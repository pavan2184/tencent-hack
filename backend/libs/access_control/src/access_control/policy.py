"""Pure read policy. Inactive users and explicit denies take precedence, then source access is
a ceiling for imported content. Ownership, admin roles and local grants can only narrow that
audience. Confidential/restricted content additionally needs one of those local approvals.

Uploads are managed locally, so owner/admin/grant rules may allow them without a source ACL.
Existing R1–R10 audit labels are retained; labels identify the rule, not execution order.
Only matching document/read grants count. Revoked allows explain a subsequent denial when no
active matching allow remains, but never override inactivity, explicit denies or errors.

Permission snapshots go stale. A snapshot of an imported document older than the maximum age
for the document's classification (``DEFAULT_MAX_PERMISSION_AGE``) no longer counts as knowledge
of the source's permissions, so the source check denies (``R9:permission_snapshot_stale``) until a
sync refreshes it. This bounds how long a revocation at the source can go unnoticed. Uploads are
exempt: their permissions are managed locally and cannot drift from an external source.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr

from access_control.models import (
    AccessDecision,
    Classification,
    DenyReason,
    DocumentAccessContext,
    Effect,
    FilterResult,
    Grant,
    Principal,
    SubjectType,
)
from access_control.permissions import (
    ConfluenceAncestor,
    ConfluencePermissions,
    EmailPermissions,
    GDriveAceType,
    GDrivePermissions,
    JiraPermissions,
    McpExternalPermissions,
    SlackChannelType,
    SlackPermissions,
    SourceKind,
    UploadPermissions,
)

DEFAULT_POLICY_VERSION = "ac-v2"
ADMIN_ROLE = "admin"
READ_SCOPE = "read"

RULE_INACTIVE = "R1:inactive_principal"
RULE_EXPLICIT_DENY = "R2:explicit_deny"
RULE_OWNER = "R3:owner"
RULE_ADMIN = "R4:admin"
RULE_EXPLICIT_GRANT = "R5:explicit_grant"
RULE_RESTRICTED = "R6:restricted"
RULE_CONFIDENTIAL = "R7:confidential"
RULE_SOURCE_PREFIX = "R8:"
RULE_UNKNOWN_PERMISSIONS = "R9:unknown_permissions"
RULE_PERMISSION_VERSION_MISMATCH = "R9:permission_version_mismatch"
RULE_SOURCE_KIND_MISMATCH = "R9:source_kind_mismatch"
RULE_PERMISSION_SNAPSHOT_STALE = "R9:permission_snapshot_stale"
RULE_DEFAULT_DENY = "R10:default_deny"
RULE_EVALUATION_ERROR = "ERR:evaluation_error"


# How old a permission snapshot may be before it stops counting, by classification. The sync
# must refresh snapshots well within these windows (the app re-reads them on every delta sync).
DEFAULT_MAX_PERMISSION_AGE: Mapping[Classification, timedelta] = {
    Classification.public: timedelta(hours=24),
    Classification.internal: timedelta(hours=1),
    Classification.confidential: timedelta(minutes=5),
    Classification.restricted: timedelta(minutes=5),
}
# A snapshot stamped further in the future than this is not trusted to be fresh.
MAX_CLOCK_SKEW = timedelta(seconds=60)


class DefaultAccessPolicy:
    """Fail-closed source-ceiling policy. Synchronous and deterministic, with no I/O.

    ``max_permission_age`` maps every classification to the oldest permission snapshot the
    policy still trusts; ``None`` disables the age check (tests and offline tools only)."""

    def __init__(
        self,
        policy_version: str = DEFAULT_POLICY_VERSION,
        *,
        max_permission_age: Mapping[Classification, timedelta] | None = DEFAULT_MAX_PERMISSION_AGE,
    ) -> None:
        if max_permission_age is not None:
            missing = set(Classification) - set(max_permission_age)
            if missing:
                raise ValueError(f"max_permission_age lacks {sorted(missing)}")
            if any(age <= timedelta(0) for age in max_permission_age.values()):
                raise ValueError("max_permission_age values must be positive")
            max_permission_age = dict(max_permission_age)
        self.policy_version = policy_version
        self.max_permission_age = max_permission_age

    # ------------------------------------------------------------------ public API

    def decide(
        self, principal: Principal, doc: DocumentAccessContext, *, now: datetime
    ) -> AccessDecision:
        try:
            return self._decide(principal, doc, now)
        except Exception:  # never raise: malformed input fails closed
            return AccessDecision(
                document_id=str(getattr(doc, "document_id", "") or ""),
                decision=Effect.deny,
                reason=DenyReason.unknown_permissions,
                matched_rule=RULE_EVALUATION_ERROR,
                permission_version=None,
                policy_version=self.policy_version,
                evaluated_at=now if isinstance(now, datetime) else datetime.now(UTC),
            )

    def filter(
        self, principal: Principal, docs: Iterable[DocumentAccessContext], *, now: datetime
    ) -> FilterResult:
        decisions = [self.decide(principal, doc, now=now) for doc in docs]
        denied_ids = {d.document_id for d in decisions if not d.allowed}
        seen: set[str] = set()
        allowed_ids: list[str] = []
        for decision in decisions:
            if (
                decision.allowed
                and decision.document_id not in denied_ids
                and decision.document_id not in seen
            ):
                seen.add(decision.document_id)
                allowed_ids.append(decision.document_id)
        return FilterResult(allowed_ids=allowed_ids, decisions=decisions)

    # ------------------------------------------------------------------ rules

    def _decide(
        self, principal: Principal, doc: DocumentAccessContext, now: datetime
    ) -> AccessDecision:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        snapshot = doc.source_permissions
        permission_version = doc.permission_version or (
            snapshot.permission_version if snapshot is not None else None
        )
        expires_at = _expires_at(doc, self.max_permission_age)

        def decision(
            rule: str, reason: DenyReason | None, grant_ids: Iterable[str] = ()
        ) -> AccessDecision:
            return AccessDecision(
                document_id=doc.document_id,
                decision=Effect.allow if reason is None else Effect.deny,
                reason=reason,
                matched_rule=rule,
                permission_version=permission_version,
                permission_captured_at=snapshot.captured_at if snapshot is not None else None,
                permission_expires_at=expires_at,
                grant_ids=list(grant_ids),
                policy_version=self.policy_version,
                evaluated_at=now,
            )

        # R1
        if not principal.is_active:
            return decision(RULE_INACTIVE, DenyReason.policy_default)

        matching = [
            g
            for g in doc.grants
            if g.document_id == doc.document_id
            and g.scope == READ_SCOPE
            and _subject_matches(g, principal)
        ]
        active = [g for g in matching if g.revoked_at is None]
        allow_ids = [g.id for g in active if g.effect == Effect.allow]
        has_allow = bool(allow_ids)

        def denied(rule: str, reason: DenyReason) -> AccessDecision:
            if not has_allow and any(
                g.effect == Effect.allow and g.revoked_at is not None for g in matching
            ):
                reason = DenyReason.grant_revoked
            return decision(rule, reason)

        # R2
        if any(g.effect == Effect.deny for g in active):
            return decision(RULE_EXPLICIT_DENY, DenyReason.explicit_deny)

        source_rule, source_reason = _source_access(principal, doc, now, self.max_permission_age)
        if source_reason is not None and (
            doc.source_kind != SourceKind.upload
            or (snapshot is not None and source_reason != DenyReason.no_source_membership)
        ):
            return denied(source_rule, source_reason)
        # R3
        if doc.owner_principal_id is not None and doc.owner_principal_id == principal.id:
            return decision(RULE_OWNER, None)
        # R4
        if ADMIN_ROLE in principal.roles:
            return decision(RULE_ADMIN, None)
        # R5
        if has_allow:
            return decision(RULE_EXPLICIT_GRANT, None, allow_ids)

        if doc.classification == Classification.restricted:
            return denied(RULE_RESTRICTED, DenyReason.classification_requires_grant)
        if doc.classification == Classification.confidential:
            return denied(RULE_CONFIDENTIAL, DenyReason.classification_requires_grant)
        if source_reason is not None:
            return denied(source_rule, source_reason)
        return decision(source_rule, None)


def _subject_matches(grant: Grant, principal: Principal) -> bool:
    match grant.subject_type:
        case SubjectType.principal:
            return grant.subject_id == principal.id
        case SubjectType.group:
            return grant.subject_id in principal.groups
        case SubjectType.role:
            return grant.subject_id in principal.roles
    return False


def _source_access(
    principal: Principal,
    doc: DocumentAccessContext,
    now: datetime,
    max_age: Mapping[Classification, timedelta] | None = None,
) -> tuple[str, DenyReason | None]:
    snapshot = doc.source_permissions
    if snapshot is None:
        return RULE_UNKNOWN_PERMISSIONS, DenyReason.unknown_permissions
    if doc.permission_version is not None and doc.permission_version != snapshot.permission_version:
        return RULE_PERMISSION_VERSION_MISMATCH, DenyReason.unknown_permissions
    if doc.source_kind != SourceKind.gbrain_import and snapshot.kind != doc.source_kind:
        return RULE_SOURCE_KIND_MISMATCH, DenyReason.unknown_permissions
    if not snapshot.permission_version:
        return RULE_UNKNOWN_PERMISSIONS, DenyReason.unknown_permissions
    if max_age is not None and _is_stale(doc, snapshot.captured_at, now, max_age):
        return RULE_PERMISSION_SNAPSHOT_STALE, DenyReason.unknown_permissions
    if isinstance(snapshot.raw, ConfluencePermissions) and any(
        not isinstance(ancestor, ConfluenceAncestor) for ancestor in snapshot.raw.ancestors
    ):
        return RULE_UNKNOWN_PERMISSIONS, DenyReason.unknown_permissions

    member = has_source_membership(principal, snapshot.raw, now=now)
    if member is None:
        return RULE_DEFAULT_DENY, DenyReason.policy_default
    rule = f"{RULE_SOURCE_PREFIX}{snapshot.raw.kind}"
    return (rule, None) if member else (rule, DenyReason.no_source_membership)


def _expires_at(
    doc: DocumentAccessContext, max_age: Mapping[Classification, timedelta] | None
) -> datetime | None:
    """When the document's snapshot stops counting, or None if it never ages out."""
    snapshot = doc.source_permissions
    if max_age is None or snapshot is None or doc.source_kind == SourceKind.upload:
        return None
    captured_at = snapshot.captured_at
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        return None
    return captured_at + max_age[doc.classification]


def _is_stale(
    doc: DocumentAccessContext,
    captured_at: datetime,
    now: datetime,
    max_age: Mapping[Classification, timedelta],
) -> bool:
    """True when an imported document's snapshot is too old (or implausibly new) to trust."""
    if doc.source_kind == SourceKind.upload:
        return False
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        return True
    age = now - captured_at
    return age > max_age[doc.classification] or age < -MAX_CLOCK_SKEW


# ---------------------------------------------------------------------- R8 per platform


def platform_identities(principal: Principal, kind: str) -> set[str]:
    """The ids a principal is known by on platform ``kind``.

    A bound platform identity takes precedence. The local id/email fallback is for synthetic
    identities without a binding, and must not widen an explicitly bound account's access.
    """

    external = principal.external_identities.get(kind)
    ids = {external} if external else {principal.id}
    if not external and kind in (SourceKind.gdrive, SourceKind.email) and principal.email:
        ids.add(principal.email)
    return ids


def platform_groups(principal: Principal, kind: str) -> set[str]:
    """The group ids a principal holds on platform ``kind``.

    Resolved platform group ids (``access_control.groups.resolve_groups``) take precedence; a
    principal without them for ``kind`` is matched by its local group ids (synthetic seeds).
    """

    bound = principal.platform_groups.get(kind)
    return set(bound if bound is not None else principal.groups)


def has_source_membership(
    principal: Principal, raw: object, *, now: datetime | None = None
) -> bool | None:
    """Evaluate the platform's own read semantics. ``None`` = unsupported raw kind (→ R10)."""

    match raw:
        case ConfluencePermissions():
            return _confluence(principal, raw)
        case JiraPermissions():
            return _jira(principal, raw)
        case SlackPermissions():
            return _slack(principal, raw)
        case GDrivePermissions():
            return _gdrive(principal, raw, now or datetime.now(UTC))
        case EmailPermissions():
            return _email(principal, raw)
        case UploadPermissions():
            return _upload(principal, raw)
        case McpExternalPermissions():
            return _mcp_external(principal, raw)
    return None


def _in(ids: set[str], groups: set[str], users: Iterable[str], group_ids: Iterable[str]) -> bool:
    return not ids.isdisjoint(users) or not groups.isdisjoint(group_ids)


def _confluence(principal: Principal, raw: ConfluencePermissions) -> bool:
    ids = platform_identities(principal, SourceKind.confluence)
    groups = platform_groups(principal, SourceKind.confluence)
    if not _in(ids, groups, raw.space_view_users, raw.space_view_groups):
        return False
    if (raw.page_view_users or raw.page_view_groups) and not _in(
        ids, groups, raw.page_view_users, raw.page_view_groups
    ):
        return False
    for ancestor in raw.ancestors:
        if not isinstance(ancestor, ConfluenceAncestor):
            return False
        if (ancestor.view_users or ancestor.view_groups) and not _in(
            ids, groups, ancestor.view_users, ancestor.view_groups
        ):
            return False
    return True


def _jira(principal: Principal, raw: JiraPermissions) -> bool:
    ids = platform_identities(principal, SourceKind.jira)
    groups = platform_groups(principal, SourceKind.jira)
    held_roles = {
        role for role, members in raw.project_roles.items() if _in(ids, groups, members, members)
    }
    if held_roles.isdisjoint(raw.browse_roles):
        return False
    if raw.issue_security_level is not None:
        members = raw.security_level_members
        return _in(ids, groups, members, members)
    return True


def _slack(principal: Principal, raw: SlackPermissions) -> bool:
    ids = platform_identities(principal, SourceKind.slack)
    if not ids.isdisjoint(raw.member_ids):
        return True
    if raw.channel_type == SlackChannelType.public:
        return raw.workspace_member_ids is not None and not ids.isdisjoint(raw.workspace_member_ids)
    return False


def _norm_address(value: str) -> str:
    address = parseaddr(value)[1] or value
    return address.strip().lower()


def _gdrive(principal: Principal, raw: GDrivePermissions, now: datetime) -> bool:
    ids = {_norm_address(i) for i in platform_identities(principal, SourceKind.gdrive)}
    domains = {i.rsplit("@", 1)[1] for i in ids if "@" in i}
    groups = {g.lower() for g in platform_groups(principal, SourceKind.gdrive)}
    for ace in raw.acl:
        if ace.deleted or (ace.expiration_time is not None and now >= ace.expiration_time):
            continue
        if (
            ace.type in (GDriveAceType.domain, GDriveAceType.anyone)
            and not ace.allow_file_discovery
        ):
            continue
        target = (ace.email_or_domain or "").strip().lower()
        match ace.type:
            case GDriveAceType.anyone:
                return True
            case GDriveAceType.domain if target in domains:
                return True
            case GDriveAceType.user if target in ids:
                return True
            case GDriveAceType.group if target in groups:
                return True
    return False


def _email(principal: Principal, raw: EmailPermissions) -> bool:
    ids = {_norm_address(i) for i in platform_identities(principal, SourceKind.email)}
    parties = {_norm_address(a) for a in (raw.from_, *raw.to, *raw.cc, *raw.bcc)}
    return not ids.isdisjoint(parties)


def _upload(principal: Principal, raw: UploadPermissions) -> bool:
    ids = platform_identities(principal, SourceKind.upload)
    if raw.owner_principal_id in ids:
        return True
    return _in(ids, set(principal.groups), raw.shared_with_principals, raw.shared_with_groups)


def _mcp_external(principal: Principal, raw: McpExternalPermissions) -> bool:
    ids = platform_identities(principal, SourceKind.mcp_external)
    return _in(ids, set(principal.groups), raw.allowed_principals, raw.allowed_groups)
