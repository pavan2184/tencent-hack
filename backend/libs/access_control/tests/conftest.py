"""Shared fixtures. Tests use fixtures only (never ``from conftest import …``) so the suite also
runs under ``--import-mode=importlib`` alongside the other libs' same-named test modules."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

import pytest
from access_control import (
    Classification,
    DefaultAccessPolicy,
    DocumentAccessContext,
    Effect,
    Grant,
    Principal,
    SourceKind,
    SourcePermissions,
    SubjectType,
)

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
DOMAIN = "harbor.example"


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def policy() -> DefaultAccessPolicy:
    return DefaultAccessPolicy()


@pytest.fixture
def people() -> dict[str, Principal]:
    """The seeded demo personas (plan: seed/principals.yaml)."""

    def p(pid: str, name: str, roles: list[str], groups: list[str], **ext: str) -> Principal:
        return Principal(
            id=pid,
            display_name=name,
            email=f"{pid}@{DOMAIN}",
            roles=roles,
            groups=groups,
            external_identities=ext,
        )

    return {
        "alex": p("alex.tan", "Alex Tan", ["employee"], ["engineering"], slack="U_ALEX"),
        "john": p(
            "john.tan", "John Tan", ["manager"], ["finance-ops", "leadership"], slack="U_JOHN"
        ),
        "sam": p("sam.lee", "Sam Lee", ["auditor"], ["compliance"], slack="U_SAM"),
        "root": p("root.admin", "Root Admin", ["admin"], []),
        "jordan": p("jordan.lim", "Jordan Lim", ["employee"], ["finance-ops"], slack="U_JORDAN"),
        "mei": p("mei.chen", "Mei Chen", ["contractor"], []),
    }


@pytest.fixture
def seed_blocks() -> dict[str, dict[str, Any]]:
    """Frontmatter ``permissions:`` blocks in the exact shapes the seed corpus uses."""

    return {
        "confluence": {
            "kind": "confluence",
            "space_key": "OPS",
            "page_id": "1042",
            "space_view_users": [],
            "space_view_groups": ["finance-ops", "engineering"],
            "page_view_users": [],
            "page_view_groups": [],
            "ancestors": [],
        },
        "jira": {
            "kind": "jira",
            "project_key": "PAY",
            "issue_key": "PAY-142",
            "project_roles": {"Developers": ["alex.tan"], "Finance": ["john.tan", "jordan.lim"]},
            "browse_roles": ["Developers", "Finance"],
            "issue_security_level": "finance-only",
            "security_level_members": ["john.tan", "jordan.lim"],
        },
        "slack": {
            "kind": "slack",
            "workspace_id": "T_HARBOR",
            "channel_id": "C_TREASURY_OPS",
            "channel_type": "private",
            "member_ids": ["U_JORDAN", "U_JOHN"],
            "workspace_member_ids": None,
        },
        "gdrive": {
            "kind": "gdrive",
            "file_id": "board-deck-q3",
            "parent_ids": ["folder-board"],
            "acl": [
                {
                    "type": "group",
                    "role": "reader",
                    "email_or_domain": "leadership",
                    "inherited": False,
                    "expiration_time": None,
                    "deleted": False,
                    "allow_file_discovery": True,
                }
            ],
        },
        "email": {
            "kind": "email",
            "message_id": "<vendor-cutover-001@harbor.example>",
            "from_": "ops-bot@harbor.example",
            "to": ["john.tan@harbor.example"],
            "cc": ["jordan.lim@harbor.example"],
            "bcc": [],
        },
        "upload": {
            "kind": "upload",
            "owner_principal_id": "alex.tan",
            "shared_with_principals": [],
            "shared_with_groups": [],
        },
        "mcp_external": {
            "kind": "mcp_external",
            "app_name": "vendor-portal",
            "allowed_principals": ["sam.lee"],
            "allowed_groups": ["finance-ops"],
        },
    }


@pytest.fixture
def make_grant(now: datetime) -> Callable[..., Grant]:
    def _make(
        subject_type: SubjectType,
        subject_id: str,
        effect: Effect = Effect.allow,
        *,
        document_id: str = "doc-1",
        revoked: bool = False,
        scope: str = "read",
        grant_id: str | None = None,
    ) -> Grant:
        extra: dict[str, Any] = {"id": grant_id} if grant_id else {}
        return Grant(
            document_id=document_id,
            subject_type=subject_type,
            subject_id=subject_id,
            effect=effect,
            scope=scope,
            granted_by="root.admin",
            granted_at=now,
            revoked_at=now if revoked else None,
            revoked_by="root.admin" if revoked else None,
            **extra,
        )

    return _make


@pytest.fixture
def make_doc(now: datetime) -> Callable[..., DocumentAccessContext]:
    """Build a ``DocumentAccessContext``; ``raw`` is a frontmatter permissions mapping or None."""

    def _make(
        raw: dict[str, Any] | None = None,
        *,
        document_id: str = "doc-1",
        classification: Classification = Classification.internal,
        owner: str | None = None,
        grants: Iterable[Grant] = (),
        permission_version: str | None = "pv-1",
        snapshot_version: str | None = None,
        source_kind: SourceKind | None = None,
    ) -> DocumentAccessContext:
        snapshot = (
            SourcePermissions.from_raw(
                raw,
                permission_version=snapshot_version or permission_version or "pv-1",
                captured_at=now,
                connector_run_id="run-1",
            )
            if raw is not None
            else None
        )
        kind = source_kind or (snapshot.kind if snapshot else SourceKind.upload)
        return DocumentAccessContext(
            document_id=document_id,
            source_id=f"src-{kind}",
            source_kind=kind,
            classification=classification,
            owner_principal_id=owner,
            source_permissions=snapshot,
            grants=list(grants),
            permission_version=permission_version,
        )

    return _make
