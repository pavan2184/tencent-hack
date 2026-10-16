"""Core access-control models: principals, grants, requests, per-document context, decisions.

Vocabulary is fixed by the foundation plan for persistence and audit records, so renaming any
member is a breaking change. Production adapters are supplied by the integrating app.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from access_control.permissions import SourceKind, SourcePermissions

__all__ = [
    "AccessDecision",
    "AccessRequest",
    "AccessRequestStatus",
    "AccessSummary",
    "Classification",
    "DenyReason",
    "DocumentAccessContext",
    "Effect",
    "FilterResult",
    "Grant",
    "Principal",
    "SourceKind",
    "SubjectType",
]


def _new_id() -> str:
    return str(uuid4())


class Classification(StrEnum):
    """Sensitivity ladder, lowest to highest. Classification can only tighten access:
    ``public``/``internal`` still require source membership; ``confidential``/``restricted``
    additionally require ownership or an explicit grant (admins excepted)."""

    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"


class Effect(StrEnum):
    allow = "allow"
    deny = "deny"


class SubjectType(StrEnum):
    principal = "principal"
    group = "group"
    role = "role"


class DenyReason(StrEnum):
    """Why a read was denied. Internal (audit) vocabulary only — never shown to the asker, who
    always gets the same response as for a nonexistent document. ``not_found`` is for the app
    (document does not exist); the policy itself never emits it."""

    not_found = "not_found"
    explicit_deny = "explicit_deny"
    no_source_membership = "no_source_membership"
    classification_requires_grant = "classification_requires_grant"
    grant_revoked = "grant_revoked"
    unknown_permissions = "unknown_permissions"
    policy_default = "policy_default"


class AccessRequestStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    denied = "denied"


class Principal(BaseModel):
    """A resolved identity at query time.

    ``external_identities`` maps a ``SourceKind`` value (e.g. ``"slack"``) to the principal's id
    on that platform (e.g. ``"U_JORDAN"``). A binding replaces the local identity. Only when
    absent does the policy fall back to ``id`` (and, for ``gdrive``/``email``, also ``email``).

    ``platform_groups`` maps a ``SourceKind`` value to the principal's group ids on that platform,
    filled by ``access_control.groups.resolve_groups``. When a platform has an entry it replaces
    ``groups`` for that platform's group ACL entries; otherwise ``groups`` is matched directly.
    """

    id: str
    display_name: str
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    external_identities: dict[str, str] = Field(default_factory=dict)
    platform_groups: dict[str, list[str]] = Field(default_factory=dict)
    is_active: bool = True


class Grant(BaseModel):
    """A per-document allow/deny for a principal, group or role. Revocation is a soft delete
    (``revoked_at``/``revoked_by`` set) so the audit trail and ``grant_revoked`` survive."""

    id: str = Field(default_factory=_new_id)
    document_id: str
    subject_type: SubjectType
    subject_id: str
    effect: Effect
    scope: str = "read"
    granted_by: str
    granted_at: datetime
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    reason: str | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class AccessRequest(BaseModel):
    """A principal asking for read access to a document. Creating one never reveals whether the
    document exists or what it contains (the app answers 202 either way)."""

    id: str = Field(default_factory=_new_id)
    document_id: str
    principal_id: str
    reason: str | None = None
    status: AccessRequestStatus = AccessRequestStatus.pending
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class DocumentAccessContext(BaseModel):
    """Everything the policy needs about one candidate document, assembled by the app.

    ``grants`` are the document's grants *including revoked ones* (needed for
    ``grant_revoked``). ``permission_version`` is the page's current permission version; when it
    is set and differs from ``source_permissions.permission_version`` the snapshot is treated as
    stale (deny ``unknown_permissions``). ``source_kind`` is the document's source; the raw
    platform semantics are taken from ``source_permissions.raw.kind`` (a ``gbrain_import`` page
    can carry Confluence permissions).
    """

    document_id: str
    source_id: str
    source_kind: SourceKind
    classification: Classification = Classification.internal
    owner_principal_id: str | None = None
    source_permissions: SourcePermissions | None = None
    grants: list[Grant] = Field(default_factory=list)
    permission_version: str | None = None


class AccessDecision(BaseModel):
    """One allow/deny for one (principal, document) pair. Audit-only: never serialise denied
    decisions into a response.

    Invariant: ``decision == allow`` ⇔ ``reason is None``.
    """

    document_id: str
    decision: Effect
    reason: DenyReason | None = None
    matched_rule: str
    permission_version: str | None = None
    # When the permission snapshot behind this decision was captured, so an auditor can see how
    # current the system's knowledge of the source's permissions was. None when no snapshot.
    permission_captured_at: datetime | None = None
    # When that snapshot stops counting (captured_at + the classification's maximum age). None for
    # uploads, documents without a snapshot, or a policy with the age check turned off.
    permission_expires_at: datetime | None = None
    # The active allow grants that satisfied ``R5:explicit_grant``; empty for every other rule.
    grant_ids: list[str] = Field(default_factory=list)
    policy_version: str
    evaluated_at: datetime

    @model_validator(mode="after")
    def _reason_iff_deny(self) -> Self:
        if self.decision == Effect.allow and self.reason is not None:
            raise ValueError("an allow decision must not carry a deny reason")
        if self.decision == Effect.deny and self.reason is None:
            raise ValueError("a deny decision must carry a reason")
        return self

    @property
    def allowed(self) -> bool:
        return self.decision == Effect.allow


class FilterResult(BaseModel):
    """Output of ``AccessPolicy.filter``.

    ``decisions`` has exactly one entry per input document, in input order. ``allowed_ids`` is
    the allowed subset in input order, de-duplicated. Any denial of a duplicate id removes it.
    """

    allowed_ids: list[str]
    decisions: list[AccessDecision]


class AccessSummary(BaseModel):
    """What a response may say about access control. Deliberately carries **no** denied count or
    denied ids: the number of hidden documents is itself an existence leak."""

    model_config = ConfigDict(extra="forbid")

    principal_id: str
    policy_version: str
    allowed_count: int
    evaluated_at: datetime

    @classmethod
    def from_filter_result(
        cls,
        result: FilterResult,
        *,
        principal_id: str,
        policy_version: str,
        evaluated_at: datetime,
    ) -> AccessSummary:
        return cls(
            principal_id=principal_id,
            policy_version=policy_version,
            allowed_count=len(result.allowed_ids),
            evaluated_at=evaluated_at,
        )
