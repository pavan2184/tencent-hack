"""Fill the composition's __PLACEHOLDER__ tokens from assets/shots/facts.json (written by shoot.mjs).

Every value shown in the audit chain, the verify chip, the 404 band and the "same hash" tiles is
a real value from the shoot, never typed in by hand. Idempotent: run it once after a shoot; a
second run finds no tokens and does nothing.

Usage: python3 script/fill.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
FACTS = ROOT / "assets" / "shots" / "facts.json"


def short(h: str | None, n: int = 10) -> str:
    return f"{h[:n]}…" if h else "—"


def report_hash(run: dict) -> str:
    rep = run.get("report") or {}
    for key in ("report_hash", "hash", "sha256", "digest", "id", "report_id"):
        if rep.get(key):
            return str(rep[key])
    return json.dumps(rep, sort_keys=True)[:72]


def main() -> None:
    facts = json.loads(FACTS.read_text())
    page = INDEX.read_text()
    if "__" not in page:
        print("no placeholders left; nothing to do")
        return
    values: dict[str, str] = {}

    deck_404, random_404 = facts["mei_404"]
    values["__404_DECK__"] = "404 " + json.dumps(deck_404, separators=(", ", ": "))
    values["__404_RANDOM__"] = "404 " + json.dumps(random_404, separators=(", ", ": "))

    # Two identical asks: the grounding content must match field for field. `report_hash` is
    # tamper evidence over the whole report including `created_at`, so it is not compared here.
    runs = facts.get("determinism") or []
    if len(runs) < 2:
        sys.exit("facts.json has no determinism runs; re-run shoot.mjs")
    content = []
    for run in runs[:2]:
        rep = dict(run.get("report") or {})
        rep.pop("created_at", None)
        rep.pop("report_hash", None)
        content.append(rep)
    if content[0] != content[1]:
        sys.exit("grounding reports differ between the two identical asks; fix before rendering")
    rep = content[0]
    summary = (
        f"verdict {rep.get('verdict')} · coverage {float(rep.get('coverage_ratio', 0)) * 100:.0f} % · "
        f"{rep.get('claims_total')} claims · {rep.get('supported')} supported · "
        f"{rep.get('contradicted')} contradicted · {rep.get('injection_flags')} injection flags · "
        f"quarantined {', '.join(rep.get('quarantined_evidence_ids') or []) or 'none'}"
    )
    values["__REPORT_1__"] = summary
    values["__REPORT_2__"] = summary
    values["__REPORT_CLAIMS__"] = " · ".join(
        f"C{i + 1} {c.get('label') or c.get('verdict') or ''}".strip()
        for i, c in enumerate(rep.get("per_claim") or [])
    ) or "—"

    recent = facts["audit_recent"]
    items = recent.get("items", recent)
    items = sorted(items, key=lambda e: e["seq"])
    # The four most recent events: John's cited ask, the sync, John's denied ask, Sam's reveal.
    wanted = [e for e in items if e["action"] in ("ask", "audit.reveal", "source.sync", "sync")]
    chosen = (wanted or items)[-4:]
    while len(chosen) < 4:
        chosen.insert(0, {"seq": "", "action": "", "actor_id": "", "hash": "", "prev_hash": ""})
    for i, e in enumerate(chosen, start=1):
        values[f"__SEQ{i}__"] = f"#{e['seq']}" if e.get("seq") != "" else "—"
        values[f"__ACT{i}__"] = e.get("action") or "—"
        values[f"__ACTOR{i}__"] = e.get("actor_id") or "system"
        values[f"__HASH{i}__"] = short(e.get("hash"))
        values[f"__PREV{i}__"] = short(e.get("prev_hash"))

    v = facts["audit_verify"]
    values["__VERIFY__"] = (
        f"ok: true · {v.get('length')} events · head {short(v.get('head_hash'))}"
        if v.get("ok")
        else f"ok: false · first broken seq {v.get('first_broken_seq')}"
    )

    for token, value in values.items():
        page = page.replace(token, html.escape(value, quote=False))
    left = re.findall(r"__[A-Z0-9_]+__", page)
    if left:
        sys.exit(f"unfilled placeholders: {sorted(set(left))}")
    INDEX.write_text(page)
    for token, value in values.items():
        print(f"{token:20s} {value[:90]}")


if __name__ == "__main__":
    main()
