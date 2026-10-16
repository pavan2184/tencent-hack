"""Access-control demo: authorised employee, contractor, revocation at the source, audit.

Narrates four scenes and checks each one, so it doubles as a filmable terminal demo and a smoke
test. Exit code 0 only if every check passes.

Offline, in-process (no Docker; mock providers; works on a throwaway copy of the seed corpus):

    cd backend && uv run python ../scripts/demo_access_control.py

Against the running stack (`make up && make seed`, with the Celery worker and beat running):

    cd backend && uv run python ../scripts/demo_access_control.py --api http://localhost:8000

In `--api` mode the script edits the board deck's Drive permissions in `backend/seed/corpus`
(mounted read-only into the containers), triggers a sync, and restores the file and re-syncs at
the end, even on failure. Synthetic data only: the persona header it sends is a demo shortcut.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
DECK_SOURCE = "gdrive-finance"
DECK_SLUG = "files/board-deck-q3"
DECK_FILE = Path("corpus") / DECK_SOURCE / "files" / "board-deck-q3.md"
LEADERSHIP_ACE = (
    "    - { type: group, role: reader, email_or_domain: leadership, inherited: false }\n"
)
QUESTION = "What were the Q3 board deck revenue figures?"
FIGURE = "48.6"

JOHN, MEI, ADMIN, AUDITOR = "john.tan", "mei.chen", "root.admin", "sam.lee"

failures: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)


def scene(title: str) -> None:
    say()
    say(f"== {title}")


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    say(f"   [{mark}] {label}{f'  ({detail})' if detail else ''}")
    if not ok:
        failures.append(label)


class Api:
    """Minimal client: every call names the acting persona explicitly."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def get(self, actor: str, path: str, **params: Any) -> Any:
        return self.client.get(path, params=params or None, headers={"X-Actor-Id": actor})

    def post(self, actor: str, path: str, body: dict[str, Any]) -> Any:
        return self.client.post(path, json=body, headers={"X-Actor-Id": actor})

    def ask(self, actor: str) -> dict[str, Any]:
        response = self.post(actor, "/api/ask", {"question": QUESTION})
        response.raise_for_status()
        return response.json()


def cited(envelope: dict[str, Any]) -> set[str]:
    return {c["document_id"] for c in envelope["citations"]}


def leaks_figure(envelope: dict[str, Any]) -> bool:
    return FIGURE in str((envelope["answer"], envelope["claims"], envelope["citations"]))


@contextmanager
def leadership_removed(seed_dir: Path) -> Iterator[None]:
    """Simulate the Drive owner removing Leadership from the deck's share; always restore."""
    path = seed_dir / DECK_FILE
    original = path.read_text(encoding="utf-8")
    if LEADERSHIP_ACE not in original:
        raise SystemExit(f"{path}: expected Leadership share line not found; is the seed edited?")
    path.write_text(original.replace(LEADERSHIP_ACE, "", 1), encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def sync(api: Api) -> None:
    response = api.post(ADMIN, f"/api/sources/{DECK_SOURCE}/sync", {"trigger_kind": "delta"})
    if response.status_code != 202:
        raise SystemExit(f"sync failed: {response.status_code} {response.text}")


def wait_until_denied(api: Api, deck_id: str, timeout_s: float) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if api.get(JOHN, f"/api/documents/{deck_id}").status_code == 404:
            return time.monotonic() - started
        time.sleep(1)
    return -1.0


def find_deck(api: Api) -> str:
    items = api.get(JOHN, "/api/documents", q="board deck", limit=50).json()["items"]
    for item in items:
        if item["source_id"] == DECK_SOURCE and item["slug"] == DECK_SLUG:
            return item["id"]
    raise SystemExit("Board deck not visible to John: is the corpus seeded and in sync?")


def run_demo(api: Api, seed_dir: Path, sync_timeout_s: float) -> None:
    deck_id = find_deck(api)

    scene("1. Authorised employee: John Tan (Finance Ops, Leadership)")
    say(f'   asks: "{QUESTION}"')
    before = api.ask(JOHN)
    say(f"   answer: {before['answer']['text'][:110]}...")
    check("answer cites the board deck", deck_id in cited(before))
    check("answer contains the Q3 figure", FIGURE in before["answer"]["text"])

    scene("2. Unauthorised contractor: Mei Chen")
    contractor = api.ask(MEI)
    say(f"   answer: {contractor['answer']['text'][:110]}")
    check("no restricted content in the answer, claims or citations", not leaks_figure(contractor))
    check("board deck not cited", deck_id not in cited(contractor))
    check(
        "access summary has an allowed count and no denied count",
        set(contractor["access_summary"])
        == {"principal_id", "policy_version", "allowed_count", "evaluated_at"},
    )
    denied = api.get(MEI, f"/api/documents/{deck_id}")
    missing = api.get(MEI, f"/api/documents/{uuid.uuid4()}")
    check(
        "opening the deck looks exactly like a missing document",
        denied.status_code == missing.status_code == 404
        and denied.json()["error"]["message"] == missing.json()["error"]["message"],
    )

    scene("3. Revoked at the source: the Drive owner removes Leadership from the share")
    with leadership_removed(seed_dir):
        say(f"   edited {DECK_FILE} (Leadership share line removed); triggering a sync")
        sync(api)
        waited = wait_until_denied(api, deck_id, sync_timeout_s)
        check(
            "John loses the deck after the sync",
            waited >= 0,
            f"{waited:.0f}s after the sync request" if waited >= 0 else "timed out",
        )
        after = api.ask(JOHN)
        say(f"   John asks again: {after['answer']['text'][:110]}")
        check("new answer no longer cites the deck", deck_id not in cited(after))
        check("new answer does not contain the Q3 figure", not leaks_figure(after))
        saved = api.get(JOHN, f"/api/queries/{before['query_id']}").json()
        check(
            "the saved answer from scene 1 is withheld",
            saved.get("status") == "withheld" and FIGURE not in str(saved),
            "needs the saved-answer re-check (PR #6)" if saved.get("status") != "withheld" else "",
        )

        scene("4. Audit inquiry: Sam Lee (compliance)")
        event = api.get(AUDITOR, f"/api/audit/events/{after['audit_id']}").json()
        decisions = {d["document_id"]: d for d in event["payload"]["access_decisions"]}
        deck_decision = decisions.get(deck_id, {})
        say(
            f"   deck decision: {deck_decision.get('decision')} / {deck_decision.get('reason')}"
            f" / rule {deck_decision.get('matched_rule')}"
            f" / permissions read at {deck_decision.get('permission_captured_at')}"
        )
        check(
            "audit records the deny for the deck",
            deck_decision.get("decision") == "deny"
            and deck_decision.get("reason") == "no_source_membership",
        )
        original = api.get(AUDITOR, f"/api/audit/events/{before['audit_id']}").json()
        check(
            "Sam sees scene 1's decisions but not its answer content",
            original.get("content_withheld") is True and FIGURE not in str(original),
        )
        reason = "Compliance review of board deck access, case 42"
        revealed = api.post(
            AUDITOR, f"/api/audit/events/{before['audit_id']}/reveal", {"reason": reason}
        )
        check(
            "a reveal with a reason shows the original answer",
            revealed.status_code == 200
            and FIGURE in str(revealed.json()["payload"]["answer_text"]),
        )
        reveals = api.get(AUDITOR, "/api/audit/events", action="audit.reveal").json()["items"]
        check(
            "the reveal itself is recorded in the audit trail",
            any(
                r["subject_id"] == before["audit_id"] and r["payload"]["reason"] == reason
                for r in reveals
            ),
        )
        chain = api.get(AUDITOR, "/api/audit/verify").json()
        check("hash chain verifies", chain.get("ok") is True, f"{chain.get('length')} events")

    say()
    say("   restored the Leadership share; re-syncing")
    sync(api)


def in_process(sync_timeout_s: float) -> None:
    workdir = Path(tempfile.mkdtemp(prefix="brain-demo-"))
    seed_dir = workdir / "seed"
    shutil.copytree(BACKEND_DIR / "seed", seed_dir)
    os.environ.update(
        {
            "ENV": "test",
            "REPO_BACKEND": "memory",
            "PROVIDER_MODE": "mock",
            "CELERY_TASK_ALWAYS_EAGER": "true",
            "SEED_DIR": str(seed_dir),
            "UPLOAD_DIR": str(workdir / "uploads"),
            "LOG_LEVEL": "warning",
        }
    )
    sys.path.insert(0, str(BACKEND_DIR))
    import asyncio

    import app.config

    app.config.get_settings.cache_clear()
    app.config.settings = app.config.get_settings()
    from fastapi.testclient import TestClient

    from app.db.repo import set_repo
    from app.main import app as fastapi_app
    from app.seed import load_seed
    from app.services.wiring import build_services, set_services

    services = build_services(app.config.get_settings())
    set_repo(None)
    set_services(services)
    asyncio.run(load_seed(services, str(seed_dir)))
    say(f"In-process demo on a copy of the seed corpus at {seed_dir}")
    try:
        with TestClient(fastapi_app) as client:
            run_demo(Api(client), seed_dir, sync_timeout_s)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def against_stack(base_url: str, sync_timeout_s: float) -> None:
    import httpx

    say(f"Demo against {base_url}, editing {BACKEND_DIR / 'seed'}")
    with httpx.Client(base_url=base_url, timeout=60) as client:
        run_demo(Api(client), BACKEND_DIR / "seed", sync_timeout_s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", help="base URL of a running stack, e.g. http://localhost:8000")
    parser.add_argument(
        "--sync-timeout", type=float, default=90, help="seconds to wait (default 90)"
    )
    args = parser.parse_args()
    if args.api:
        against_stack(args.api.rstrip("/"), args.sync_timeout)
    else:
        in_process(args.sync_timeout)
    say()
    if failures:
        say(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    say("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
