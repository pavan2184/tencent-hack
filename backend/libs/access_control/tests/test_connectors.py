"""Provider field preservation, complete pagination and safe discovery semantics."""

from datetime import timedelta

import pytest
from access_control import (
    GDriveAce,
    gdrive_permissions_from_api,
    permission_fingerprint,
    slack_permissions_from_api,
)


def user(uid, **flags):
    return {
        "id": uid,
        "team_id": "T_HARBOR",
        "deleted": False,
        "is_bot": False,
        "is_restricted": False,
        "is_ultra_restricted": False,
        **flags,
    }


def slack_snapshot(*, members=(), users=None, private=False):
    return slack_permissions_from_api(
        workspace_id="T_HARBOR",
        channel={"ok": True, "channel": {"id": "C_GENERAL", "is_private": private}},
        member_pages=[{"ok": True, "members": list(members)}],
        workspace_pages=None if users is None else [{"ok": True, "members": users}],
    )


def test_public_slack_roster_excludes_guests_bots_deleted_and_other_workspaces(
    policy, people, make_doc, now
):
    users = [
        user("U_ALEX"),
        user("U_JOHN", is_restricted=True),
        user("U_JORDAN", is_ultra_restricted=True),
        user("U_SAM", deleted=True),
        user("U_BOT", is_bot=True),
        user("U_APP", is_app_user=True),
        user("U_EXTERNAL", team_id="T_OTHER"),
    ]
    raw = slack_snapshot(users=users)
    assert raw.workspace_member_ids == ["U_ALEX"]
    doc = make_doc(raw.model_dump())
    assert policy.decide(people["alex"], doc, now=now).allowed
    assert not policy.decide(people["john"], doc, now=now).allowed
    member_guest = slack_snapshot(members=["U_JOHN"], users=users)
    assert policy.decide(people["john"], make_doc(member_guest.model_dump()), now=now).allowed


@pytest.mark.parametrize("flag", ["deleted", "is_restricted", "is_ultra_restricted", "is_bot"])
def test_ambiguous_workspace_user_flags_are_rejected(flag):
    row = user("U_ALEX")
    del row[flag]
    with pytest.raises(ValueError):
        slack_snapshot(users=[row])


def test_complete_slack_pages_are_combined_without_duplicates():
    raw = slack_permissions_from_api(
        workspace_id="T_HARBOR",
        channel={"ok": True, "channel": {"id": "C_TREASURY", "is_private": True}},
        member_pages=[
            {"ok": True, "members": ["U_JOHN"], "response_metadata": {"next_cursor": "c2"}},
            {"ok": True, "members": ["U_JORDAN", "U_JOHN"]},
        ],
    )
    assert raw.member_ids == ["U_JOHN", "U_JORDAN"]
    assert raw.channel_type == "private"


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [{"ok": False, "members": []}],
        [{"ok": True, "members": [], "response_metadata": {"next_cursor": "more"}}],
        [{"ok": True, "members": []}, {"ok": True, "members": []}],
        [{"ok": True, "members": [123]}],
    ],
)
def test_incomplete_or_malformed_slack_pages_are_rejected(pages):
    with pytest.raises(ValueError):
        slack_permissions_from_api(
            workspace_id="T_HARBOR",
            channel={"ok": True, "channel": {"id": "C_1", "is_private": False}},
            member_pages=pages,
        )


def test_drive_wire_fields_survive_and_expiry_is_checked_at_read_time(
    policy, people, make_doc, now
):
    raw = gdrive_permissions_from_api(
        file={"id": "f1", "parents": ["folder"]},
        permission_pages=[
            {
                "permissions": [
                    {
                        "type": "user",
                        "role": "reader",
                        "emailAddress": people["alex"].email,
                        "expirationTime": (now + timedelta(seconds=1)).isoformat(),
                        "permissionDetails": [{"inherited": True}],
                        "deleted": False,
                    }
                ]
            }
        ],
    )
    assert raw.acl[0].inherited and raw.parent_ids == ["folder"]
    doc = make_doc(raw.model_dump())
    assert policy.decide(people["alex"], doc, now=now).allowed
    assert not policy.decide(people["alex"], doc, now=now + timedelta(seconds=1)).allowed


@pytest.mark.parametrize("discoverable", [None, False, True])
def test_drive_link_sharing_does_not_automatically_grant_search(
    policy, people, make_doc, now, discoverable
):
    ace = {"type": "anyone", "role": "reader"}
    if discoverable is not None:
        ace["allowFileDiscovery"] = discoverable
    raw = gdrive_permissions_from_api(file={"id": "f1"}, permission_pages=[{"permissions": [ace]}])
    assert policy.decide(people["mei"], make_doc(raw.model_dump()), now=now).allowed is (
        discoverable is True
    )


def test_drive_deleted_identity_with_missing_address_never_grants(policy, people, make_doc, now):
    raw = gdrive_permissions_from_api(
        file={"id": "f1"},
        permission_pages=[{"permissions": [{"type": "user", "role": "reader", "deleted": True}]}],
    )
    assert not policy.decide(people["alex"], make_doc(raw.model_dump()), now=now).allowed


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [{"permissions": [], "nextPageToken": "more"}],
        [{"permissions": []}, {"permissions": []}],
        [{"permissions": [{"type": "user", "role": "owner"}]}],
        [{"permissions": [{"type": "anyone", "role": "reader", "allowFileDiscovery": "false"}]}],
    ],
)
def test_incomplete_or_malformed_drive_pages_are_rejected(pages):
    with pytest.raises(ValueError):
        gdrive_permissions_from_api(file={"id": "f1"}, permission_pages=pages)


def test_drive_complete_pages_and_parent_move_change_revision():
    pages = [
        {
            "permissions": [{"type": "anyone", "role": "reader", "allowFileDiscovery": True}],
            "nextPageToken": "p2",
        },
        {"permissions": []},
    ]
    raw = gdrive_permissions_from_api(file={"id": "f1", "parents": ["old"]}, permission_pages=pages)
    assert permission_fingerprint(raw) == permission_fingerprint(raw.model_dump())
    moved = raw.model_copy(update={"parent_ids": ["new"]})
    assert permission_fingerprint(raw) != permission_fingerprint(moved)
    assert permission_fingerprint(raw).startswith("sha256:")


def test_legacy_drive_seed_parses_with_safe_explicit_defaults():
    ace = GDriveAce(type="user", role="reader", email_or_domain="alex@example.com")
    assert ace.expiration_time is None and not ace.deleted and ace.allow_file_discovery


def test_drive_expiry_must_have_timezone(now):
    with pytest.raises(ValueError):
        GDriveAce(type="anyone", role="reader", expiration_time=now.replace(tzinfo=None))


def test_invalid_page_containers_are_rejected():
    with pytest.raises(ValueError):
        gdrive_permissions_from_api(file={"id": "f1"}, permission_pages=[None])
    with pytest.raises(ValueError):
        slack_permissions_from_api(
            workspace_id="T_HARBOR",
            channel={"ok": True, "channel": {"id": "C_1", "is_private": False}},
            member_pages=[{"ok": True, "members": [], "response_metadata": None}],
        )
