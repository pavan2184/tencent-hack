from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import access_control
import pytest
from access_control import (
    AccessDecision,
    Classification,
    ConfluenceAncestor,
    ConfluencePermissions,
    DenyReason,
    Effect,
    EmailPermissions,
    GDriveAce,
    GDrivePermissions,
    JiraPermissions,
    McpExternalPermissions,
    SlackPermissions,
    SourceKind,
    SourcePermissions,
    SubjectType,
    UploadPermissions,
    parse_raw_permissions,
)
from pydantic import ValidationError

SRC = Path(__file__).resolve().parents[1] / "src"

EXPECTED_CLASS = {
    "confluence": ConfluencePermissions,
    "jira": JiraPermissions,
    "slack": SlackPermissions,
    "gdrive": GDrivePermissions,
    "email": EmailPermissions,
    "upload": UploadPermissions,
    "mcp_external": McpExternalPermissions,
}


def test_vocabulary_is_exact() -> None:
    assert [k.value for k in SourceKind] == [
        "confluence",
        "jira",
        "slack",
        "gdrive",
        "email",
        "upload",
        "gbrain_import",
        "mcp_external",
    ]
    assert [c.value for c in Classification] == ["public", "internal", "confidential", "restricted"]
    assert [e.value for e in Effect] == ["allow", "deny"]
    assert [s.value for s in SubjectType] == ["principal", "group", "role"]
    assert [r.value for r in DenyReason] == [
        "not_found",
        "explicit_deny",
        "no_source_membership",
        "classification_requires_grant",
        "grant_revoked",
        "unknown_permissions",
        "policy_default",
    ]


@pytest.mark.parametrize("kind", sorted(EXPECTED_CLASS))
def test_raw_permissions_round_trip_seed_shapes(
    kind: str, seed_blocks: dict[str, dict[str, Any]]
) -> None:
    block = seed_blocks[kind]
    raw = parse_raw_permissions(block)
    assert isinstance(raw, EXPECTED_CLASS[kind])
    assert raw.kind == kind
    # verbatim: the seed block is complete, so the JSON dump equals the input exactly
    assert raw.model_dump(mode="json") == block
    assert parse_raw_permissions(raw.model_dump(mode="json")) == raw
    # python-mode dump round-trips too (StrEnum values compare equal to their strings)
    assert parse_raw_permissions(raw.model_dump()) == raw


def test_seed_shape_details(seed_blocks: dict[str, dict[str, Any]]) -> None:
    jira = parse_raw_permissions(seed_blocks["jira"])
    assert isinstance(jira, JiraPermissions)
    assert jira.project_roles["Developers"] == ["alex.tan"]
    assert jira.issue_security_level == "finance-only"
    slack = parse_raw_permissions(seed_blocks["slack"])
    assert isinstance(slack, SlackPermissions)
    assert slack.member_ids == ["U_JORDAN", "U_PRIYA"]
    assert slack.workspace_member_ids is None
    gdrive = parse_raw_permissions(seed_blocks["gdrive"])
    assert isinstance(gdrive, GDrivePermissions)
    assert gdrive.acl == [
        GDriveAce(type="group", role="reader", email_or_domain="leadership", inherited=False)
    ]


def test_source_permissions_round_trip_and_kind_inferred(
    seed_blocks: dict[str, dict[str, Any]], now: datetime
) -> None:
    for kind, block in seed_blocks.items():
        snap = SourcePermissions.from_raw(
            block, permission_version="7", captured_at=now, connector_run_id="run-9"
        )
        assert snap.kind == kind
        dumped = snap.model_dump(mode="json")
        assert dumped["raw"] == block
        assert dumped["kind"] == kind
        assert SourcePermissions.model_validate(dumped) == snap
        assert SourcePermissions.model_validate_json(snap.model_dump_json()) == snap
        # mapping input without an explicit kind (as the seed loader builds it)
        no_kind = {"raw": block, "permission_version": "7", "captured_at": now}
        assert SourcePermissions.model_validate(no_kind).kind == kind


def test_source_permissions_kind_must_match_raw(
    seed_blocks: dict[str, dict[str, Any]], now: datetime
) -> None:
    with pytest.raises(ValidationError, match="raw.kind"):
        SourcePermissions(
            kind=SourceKind.jira,
            raw=parse_raw_permissions(seed_blocks["confluence"]),
            permission_version="1",
            captured_at=now,
        )


def test_email_from_alias(seed_blocks: dict[str, dict[str, Any]]) -> None:
    block = seed_blocks["email"]
    via_from_ = parse_raw_permissions(block)
    aliased = {k if k != "from_" else "from": v for k, v in block.items()}
    via_from = parse_raw_permissions(aliased)
    assert isinstance(via_from_, EmailPermissions) and isinstance(via_from, EmailPermissions)
    assert via_from.from_ == via_from_.from_ == "ops-bot@harbor.example"
    for dumped in (via_from.model_dump(), via_from.model_dump(by_alias=True)):
        assert "from_" in dumped and "from" not in dumped
    # the Python constructor accepts the field name
    assert EmailPermissions(message_id="m", from_="a@b.c").from_ == "a@b.c"


def test_unknown_kind_and_unknown_keys_rejected(seed_blocks: dict[str, dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        parse_raw_permissions({"kind": "gbrain_import"})
    with pytest.raises(ValidationError):
        parse_raw_permissions({"space_key": "OPS", "page_id": "1"})  # no discriminator
    typo = {**seed_blocks["confluence"], "page_view_group": ["leadership"]}
    with pytest.raises(ValidationError):
        parse_raw_permissions(typo)


def test_numeric_ids_coerced_to_str(seed_blocks: dict[str, dict[str, Any]]) -> None:
    raw = parse_raw_permissions({**seed_blocks["confluence"], "page_id": 1042, "ancestors": [7]})
    assert isinstance(raw, ConfluencePermissions)
    assert raw.page_id == "1042"
    assert raw.ancestors == ["7"]


def test_confluence_ancestors_accept_ids_and_restrictions(
    seed_blocks: dict[str, dict[str, Any]],
) -> None:
    block = {
        **seed_blocks["confluence"],
        "ancestors": ["1000", {"page_id": "1001", "view_users": [], "view_groups": ["leadership"]}],
    }
    raw = parse_raw_permissions(block)
    assert isinstance(raw, ConfluencePermissions)
    assert raw.ancestors[0] == "1000"
    assert raw.ancestors[1] == ConfluenceAncestor(page_id="1001", view_groups=["leadership"])
    assert raw.model_dump(mode="json") == block


def test_gdrive_ace_requires_target_unless_anyone() -> None:
    assert GDriveAce(type="anyone", role="reader").email_or_domain is None
    with pytest.raises(ValidationError):
        GDriveAce(type="user", role="reader")
    with pytest.raises(ValidationError):
        GDriveAce(type="group", role="viewer", email_or_domain="x")  # not a Drive role


def test_access_decision_reason_iff_deny(now: datetime) -> None:
    base = {"document_id": "d", "matched_rule": "R", "policy_version": "v", "evaluated_at": now}
    AccessDecision(decision=Effect.allow, **base)
    AccessDecision(decision=Effect.deny, reason=DenyReason.policy_default, **base)
    with pytest.raises(ValidationError):
        AccessDecision(decision=Effect.allow, reason=DenyReason.explicit_deny, **base)
    with pytest.raises(ValidationError):
        AccessDecision(decision=Effect.deny, **base)


def test_public_api() -> None:
    assert access_control.SCHEMA_VERSION == 1
    assert access_control.__version__ == "0.1.0"
    for name in access_control.__all__:
        assert hasattr(access_control, name), name


def test_no_app_import() -> None:
    pattern = re.compile(r"^\s*(from\s+app(\.|\s)|import\s+app(\.|\s|$|,))", re.MULTILINE)
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert list(SRC.rglob("*.py")), "src/ not found"
    assert offenders == [], f"access_control must never import app: {offenders}"
