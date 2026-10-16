"""Raw, per-platform permission snapshots — preserved verbatim, never flattened.

Each source platform authorises reads differently (Confluence space + page restrictions, Jira
project roles + issue security levels, Slack channel membership, Google Drive ACLs, e-mail
recipients, upload sharing, external MCP app allow-lists). This module keeps each model in its
native shape so the policy can evaluate the platform's own semantics at query time, and so an
auditor can see exactly what the connector captured.

``RawPermissions`` is a Pydantic discriminated union on ``kind``. It parses the ``permissions:``
block of a seed/gbrain page frontmatter as-is, e.g.::

    {kind: confluence, space_key: OPS, page_id: "1042", space_view_users: [],
     space_view_groups: [finance-ops, engineering], page_view_users: [], page_view_groups: [],
     ancestors: []}

Unknown keys are rejected (``extra="forbid"``): a misspelt restriction field must fail loudly at
ingest rather than be silently dropped, because a dropped *restriction* would fail open.
Numeric identifiers (``page_id: 1042`` unquoted in YAML) are coerced to strings.

``SourceKind`` lives here (not in ``models``) so this module has no intra-package imports;
``access_control.models`` re-exports it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


class SourceKind(StrEnum):
    """Where a document came from. ``gdrive`` (not ``google_drive``) matches the seed corpus."""

    confluence = "confluence"
    jira = "jira"
    slack = "slack"
    gdrive = "gdrive"
    email = "email"
    upload = "upload"
    gbrain_import = "gbrain_import"
    mcp_external = "mcp_external"


class SlackChannelType(StrEnum):
    public = "public"
    private = "private"
    dm = "dm"
    mpdm = "mpdm"


class GDriveAceType(StrEnum):
    user = "user"
    group = "group"
    domain = "domain"
    anyone = "anyone"


class GDriveRole(StrEnum):
    """Google Drive permission roles. Every role implies read access."""

    owner = "owner"
    organizer = "organizer"
    file_organizer = "fileOrganizer"
    writer = "writer"
    commenter = "commenter"
    reader = "reader"


class _RawModel(BaseModel):
    """Shared config: strict keys, numeric ids coerced to ``str``."""

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)


# --------------------------------------------------------------------------- Confluence


class ConfluenceAncestor(_RawModel):
    """An ancestor page's own view restriction (Confluence restrictions inherit downwards).

    Empty ``view_users`` and ``view_groups`` mean the ancestor carries no view restriction.
    """

    page_id: str
    view_users: list[str] = Field(default_factory=list)
    view_groups: list[str] = Field(default_factory=list)


class ConfluencePermissions(_RawModel):
    """Confluence space permission + page-level view restrictions.

    Semantics (evaluated by the policy): the reader must hold *space* view
    (``space_view_users``/``space_view_groups``); if the page has view restrictions
    (``page_view_users``/``page_view_groups`` non-empty) the reader must *also* satisfy them —
    page restrictions narrow (override) the space audience, they never widen it. Empty page lists
    mean "no page restriction, inherit the space audience". Every ancestor must carry its captured
    restrictions. A legacy bare page id remains parseable but the policy denies incomplete data.
    """

    kind: Literal["confluence"] = "confluence"
    space_key: str
    page_id: str
    space_view_users: list[str] = Field(default_factory=list)
    space_view_groups: list[str] = Field(default_factory=list)
    page_view_users: list[str] = Field(default_factory=list)
    page_view_groups: list[str] = Field(default_factory=list)
    ancestors: list[str | ConfluenceAncestor] = Field(default_factory=list)


# --------------------------------------------------------------------------------- Jira


class JiraPermissions(_RawModel):
    """Jira project roles, the "Browse Projects" permission, and issue-level security.

    ``project_roles`` maps role name → members (user ids or group ids). A reader may browse when
    they hold any role listed in ``browse_roles``. When ``issue_security_level`` is set the reader
    must additionally appear (as user or group) in ``security_level_members``. Empty
    ``browse_roles`` means nobody can browse.
    """

    kind: Literal["jira"] = "jira"
    project_key: str
    issue_key: str
    project_roles: dict[str, list[str]] = Field(default_factory=dict)
    browse_roles: list[str] = Field(default_factory=list)
    issue_security_level: str | None = None
    security_level_members: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------------------- Slack


class SlackPermissions(_RawModel):
    """Slack channel membership.

    All channel types allow explicit ``member_ids``. Public channels additionally allow the
    captured full workspace roster, excluding guests/bots/deactivated users. A missing roster
    never grants access to outsiders. Private channels and direct messages require membership.
    """

    kind: Literal["slack"] = "slack"
    workspace_id: str
    channel_id: str
    channel_type: SlackChannelType
    member_ids: list[str] = Field(default_factory=list)
    workspace_member_ids: list[str] | None = None


# -------------------------------------------------------------------------- Google Drive


class GDriveAce(_RawModel):
    """One Drive permission entry. ``email_or_domain`` is required unless ``type == anyone``."""

    type: GDriveAceType
    role: GDriveRole
    email_or_domain: str | None = None
    inherited: bool = False
    expiration_time: datetime | None = None
    deleted: bool = Field(default=False, strict=True)
    allow_file_discovery: bool = Field(default=True, strict=True)

    @field_validator("expiration_time")
    @classmethod
    def _expiry_has_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Drive expiration_time must include a timezone")
        return value

    @model_validator(mode="after")
    def _target_required(self) -> Self:
        if not self.deleted and self.type != GDriveAceType.anyone and not self.email_or_domain:
            raise ValueError(f"GDrive ACE of type {self.type.value!r} needs email_or_domain")
        return self


class GDrivePermissions(_RawModel):
    """Google Drive file ACL.

    ``acl`` is the *effective* ACL as the Drive API returns it, inherited folder entries included
    (``inherited=True``); ``parent_ids`` is kept for folder-move / permission-drift detection.
    """

    kind: Literal["gdrive"] = "gdrive"
    file_id: str
    parent_ids: list[str] = Field(default_factory=list)
    acl: list[GDriveAce] = Field(default_factory=list)


# -------------------------------------------------------------------------------- Email


class EmailPermissions(_RawModel):
    """E-mail: readable by the sender and every recipient (to/cc/bcc), case-insensitively.

    The sender field is ``from_`` in Python and in serialised output; input may use ``from_`` or
    ``from``.
    """

    kind: Literal["email"] = "email"
    message_id: str
    from_: str = Field(validation_alias=AliasChoices("from_", "from"))
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------------------- Upload


class UploadPermissions(_RawModel):
    """User upload: the owner plus explicitly shared principals and groups."""

    kind: Literal["upload"] = "upload"
    owner_principal_id: str
    shared_with_principals: list[str] = Field(default_factory=list)
    shared_with_groups: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------------- MCP external


class McpExternalPermissions(_RawModel):
    """Content pulled from an external MCP app: explicit principal/group allow-lists."""

    kind: Literal["mcp_external"] = "mcp_external"
    app_name: str
    allowed_principals: list[str] = Field(default_factory=list)
    allowed_groups: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------------------ Union

RawPermissions = Annotated[
    ConfluencePermissions
    | JiraPermissions
    | SlackPermissions
    | GDrivePermissions
    | EmailPermissions
    | UploadPermissions
    | McpExternalPermissions,
    Field(discriminator="kind"),
]

_RAW_ADAPTER: TypeAdapter[RawPermissions] = TypeAdapter(RawPermissions)


def parse_raw_permissions(data: Any) -> RawPermissions:
    """Parse a frontmatter ``permissions:`` mapping (or a raw model) into its typed model.

    Raises ``pydantic.ValidationError`` on an unknown ``kind``, a missing required field, or an
    unexpected key.
    """

    return _RAW_ADAPTER.validate_python(data)


class SourcePermissions(BaseModel):
    """A versioned snapshot of one document's raw platform permissions.

    ``kind`` must equal ``raw.kind``; when omitted from mapping input it is taken from ``raw``.
    ``permission_version`` identifies the snapshot (it is stamped on every decision made with it
    and compared with the document's own ``permission_version`` to detect drift).
    """

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    kind: SourceKind
    raw: RawPermissions
    permission_version: str
    captured_at: datetime
    connector_run_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _kind_defaults_to_raw_kind(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("kind") is None:
            raw = data.get("raw")
            raw_kind = raw.get("kind") if isinstance(raw, dict) else getattr(raw, "kind", None)
            if raw_kind is not None:
                data = {**data, "kind": raw_kind}
        return data

    @model_validator(mode="after")
    def _kind_matches_raw(self) -> Self:
        if self.kind != self.raw.kind:
            raise ValueError(
                f"SourcePermissions.kind {self.kind.value!r} != raw.kind {self.raw.kind!r}"
            )
        return self

    @classmethod
    def from_raw(
        cls,
        raw: RawPermissions | dict[str, Any],
        *,
        permission_version: str,
        captured_at: datetime,
        connector_run_id: str | None = None,
    ) -> SourcePermissions:
        """Build a snapshot from a frontmatter ``permissions:`` block (``kind`` inferred)."""

        return cls.model_validate(
            {
                "raw": raw,
                "permission_version": permission_version,
                "captured_at": captured_at,
                "connector_run_id": connector_run_id,
            }
        )
