"""R8: each platform's own read semantics, evaluated from the raw snapshot (never flattened)."""

from __future__ import annotations

from typing import Any

import pytest
from access_control import Effect, Principal


@pytest.fixture
def allowed(policy, make_doc, now):
    """``allowed(principal, raw) -> bool`` for an internal doc with that raw snapshot."""

    def _allowed(principal: Principal, raw: dict[str, Any]) -> bool:
        decision = policy.decide(principal, make_doc(raw), now=now)
        expected_rule = f"R8:{raw['kind']}"
        assert decision.matched_rule == expected_rule, decision
        return decision.decision == Effect.allow

    return _allowed


# -- Confluence ---------------------------------------------------------------------------


def test_confluence_space_view_groups(allowed, people, seed_blocks):
    space = seed_blocks["confluence"]  # finance-ops + engineering
    assert allowed(people["alex"], space)
    assert allowed(people["jordan"], space)
    assert not allowed(people["mei"], space)
    assert not allowed(people["sam"], space)


def test_confluence_page_restriction_overrides_space(allowed, people, seed_blocks):
    page = {**seed_blocks["confluence"], "page_view_groups": ["finance-ops"]}
    assert not allowed(people["alex"], page)  # in the space audience, not in the page restriction
    assert allowed(people["jordan"], page)


def test_confluence_page_restriction_never_widens_space(allowed, people, seed_blocks):
    page = {**seed_blocks["confluence"], "page_view_users": ["mei.chen"]}
    assert not allowed(people["mei"], page)  # named on the page but has no space view
    assert not allowed(people["alex"], page)


def test_confluence_space_view_user_via_external_identity(allowed, people, seed_blocks):
    space = {**seed_blocks["confluence"], "space_view_groups": [], "space_view_users": ["cf-mei"]}
    mei = people["mei"].model_copy(update={"external_identities": {"confluence": "cf-mei"}})
    assert allowed(mei, space)
    assert not allowed(people["mei"], space)  # falls back to "mei.chen", which is not listed


def test_confluence_ancestor_restriction_is_inherited(allowed, people, seed_blocks):
    restricted_parent = {"page_id": "1000", "view_users": [], "view_groups": ["finance-ops"]}
    page = {**seed_blocks["confluence"], "ancestors": ["999", restricted_parent]}
    assert allowed(people["jordan"], page)
    assert not allowed(people["alex"], page)
    unrestricted = {**seed_blocks["confluence"], "ancestors": ["999", {"page_id": "1000"}]}
    assert allowed(people["alex"], unrestricted)


# -- Jira ---------------------------------------------------------------------------------


def test_jira_security_level_excludes_browse_role_holder(allowed, people, seed_blocks):
    issue = seed_blocks["jira"]  # PAY-142, security level finance-only
    assert not allowed(people["alex"], issue)  # Developers can browse PAY, but not this level
    assert allowed(people["john"], issue)
    assert allowed(people["jordan"], issue)


def test_jira_without_security_level_any_browse_role(allowed, people, seed_blocks):
    issue = {
        **seed_blocks["jira"],
        "issue_key": "PAY-150",
        "issue_security_level": None,
        "security_level_members": [],
    }
    assert allowed(people["alex"], issue)
    assert not allowed(people["mei"], issue)  # holds no project role


def test_jira_role_without_browse_permission_denied(allowed, people, seed_blocks):
    issue = {**seed_blocks["jira"], "issue_security_level": None, "browse_roles": ["Finance"]}
    assert not allowed(people["alex"], issue)  # Developers role exists but cannot browse
    assert allowed(people["jordan"], issue)


def test_jira_group_role_actor_and_group_security_member(allowed, people, seed_blocks):
    issue = {
        **seed_blocks["jira"],
        "project_roles": {"Auditors": ["compliance"]},
        "browse_roles": ["Auditors"],
        "security_level_members": ["compliance"],
    }
    assert allowed(people["sam"], issue)
    assert not allowed(people["john"], issue)


# -- Slack --------------------------------------------------------------------------------


def test_slack_private_channel_membership(allowed, people, seed_blocks):
    treasury = seed_blocks["slack"]  # #treasury-ops: U_JORDAN, U_JOHN
    assert allowed(people["jordan"], treasury)
    assert allowed(people["john"], treasury)
    assert not allowed(people["alex"], treasury)
    assert not allowed(people["mei"], treasury)  # no slack identity → "mei.chen" not a member


def test_slack_public_channel(allowed, people, seed_blocks):
    general = {
        **seed_blocks["slack"],
        "channel_id": "C_GENERAL",
        "channel_type": "public",
        "member_ids": [],
    }
    assert allowed(people["alex"], general)  # workspace roster not captured → any principal
    assert allowed(people["mei"], general)
    rostered = {**general, "workspace_member_ids": ["U_ALEX", "U_JOHN", "U_JORDAN"]}
    assert allowed(people["alex"], rostered)
    assert not allowed(people["mei"], rostered)


@pytest.mark.parametrize("channel_type", ["dm", "mpdm"])
def test_slack_dm_requires_membership(allowed, people, seed_blocks, channel_type):
    dm = {**seed_blocks["slack"], "channel_type": channel_type, "member_ids": ["U_ALEX"]}
    assert allowed(people["alex"], dm)
    assert not allowed(people["jordan"], dm)


# -- Google Drive -------------------------------------------------------------------------


def _drive(seed_blocks: dict[str, dict[str, Any]], *acl: dict[str, Any]) -> dict[str, Any]:
    return {**seed_blocks["gdrive"], "acl": list(acl)}


def test_gdrive_group_ace(allowed, people, seed_blocks):
    deck = seed_blocks["gdrive"]  # group:leadership reader
    assert allowed(people["john"], deck)
    assert not allowed(people["jordan"], deck)


def test_gdrive_anyone_ace(allowed, people, seed_blocks):
    assert allowed(people["mei"], _drive(seed_blocks, {"type": "anyone", "role": "reader"}))


def test_gdrive_domain_ace(allowed, people, seed_blocks):
    vendor_list = _drive(
        seed_blocks, {"type": "domain", "role": "commenter", "email_or_domain": "Harbor.Example"}
    )
    assert allowed(people["mei"], vendor_list)
    outsider = people["mei"].model_copy(update={"email": "mei@contractor.example"})
    assert not allowed(outsider, vendor_list)


def test_gdrive_user_ace_case_insensitive(allowed, people, seed_blocks):
    shared = _drive(
        seed_blocks,
        {"type": "user", "role": "writer", "email_or_domain": "Alex.Tan@Harbor.example"},
    )
    assert allowed(people["alex"], shared)
    assert not allowed(people["john"], shared)


def test_gdrive_user_ace_via_external_identity(allowed, people, seed_blocks):
    shared = _drive(
        seed_blocks, {"type": "user", "role": "reader", "email_or_domain": "mei@gmail.example"}
    )
    mei = people["mei"].model_copy(update={"external_identities": {"gdrive": "mei@gmail.example"}})
    assert allowed(mei, shared)


def test_gdrive_inherited_folder_ace_counts(allowed, people, seed_blocks):
    shared = _drive(
        seed_blocks,
        {"type": "group", "role": "reader", "email_or_domain": "compliance", "inherited": True},
    )
    assert allowed(people["sam"], shared)


def test_gdrive_empty_acl_denies(allowed, people, seed_blocks):
    assert not allowed(people["john"], _drive(seed_blocks))


# -- Email --------------------------------------------------------------------------------


def test_email_cc_recipient(allowed, people, seed_blocks):
    cutover = seed_blocks["email"]  # to john, cc jordan
    assert allowed(people["john"], cutover)
    assert allowed(people["jordan"], cutover)  # cc
    assert not allowed(people["alex"], cutover)


def test_email_sender_bcc_display_names_and_case(allowed, people, seed_blocks):
    msg = {
        **seed_blocks["email"],
        "from_": "Sam Lee <SAM.LEE@harbor.example>",
        "to": [],
        "cc": [],
        "bcc": ["Mei Chen <mei.chen@HARBOR.example>"],
    }
    assert allowed(people["sam"], msg)
    assert allowed(people["mei"], msg)
    assert not allowed(people["john"], msg)


def test_email_principal_without_address_denied(allowed, people, seed_blocks):
    no_mail = people["jordan"].model_copy(update={"email": None})
    assert not allowed(no_mail, seed_blocks["email"])


# -- Upload -------------------------------------------------------------------------------


def test_upload_owner_and_shared(allowed, people, seed_blocks):
    upload = seed_blocks["upload"]  # owner alex.tan, not shared
    assert allowed(people["alex"], upload)
    assert not allowed(people["jordan"], upload)
    shared_group = {**upload, "shared_with_groups": ["finance-ops"]}
    assert allowed(people["jordan"], shared_group)
    assert allowed(people["john"], shared_group)
    assert not allowed(people["mei"], shared_group)
    shared_user = {**upload, "shared_with_principals": ["mei.chen"]}
    assert allowed(people["mei"], shared_user)


# -- MCP external -------------------------------------------------------------------------


def test_mcp_external_allow_lists(allowed, people, seed_blocks):
    app = seed_blocks["mcp_external"]  # sam.lee + group finance-ops
    assert allowed(people["sam"], app)
    assert allowed(people["jordan"], app)
    assert not allowed(people["alex"], app)
    assert not allowed(people["mei"], app)
