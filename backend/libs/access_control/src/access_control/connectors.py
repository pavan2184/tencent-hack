"""Normalise captured provider responses without fetching data or storing credentials.

Only complete pages are accepted. Connectors must request all ACL fields, use trusted API
responses, and independently refresh identity/group membership. Document text is never authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from access_control.permissions import (
    GDriveAce,
    GDrivePermissions,
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


def permission_fingerprint(raw: RawPermissions | dict[str, Any]) -> str:
    """Stable ACL revision, independent of capture time/run id. Never an access decision cache."""
    payload = parse_raw_permissions(raw).model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
