"""Normalise captured provider responses without fetching data or storing credentials.

Only complete pages are accepted. Connectors must request all ACL fields, use trusted API
responses, and independently refresh identity/group membership. Document text is never authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from email.utils import getaddresses
from typing import Any

from access_control.permissions import (
    ConfluenceAncestor,
    ConfluencePermissions,
    EmailPermissions,
    GDriveAce,
    GDrivePermissions,
    JiraPermissions,
    RawPermissions,
    SlackChannelType,
    SlackPermissions,
    parse_raw_permissions,
)


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a non-empty provider identifier")
    return value


def _flag(data: Mapping[str, Any], key: str, *, default: bool | None = None) -> bool:
    value = data.get(key, default)
    if type(value) is not bool:
        raise ValueError(f"Missing or invalid provider flag: {key}")
    return value


def _pages(pages: Sequence[Mapping[str, Any]], key: str, *, slack: bool) -> list[Any]:
    if not pages:
        raise ValueError("At least one complete provider page is required")
    items: list[Any] = []
    seen: set[str] = set()
    for index, page in enumerate(pages):
        if not isinstance(page, Mapping):
            raise ValueError("Invalid provider page")
        if slack and page.get("ok") is not True:
            raise ValueError("Slack API did not confirm success")
        rows = page.get(key)
        if not isinstance(rows, list):
            raise ValueError(f"Missing provider list: {key}")
        metadata = page.get("response_metadata", {})
        if slack and not isinstance(metadata, Mapping):
            raise ValueError("Invalid Slack response metadata")
        cursor = metadata.get("next_cursor", "") if slack else page.get("nextPageToken", "")
        if not isinstance(cursor, str):
            raise ValueError("Invalid pagination cursor")
        if bool(cursor) != (index < len(pages) - 1) or (cursor and cursor in seen):
            raise ValueError("Incomplete or inconsistent provider pagination")
        seen.add(cursor)
        items.extend(rows)
    return items


def slack_permissions_from_api(
    *,
    workspace_id: str,
    channel: Mapping[str, Any],
    member_pages: Sequence[Mapping[str, Any]],
    workspace_pages: Sequence[Mapping[str, Any]] | None = None,
) -> SlackPermissions:
    """Capture conversations.info/members and, optionally, complete users.list pages.

    Full workspace users require explicit guest/deactivation flags. Guests and Slack Connect
    users may still read channels where the member list explicitly includes them.
    """
    workspace_id = _text(workspace_id)
    if channel.get("ok") is not True or not isinstance(channel.get("channel"), Mapping):
        raise ValueError("Invalid conversations.info response")
    info = channel["channel"]
    if _flag(info, "is_im", default=False):
        kind = SlackChannelType.dm
    elif _flag(info, "is_mpim", default=False):
        kind = SlackChannelType.mpdm
    else:
        kind = SlackChannelType.private if _flag(info, "is_private") else SlackChannelType.public
    members = [_text(member) for member in _pages(member_pages, "members", slack=True)]
    workspace_members = None
    if workspace_pages is not None:
        workspace_members = []
        for user in _pages(workspace_pages, "members", slack=True):
            if not isinstance(user, Mapping):
                raise ValueError("Invalid Slack user")
            if (
                _text(user.get("team_id")) == workspace_id
                and not _flag(user, "deleted")
                and not _flag(user, "is_bot")
                and not _flag(user, "is_app_user", default=False)
                and not _flag(user, "is_restricted")
                and not _flag(user, "is_ultra_restricted")
            ):
                workspace_members.append(_text(user.get("id")))
    return SlackPermissions(
        workspace_id=workspace_id,
        channel_id=_text(info.get("id")),
        channel_type=kind,
        member_ids=list(dict.fromkeys(members)),
        workspace_member_ids=workspace_members,
    )


def gdrive_permissions_from_api(
    *,
    file: Mapping[str, Any],
    permission_pages: Sequence[Mapping[str, Any]],
) -> GDrivePermissions:
    """Capture files.get metadata and complete permissions.list pages for the effective file ACL.

    Request type, role, emailAddress, domain, permissionDetails, deleted, expirationTime and
    allowFileDiscovery. Missing discovery flags on domain/anyone shares never allow search.
    Parent ACLs must not be blindly unioned into a child's effective permissions.
    """
    acl: list[GDriveAce] = []
    for permission in _pages(permission_pages, "permissions", slack=False):
        if not isinstance(permission, Mapping):
            raise ValueError("Invalid Drive permission")
        kind = permission.get("type")
        details = permission.get("permissionDetails", [])
        if not isinstance(details, list) or any(not isinstance(d, Mapping) for d in details):
            raise ValueError("Invalid Drive permissionDetails")
        acl.append(
            GDriveAce(
                type=kind,
                role=permission.get("role"),
                email_or_domain=permission.get("domain" if kind == "domain" else "emailAddress"),
                inherited=any(_flag(d, "inherited") for d in details),
                deleted=_flag(permission, "deleted", default=False),
                expiration_time=permission.get("expirationTime"),
                allow_file_discovery=_flag(permission, "allowFileDiscovery", default=False),
            )
        )
    parents = file.get("parents", [])
    if not isinstance(parents, list):
        raise ValueError("Invalid Drive parents")
    return GDrivePermissions(
        file_id=_text(file.get("id")), parent_ids=[_text(p) for p in parents], acl=acl
    )


# ----------------------------------------------------------------------------- Confluence


def _confluence_restriction(response: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Users and groups of one ``restriction/byOperation/read`` response, complete or refused.

    Both lists must be whole: ``start`` 0, ``size`` equal to the rows returned, and
    ``totalSize`` (when present) equal to ``size``. Groups are identified by their id.
    """
    if not isinstance(response, Mapping) or response.get("operation") != "read":
        raise ValueError("Expected a Confluence read restriction")
    blocks = response.get("restrictions")
    if not isinstance(blocks, Mapping):
        raise ValueError("Missing Confluence restrictions")
    out: dict[str, list[str]] = {}
    for key, ident in (("user", "accountId"), ("group", "id")):
        block = blocks.get(key)  # a missing block is unknown, not "unrestricted"
        rows = block.get("results") if isinstance(block, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError(f"Missing Confluence {key} restrictions")
        size, total = block.get("size", len(rows)), block.get("totalSize", block.get("size"))
        if block.get("start", 0) != 0 or size != len(rows) or total not in (None, len(rows)):
            raise ValueError(f"Incomplete Confluence {key} restrictions")
        out[key] = [
            _text(row.get(ident)) if isinstance(row, Mapping) else _text(None) for row in rows
        ]
    return list(dict.fromkeys(out["user"])), list(dict.fromkeys(out["group"]))


def confluence_permissions_from_api(
    *,
    space_key: str,
    page_id: str,
    space_permission_pages: Sequence[Mapping[str, Any]],
    page_restriction: Mapping[str, Any],
    ancestor_restrictions: Sequence[tuple[str, Mapping[str, Any]]] = (),
) -> ConfluencePermissions:
    """Capture a page's space read audience, its own read restriction and every ancestor's.

    ``space_permission_pages`` are all pages of ``GET /wiki/api/v2/spaces/{id}/permissions``
    (``_links.next`` on every page but the last). Only ``read``/``space`` entries count; a
    ``role`` principal (anonymous or access-class access) cannot be enumerated and is refused.
    ``page_restriction`` and each ``(ancestor_page_id, response)`` are
    ``GET /wiki/rest/api/content/{id}/restriction/byOperation/read`` responses, ancestors root
    first. A missing ancestor would fail open, so the caller must pass every one.
    """
    if not space_permission_pages:
        raise ValueError("At least one complete provider page is required")
    users: list[str] = []
    groups: list[str] = []
    for index, page in enumerate(space_permission_pages):
        rows = page.get("results") if isinstance(page, Mapping) else None
        links = page.get("_links", {}) if isinstance(page, Mapping) else None
        if not isinstance(rows, list) or not isinstance(links, Mapping):
            raise ValueError("Invalid Confluence space permissions page")
        if bool(links.get("next")) != (index < len(space_permission_pages) - 1):
            raise ValueError("Incomplete or inconsistent provider pagination")
        for row in rows:
            operation = row.get("operation") if isinstance(row, Mapping) else None
            principal = row.get("principal") if isinstance(row, Mapping) else None
            if not isinstance(operation, Mapping) or not isinstance(principal, Mapping):
                raise ValueError("Invalid Confluence space permission")
            if operation.get("key") != "read" or operation.get("targetType") != "space":
                continue
            match principal.get("type"):
                case "user":
                    users.append(_text(principal.get("id")))
                case "group":
                    groups.append(_text(principal.get("id")))
                case other:
                    raise ValueError(f"Unsupported Confluence space principal: {other!r}")
    page_users, page_groups = _confluence_restriction(page_restriction)
    ancestors = []
    for ancestor_id, response in ancestor_restrictions:
        view_users, view_groups = _confluence_restriction(response)
        ancestors.append(
            ConfluenceAncestor(
                page_id=_text(ancestor_id), view_users=view_users, view_groups=view_groups
            )
        )
    return ConfluencePermissions(
        space_key=_text(space_key),
        page_id=_text(page_id),
        space_view_users=list(dict.fromkeys(users)),
        space_view_groups=list(dict.fromkeys(groups)),
        page_view_users=page_users,
        page_view_groups=page_groups,
        ancestors=ancestors,
    )


# ----------------------------------------------------------------------------------- Jira

BROWSE_PROJECTS = "BROWSE_PROJECTS"


def _jira_group(holder: Mapping[str, Any]) -> str:
    group = holder.get("group")
    if isinstance(group, Mapping) and group.get("groupId"):
        return _text(group["groupId"])
    return _text(holder.get("value") or holder.get("parameter"))


def _jira_role_members(role: Mapping[str, Any]) -> list[str]:
    members: list[str] = []
    actors = role.get("actors")
    if not isinstance(actors, list):
        raise ValueError("Missing Jira role actors")
    for actor in actors:
        if not isinstance(actor, Mapping):
            raise ValueError("Invalid Jira role actor")
        match actor.get("type"):
            case "atlassian-user-role-actor":
                members.append(_text((actor.get("actorUser") or {}).get("accountId")))
            case "atlassian-group-role-actor":
                group = actor.get("actorGroup") or {}
                members.append(_text(group.get("groupId") or group.get("name")))
            case other:
                raise ValueError(f"Unsupported Jira role actor: {other!r}")
    return list(dict.fromkeys(members))


def jira_permissions_from_api(
    *,
    issue: Mapping[str, Any],
    project_roles: Sequence[Mapping[str, Any]],
    permission_scheme: Mapping[str, Any],
    security_member_pages: Sequence[Mapping[str, Any]] = (),
) -> JiraPermissions:
    """Capture who may browse an issue: Browse Projects holders plus its issue security level.

    ``issue`` is ``GET /rest/api/3/issue/{key}?fields=project,security``; ``project_roles``
    every ``GET /rest/api/3/project/{key}/role/{id}`` response; ``permission_scheme`` is
    ``GET /rest/api/3/project/{key}/permissionscheme?expand=permissions``; and, when the issue
    has a security level, ``security_member_pages`` are all pages of
    ``GET /rest/api/3/issuesecurityschemes/level/member?levelId=…``. Project roles, users and
    groups are captured. Holders that depend on the issue or a licence (reporter, assignee,
    project lead, custom fields, application roles, anyone) cannot be enumerated here and are
    refused, so such issues need a live, user-bound check instead.
    """
    fields = issue.get("fields")
    if not isinstance(fields, Mapping) or not isinstance(fields.get("project"), Mapping):
        raise ValueError("Invalid Jira issue response")
    roles = {}
    role_names: dict[str, str] = {}
    for role in project_roles:
        if not isinstance(role, Mapping):
            raise ValueError("Invalid Jira project role")
        name = _text(role.get("name"))
        role_names[str(role.get("id"))] = name
        roles[name] = _jira_role_members(role)

    browse: list[str] = []
    grants = permission_scheme.get("permissions")
    if not isinstance(grants, list):
        raise ValueError("Missing Jira permission scheme grants")
    for grant in grants:
        if not isinstance(grant, Mapping) or not isinstance(grant.get("holder"), Mapping):
            raise ValueError("Invalid Jira permission grant")
        if grant.get("permission") != BROWSE_PROJECTS:
            continue
        holder = grant["holder"]
        match holder.get("type"):
            case "projectRole":
                role_id = str(holder.get("value") or holder.get("parameter"))
                if role_id not in role_names:
                    raise ValueError(f"Jira project role {role_id} was not captured")
                browse.append(role_names[role_id])
            case "group":
                group_id = _jira_group(holder)
                roles.setdefault(f"group:{group_id}", [group_id])
                browse.append(f"group:{group_id}")
            case "user":
                account = _text((holder.get("user") or {}).get("accountId") or holder.get("value"))
                roles.setdefault(f"user:{account}", [account])
                browse.append(f"user:{account}")
            case other:
                raise ValueError(f"Unsupported Jira Browse Projects holder: {other!r}")

    security = fields.get("security")
    level: str | None = None
    members: list[str] = []
    if security is not None:
        if not isinstance(security, Mapping):
            raise ValueError("Invalid Jira issue security level")
        level = _text(str(security.get("id") or ""))
        if not security_member_pages:
            raise ValueError("Issue security members are required for a secured issue")
        for index, page in enumerate(security_member_pages):
            values = page.get("values") if isinstance(page, Mapping) else None
            if not isinstance(values, list):
                raise ValueError("Invalid Jira security member page")
            if page.get("isLast") is not (index == len(security_member_pages) - 1):
                raise ValueError("Incomplete or inconsistent provider pagination")
            for value in values:
                holder = value.get("holder") if isinstance(value, Mapping) else None
                if not isinstance(holder, Mapping):
                    raise ValueError("Invalid Jira security member")
                if str(value.get("issueSecurityLevelId", level)) != level:
                    raise ValueError("Jira security member belongs to another level")
                match holder.get("type"):
                    case "user":
                        members.append(
                            _text(
                                (holder.get("user") or {}).get("accountId") or holder.get("value")
                            )
                        )
                    case "group":
                        members.append(_jira_group(holder))
                    case "projectRole":
                        role_id = str(holder.get("value") or holder.get("parameter"))
                        if role_id not in role_names:
                            raise ValueError(f"Jira project role {role_id} was not captured")
                        members.extend(roles[role_names[role_id]])
                    case other:
                        raise ValueError(f"Unsupported Jira security level holder: {other!r}")

    return JiraPermissions(
        project_key=_text(fields["project"].get("key")),
        issue_key=_text(issue.get("key")),
        project_roles=roles,
        browse_roles=list(dict.fromkeys(browse)),
        issue_security_level=level,
        security_level_members=list(dict.fromkeys(members)),
    )


# ---------------------------------------------------------------------------------- Email


def email_permissions_from_gmail(message: Mapping[str, Any]) -> EmailPermissions:
    """Capture a Gmail ``users.messages.get`` (``format=metadata``) response: its sender and
    every To/Cc/Bcc recipient. Request the From, To, Cc, Bcc and Message-ID headers. Exactly one
    sender is required; a message without one is refused rather than readable by nobody."""
    payload = message.get("payload")
    headers = payload.get("headers") if isinstance(payload, Mapping) else None
    if not isinstance(headers, list):
        raise ValueError("Invalid Gmail message metadata")
    values: dict[str, list[str]] = {}
    for header in headers:
        if not isinstance(header, Mapping) or not isinstance(header.get("value"), str):
            raise ValueError("Invalid Gmail header")
        values.setdefault(_text(header.get("name")).lower(), []).append(header["value"])

    def addresses(name: str) -> list[str]:
        found = [address for _, address in getaddresses(values.get(name, [])) if address]
        return list(dict.fromkeys(found))

    senders = addresses("from")
    if len(senders) != 1:
        raise ValueError("A Gmail message needs exactly one From address")
    message_ids = values.get("message-id", [])
    return EmailPermissions(
        message_id=_text(message_ids[0] if message_ids else message.get("id")),
        from_=senders[0],
        to=addresses("to"),
        cc=addresses("cc"),
        bcc=addresses("bcc"),
    )


def permission_fingerprint(raw: RawPermissions | dict[str, Any]) -> str:
    """Stable ACL revision, independent of capture time/run id. Never an access decision cache."""
    payload = parse_raw_permissions(raw).model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
