"""Run from backend: uv run --frozen python libs/access_control/examples/revocation_demo.py.

Synthetic corpus only. This output is an internal demonstration, not a public API response.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from access_control import (
    AccessControlService,
    DocumentAccessContext,
    Grant,
    InMemoryGrantStore,
    InMemoryPermissionSnapshotStore,
    InMemoryPrincipalDirectory,
    Principal,
    SourcePermissions,
)


def load_seed(now: datetime):
    """Load only the checked-in synthetic fixture, never arbitrary uploaded frontmatter."""
    seed = Path(__file__).resolve().parents[3] / "seed"
    principals = [
        Principal.model_validate(p)
        for p in yaml.safe_load((seed / "principals.yaml").read_text())["principals"]
    ]
    docs = []
    bodies = {}
    for path in sorted((seed / "corpus").rglob("*.md")):
        text = path.read_text()
        if not text.startswith("---\n"):
            continue
        _, frontmatter, body = text.split("---\n", 2)
        metadata = yaml.safe_load(frontmatter)
        if "permissions" not in metadata:
            continue
        doc_id = metadata["external_object_id"]
        grants = [
            Grant(
                id=f"{doc_id}-grant-{index}",
                document_id=doc_id,
                granted_by="root.admin",
                granted_at=now,
                **grant,
            )
            for index, grant in enumerate(metadata.get("grants", []))
        ]
        docs.append(
            DocumentAccessContext(
                document_id=doc_id,
                source_id=path.relative_to(seed / "corpus").parts[0],
                source_kind=metadata["source_kind"],
                classification=metadata["classification"],
                owner_principal_id=metadata.get("owner"),
                permission_version=metadata["permission_version"],
                source_permissions=SourcePermissions.from_raw(
                    metadata["permissions"],
                    permission_version=metadata["permission_version"],
                    captured_at=now,
                    connector_run_id="synthetic-demo",
                ),
                grants=grants,
            )
        )
        bodies[doc_id] = body
    return principals, docs, bodies


async def run_demo() -> dict:
    now = datetime(2026, 10, 12, 9, tzinfo=UTC)
    principals, docs, bodies = load_seed(now)
    grants = InMemoryGrantStore(g for doc in docs for g in doc.grants)
    snapshots = InMemoryPermissionSnapshotStore(
        {doc.document_id: doc.source_permissions for doc in docs}
    )
    service = AccessControlService(
        directory=InMemoryPrincipalDirectory(principals), grants=grants, snapshots=snapshots
    )
    board = next(doc for doc in docs if "BoardDeck" in doc.document_id)
    visibility = {
        principal.id: (await service.filter(principal.id, docs, now=now)).allowed_ids
        for principal in principals
    }
    before = await service.filter("priya.nair", docs, now=now)
    outsider = await service.filter("mei.chen", docs, now=now)
    await grants.revoke(board.grants[0].id, by="root.admin", at=now)
    after = await service.filter("priya.nair", docs, now=now)
    assert board.document_id in before.allowed_ids
    assert board.document_id not in after.allowed_ids
    assert outsider.allowed_ids == []
    model_context = [bodies[doc_id] for doc_id in after.allowed_ids]
    assert bodies[board.document_id] not in model_context
    return {
        "mode": "synthetic in-memory demonstration",
        "documents": len(docs),
        "visibility_before_revocation": visibility,
        "policy_version": service.policy.policy_version,
        "before_board_allowed": True,
        "after_board_allowed": False,
        "outsider_allowed_count": len(outsider.allowed_ids),
        "revoked_body_in_model_context": False,
        "audit_rule": next(
            d.matched_rule for d in after.decisions if d.document_id == board.document_id
        ),
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), indent=2))
