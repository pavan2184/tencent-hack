"""Confluence, Jira and Gmail capture: complete responses become snapshots the policy evaluates
with the platform's own semantics; anything partial or unrepresentable is refused."""

from __future__ import annotations

from typing import Any

import pytest
from access_control import (
    confluence_permissions_from_api,
    email_permissions_from_gmail,
    jira_permissions_from_api,
)


# ----------------------------------------------------------------------------- Confluence
def space_page(*principals: tuple[str, str], operation: str = "read", next_link: str = ""):
    return {
        "results": [
            {
                "id": f"perm-{i}",
                "principal": {"type": kind, "id": pid},
                "operation": {"key": operation, "targetType": "space"},
            }
            for i, (kind, pid) in enumerate(principals)
        ],
        "_links": {"next": next_link} if next_link else {},
    }


def restriction(users: list[str] = (), groups: list[str] = (), **overrides: Any):
    user_rows = [{"type": "known", "accountId": u} for u in users]
    group_rows = [{"type": "group", "name": g, "id": g} for g in groups]
    body = {
        "operation": "read",
        "restrictions": {
            "user": {"results": user_rows, "start": 0, "size": len(user_rows)},
            "group": {"results": group_rows, "start": 0, "size": len(group_rows)},
        },
    }
    body["restrictions"].update(overrides)
    return body


def default_space_pages():
    second = space_page(("user", "mei.chen"), ("group", "finance-ops"))
    second["results"] += space_page(("group", "leadership"), operation="administer")["results"]
    first = space_page(
        ("group", "finance-ops"),
        ("group", "engineering"),
        next_link="/wiki/api/v2/spaces/9/permissions?cursor=2",
    )
    return [first, second]


def confluence(**kwargs: Any):
    return confluence_permissions_from_api(
        space_key="OPS",
        page_id="1042",
        space_permission_pages=kwargs.pop("pages", None) or default_space_pages(),
        page_restriction=kwargs.pop("page", restriction()),
        ancestor_restrictions=kwargs.pop("ancestors", ()),
    )


def test_confluence_space_audience_counts_only_read_and_dedupes():
    raw = confluence()
    assert raw.space_view_groups == ["finance-ops", "engineering"]
    assert raw.space_view_users == ["mei.chen"]
    assert "leadership" not in raw.space_view_groups  # only "read" rows count
    assert (raw.page_view_users, raw.page_view_groups, raw.ancestors) == ([], [], [])


def test_confluence_page_and_ancestor_restrictions_narrow_the_space(policy, people, make_doc, now):
    raw = confluence(
        page=restriction(groups=["finance-ops", "engineering"]),
        ancestors=[("900", restriction(groups=["finance-ops"]))],
    )
    doc = make_doc(raw.model_dump())
    assert policy.decide(people["jordan"], doc, now=now).allowed
    assert not policy.decide(people["alex"], doc, now=now).allowed  # stopped by the ancestor
    assert not policy.decide(people["sam"], doc, now=now).allowed  # not in the space


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [space_page(("group", "finance-ops"), next_link="/next")],  # last page still has next
        [space_page(("group", "a")), space_page(("group", "b"))],  # first page lacks next
        [space_page(("role", "anonymous"))],  # anonymous/access-class access: not enumerable
    ],
)
def test_confluence_incomplete_or_unenumerable_space_permissions_are_refused(pages):
    with pytest.raises(ValueError):
        confluence_permissions_from_api(
            space_key="OPS",
            page_id="1042",
            space_permission_pages=pages,
            page_restriction=restriction(),
        )


@pytest.mark.parametrize(
    "page",
    [
        restriction(group={"results": [{"id": "a"}], "start": 0, "size": 1, "totalSize": 3}),
        restriction(user={"results": [], "start": 100, "size": 0}),
        {"operation": "read", "restrictions": {"user": {"results": [], "start": 0, "size": 0}}},
        {"operation": "update", "restrictions": {}},
    ],
)
def test_confluence_partial_or_missing_restrictions_are_refused(page):
    """A truncated or missing restriction list would read as "unrestricted": fail closed."""
    with pytest.raises(ValueError):
        confluence(page=page)


# ----------------------------------------------------------------------------------- Jira
ROLES = [
    {
        "id": 10360,
        "name": "Developers",
        "actors": [
            {"type": "atlassian-user-role-actor", "actorUser": {"accountId": "alex.tan"}},
        ],
    },
    {
        "id": 10361,
        "name": "Finance",
        "actors": [
            {
                "type": "atlassian-group-role-actor",
                "actorGroup": {"name": "Finance Ops", "groupId": "finance-ops"},
            },
            {"type": "atlassian-user-role-actor", "actorUser": {"accountId": "sam.lee"}},
        ],
    },
]


def scheme(*holders: dict[str, Any]):
    return {
        "permissions": [{"holder": holder, "permission": "BROWSE_PROJECTS"} for holder in holders]
        + [{"holder": {"type": "anyone"}, "permission": "CREATE_ISSUES"}]
    }


def issue(security: dict[str, Any] | None = None):
    return {"key": "PAY-142", "fields": {"project": {"key": "PAY"}, "security": security}}


def members_page(*holders: dict[str, Any], last: bool = True):
    return {
        "isLast": last,
        "values": [{"issueSecurityLevelId": 10021, "holder": h} for h in holders],
    }


def test_jira_browse_holders_and_security_level_members(policy, people, make_doc, now):
    raw = jira_permissions_from_api(
        issue=issue({"id": "10021", "name": "Finance only"}),
        project_roles=ROLES,
        permission_scheme=scheme(
            {"type": "projectRole", "parameter": "10360", "value": "10360"},
            {"type": "projectRole", "value": "10361"},
            {"type": "group", "value": "leadership", "group": {"groupId": "leadership"}},
        ),
        security_member_pages=[
            members_page({"type": "projectRole", "value": "10361"}, last=False),
            members_page({"type": "user", "user": {"accountId": "john.tan"}}),
        ],
    )
    assert raw.browse_roles == ["Developers", "Finance", "group:leadership"]
    assert raw.project_roles["group:leadership"] == ["leadership"]
    assert raw.issue_security_level == "10021"
    assert raw.security_level_members == ["finance-ops", "sam.lee", "john.tan"]

    doc = make_doc(raw.model_dump())
    assert policy.decide(people["jordan"], doc, now=now).allowed  # Finance role via group
    assert policy.decide(people["john"], doc, now=now).allowed  # leadership + named member
    assert not policy.decide(people["alex"], doc, now=now).allowed  # browses, not in level


@pytest.mark.parametrize(
    "holder", [{"type": "reporter"}, {"type": "applicationRole"}, {"type": "anyone"}]
)
def test_jira_holders_that_cannot_be_enumerated_are_refused(holder):
    with pytest.raises(ValueError):
        jira_permissions_from_api(
            issue=issue(), project_roles=ROLES, permission_scheme=scheme(holder)
        )


def test_jira_secured_issue_needs_complete_member_pages():
    secured = issue({"id": "10021"})
    kwargs: dict[str, Any] = {
        "issue": secured,
        "project_roles": ROLES,
        "permission_scheme": scheme({"type": "projectRole", "value": "10360"}),
    }
    with pytest.raises(ValueError):
        jira_permissions_from_api(**kwargs)  # no members captured at all
    with pytest.raises(ValueError):
        jira_permissions_from_api(
            **kwargs,
            security_member_pages=[members_page({"type": "group", "value": "x"}, last=False)],
        )
    with pytest.raises(ValueError):
        jira_permissions_from_api(
            **kwargs, security_member_pages=[members_page({"type": "assignee"})]
        )


def test_jira_role_referenced_but_not_captured_is_refused():
    with pytest.raises(ValueError):
        jira_permissions_from_api(
            issue=issue(),
            project_roles=ROLES[:1],
            permission_scheme=scheme({"type": "projectRole", "value": "10361"}),
        )


# ---------------------------------------------------------------------------------- Gmail
def gmail(*headers: tuple[str, str], message_id: str = "18c0ffee"):
    return {
        "id": message_id,
        "payload": {"headers": [{"name": n, "value": v} for n, v in headers]},
    }


def test_gmail_headers_become_the_mail_audience(policy, people, make_doc, now):
    raw = email_permissions_from_gmail(
        gmail(
            ("From", "Ops Bot <ops-bot@harbor.example>"),
            ("To", "John Tan <John.Tan@harbor.example>, jordan.lim@harbor.example"),
            ("Cc", "sam.lee@harbor.example"),
            ("Message-ID", "<cutover-1@harbor.example>"),
        )
    )
    assert raw.message_id == "<cutover-1@harbor.example>"
    assert raw.from_ == "ops-bot@harbor.example"
    assert raw.to == ["John.Tan@harbor.example", "jordan.lim@harbor.example"]
    doc = make_doc(raw.model_dump())
    assert policy.decide(people["john"], doc, now=now).allowed  # case-insensitive match
    assert not policy.decide(people["alex"], doc, now=now).allowed


@pytest.mark.parametrize(
    "message",
    [
        gmail(("To", "john.tan@harbor.example")),
        gmail(("From", "a@x.example, b@x.example")),
        {"id": "1", "payload": {}},
    ],
)
def test_gmail_without_exactly_one_sender_is_refused(message):
    with pytest.raises(ValueError):
        email_permissions_from_gmail(message)
