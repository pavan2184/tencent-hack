"""Seed loader (`make seed` -> `ROLE=seed` -> `python -m app.seed`). Idempotent.

1. principals + groups + memberships from `principals.yaml`, and each group's optional
   `parents` and `platform_ids` (group resolution, `services.group_directory`);
2. freshness policies from `policies.yaml` (`freshness_store.put_policy`);
3. for each `corpus/<source>/source.yaml`: register the source (`local_path` = that directory)
   and run a `reconcile` sync through the `gbrain_import` connector (pages, permission snapshots,
   frontmatter grants with `granted_by="system:seed"`, object freshness, chunks + embeddings);
   the idempotency key includes a digest of the directory, so an unchanged corpus replays the
   completed run and a changed one syncs again (same versions are no-ops, no duplicates);
4. live-verify every seeded object once, so `last_verified_at` is the seed time (critical
   evidence then starts `fresh` unless the provider differs, e.g. `simulate.live_version`);
5. audit `seed.loaded`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from access_control import GroupDefinition, Principal
from freshness import FreshnessPolicy
from pydantic import BaseModel, Field

from app.schemas.domain import Group
from app.services import audit
from app.services.documents import verify_object
from app.services.sources import add_source, run_sync

if TYPE_CHECKING:
    from app.services.wiring import Services

logger = logging.getLogger(__name__)

SEED_ACTOR = "system:seed"


class SeedSummary(BaseModel):
    principals: int = 0
    groups: int = 0
    policies: int = 0
    sources: int = 0
    pages: int = 0
    grants: int = 0
    runs: list[dict[str, Any]] = Field(default_factory=list)
    verified: dict[str, int] = Field(default_factory=dict)


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _dir_digest(directory: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            h.update(path.relative_to(directory).as_posix().encode("utf-8"))
            h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()[:16]


async def _load_principals(services: Services, path: Path, summary: SeedSummary) -> None:
    data = _load_yaml(path) or {}
    groups = data.get("groups") or []
    for group in groups:
        await services.repo.upsert_group(Group(id=str(group["id"]), name=str(group["name"])))
        summary.groups += 1
    # Nesting and platform ids (group resolution) once every group exists.
    for group in groups:
        if group.get("parents") or group.get("platform_ids"):
            await services.group_directory.put(
                GroupDefinition(
                    id=str(group["id"]),
                    parent_ids=[str(p) for p in group.get("parents") or []],
                    platform_ids={
                        str(k): str(v) for k, v in (group.get("platform_ids") or {}).items()
                    },
                )
            )
    for item in data.get("principals") or []:
        principal = Principal(
            id=str(item["id"]),
            display_name=str(item["display_name"]),
            email=item.get("email"),
            roles=[str(r) for r in item.get("roles") or []],
            external_identities={
                str(k): str(v) for k, v in (item.get("external_identities") or {}).items()
            },
            is_active=bool(item.get("is_active", True)),
        )
        await services.repo.upsert_principal(principal)
        await services.repo.set_memberships(
            principal.id, [str(g) for g in item.get("groups") or []]
        )
        summary.principals += 1


async def _load_policies(services: Services, path: Path, summary: SeedSummary) -> None:
    for item in _load_yaml(path) or []:
        await services.freshness_store.put_policy(FreshnessPolicy.model_validate(item))
        summary.policies += 1


async def _load_source(services: Services, directory: Path, summary: SeedSummary) -> None:
    meta = _load_yaml(directory / "source.yaml") or {}
    source_id = str(meta.get("id") or directory.name)
    kind = str(meta["kind"])
    connector = "upload" if kind == "upload" else "gbrain_import"
    source = await add_source(
        services,
        id=source_id,
        name=str(meta.get("name") or source_id),
        kind=kind,
        local_path=None if connector == "upload" else str(directory.resolve()),
        config={"connector": connector},
        description=str(meta.get("description") or ""),
    )
    summary.sources += 1
    if connector == "upload":
        return
    key = f"seed:{source.id}:{_dir_digest(directory)}"
    result = await run_sync(services, source.id, "reconcile", key, granted_by=SEED_ACTOR)
    summary.runs.append(
        {
            "source_id": source.id,
            "run_id": result.run_id,
            "status": str(result.status),
            "replayed": result.replayed,
            "applied": result.applied_count,
            "parked": result.parked_count,
        }
    )
    pages = await services.repo.list_pages(source_ids=[source.id], limit=10_000)
    summary.pages += len(pages)
    grants = await services.grant_store.list_for_documents([p.id for p in pages])
    summary.grants += sum(1 for gs in grants.values() for g in gs if g.revoked_at is None)
    for page in pages:
        if not page.external_object_id:
            continue
        verified = await verify_object(services, source.id, page.external_object_id)
        status = str(verified.verification_result)
        summary.verified[status] = summary.verified.get(status, 0) + 1


async def load_seed(services: Services, seed_dir: str) -> SeedSummary:
    root = Path(seed_dir)
    if not (root / "principals.yaml").is_file():
        raise FileNotFoundError(f"seed directory {root} has no principals.yaml")
    summary = SeedSummary()
    await _load_principals(services, root / "principals.yaml", summary)
    if (root / "policies.yaml").is_file():
        await _load_policies(services, root / "policies.yaml", summary)
    corpus = root / "corpus"
    if corpus.is_dir():
        for directory in sorted(p for p in corpus.iterdir() if p.is_dir()):
            if (directory / "source.yaml").is_file():
                await _load_source(services, directory, summary)
    await audit.record(
        services,
        actor_id=None,
        action="seed.loaded",
        subject_type="seed",
        subject_id=str(root.name),
        payload={"summary": summary.model_dump(mode="json"), "seed_actor": SEED_ACTOR},
    )
    return summary


async def _main() -> SeedSummary:
    from app.config import get_settings
    from app.core.logging import configure_logging
    from app.services.wiring import build_services, set_services

    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    services = build_services(settings)
    set_services(services)
    try:
        return await load_seed(services, settings.SEED_DIR)
    finally:
        if settings.REPO_BACKEND == "sql":
            try:
                from app.db.session import dispose_engine

                await dispose_engine()
            except Exception:  # noqa: BLE001
                logger.warning("engine dispose failed", exc_info=True)


if __name__ == "__main__":
    print(json.dumps(asyncio.run(_main()).model_dump(mode="json"), indent=2))
