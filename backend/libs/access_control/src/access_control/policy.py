"""``DefaultAccessPolicy`` — ordered, first-match rules over principal, grants, classification and
the document's raw platform permissions.

Rule order (first match wins; every decision stamps ``matched_rule``):

=====  =============================================  ======  ===============================
Rule   Condition                                      Effect  reason → matched_rule
=====  =============================================  ======  ===============================
R1     principal inactive                             deny    policy_default → R1:inactive_principal
R2     unrevoked deny grant (principal|group|role)    deny    explicit_deny → R2:explicit_deny
R3     ``owner_principal_id == principal.id``         allow   R3:owner
R4     principal has role ``admin``                   allow   R4:admin
R5     unrevoked allow grant (principal|group|role)   allow   R5:explicit_grant
R6     classification ``restricted``                  deny    classification_requires_grant →
                                                              R6:restricted
R7     classification ``confidential``                deny    classification_requires_grant →
                                                              R7:confidential
R8     raw platform membership (per ``raw.kind``)     allow   R8:<kind>
       … not a member                                 deny    no_source_membership → R8:<kind>
R9     no snapshot                                    deny    unknown_permissions →
                                                              R9:unknown_permissions
       snapshot version ≠ document version            deny    unknown_permissions →
                                                              R9:permission_version_mismatch
R10    nothing else applied                           deny    policy_default → R10:default_deny
guard  any exception while evaluating                 deny    unknown_permissions →
                                                              ERR:evaluation_error
=====  =============================================  ======  ===============================

Grants only count when ``grant.document_id == doc.document_id`` and ``grant.scope == "read"``.
Revoked grants are ignored by R2/R5 (a formerly-allowed principal falls through to R6+).

``grant_revoked``: when the outcome is a deny from R6–R10 **and** the principal matches at least
one *revoked allow* grant (read scope) on the document, the reason is rewritten to
``grant_revoked`` while ``matched_rule`` keeps the rule that actually denied (e.g.
``R7:confidential``). At that point no unrevoked matching grant can exist (R2/R5 would have
fired), so "the only matching grants were revoked" holds by construction. R1, R2 and ERR reasons
are never rewritten, revoked *deny* grants never produce ``grant_revoked``, and a revoked grant
never turns an allow into a deny (if R8 still allows, the principal keeps access).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
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

DEFAULT_POLICY_VERSION = "ac-v1"
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
RULE_DEFAULT_DENY = "R10:default_deny"
RULE_EVALUATION_ERROR = "ERR:evaluation_error"


class DefaultAccessPolicy:
    """The foundation policy (``ac-v1``). Pure and synchronous; see the module docstring for the
    rule table. Satisfies :class:`access_control.protocols.AccessPolicy`."""

    def __init__(self, policy_version: str = DEFAULT_POLICY_VERSION) -> None:
        self.policy_version = policy_version

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
        seen: set[str] = set()
        allowed_ids: list[str] = []
        for decision in decisions:
            if decision.decision == Effect.allow and decision.document_id not in seen:
                seen.add(decision.document_id)
                allowed_ids.append(decision.document_id)
        return FilterResult(allowed_ids=allowed_ids, decisions=decisions)

    # ------------------------------------------------------------------ rules

    def _decide(
        self, principal: Principal, doc: DocumentAccessContext, now: datetime
    ) -> AccessDecision:
        snapshot = doc.source_permissions
        permission_version = doc.permission_version or (
            snapshot.permission_version if snapshot is not None else None
        )

        def decision(rule: str, reason: DenyReason | None) -> AccessDecision:
            return AccessDecision(
                document_id=doc.document_id,
                decision=Effect.allow if reason is None else Effect.deny,
                reason=reason,
                matched_rule=rule,
                permission_version=permission_version,
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

        # R2
        if any(g.effect == Effect.deny for g in active):
            return decision(RULE_EXPLICIT_DENY, DenyReason.explicit_deny)
        # R3
        if doc.owner_principal_id is not None and doc.owner_principal_id == principal.id:
            return decision(RULE_OWNER, None)
        # R4
        if ADMIN_ROLE in principal.roles:
            return decision(RULE_ADMIN, None)
        # R5
        if any(g.effect == Effect.allow for g in active):
            return decision(RULE_EXPLICIT_GRANT, None)

        # R6–R10
        rule, reason = _classification_and_source(principal, doc)
        if reason is None:
            return decision(rule, None)
        if any(g.effect == Effect.allow and g.revoked_at is not None for g in matching):
            reason = DenyReason.grant_revoked
        return decision(rule, reason)


def _subject_matches(grant: Grant, principal: Principal) -> bool:
    match grant.subject_type:
        case SubjectType.principal:
            return grant.subject_id == principal.id
        case SubjectType.group:
            return grant.subject_id in principal.groups
        case SubjectType.role:
            return grant.subject_id in principal.roles
    return False


def _classification_and_source(
    principal: Principal, doc: DocumentAccessContext
) -> tuple[str, DenyReason | None]:
    """R6–R10. Returns ``(matched_rule, None)`` for allow, ``(matched_rule, reason)`` for deny."""

    if doc.classification == Classification.restricted:
        return RULE_RESTRICTED, DenyReason.classification_requires_grant
    if doc.classification == Classification.confidential:
        return RULE_CONFIDENTIAL, DenyReason.classification_requires_grant

    snapshot = doc.source_permissions
    if snapshot is None:
        return RULE_UNKNOWN_PERMISSIONS, DenyReason.unknown_permissions
    if doc.permission_version is not None and doc.permission_version != snapshot.permission_version:
        return RULE_PERMISSION_VERSION_MISMATCH, DenyReason.unknown_permissions

    member = has_source_membership(principal, snapshot.raw)
    if member is None:
        return RULE_DEFAULT_DENY, DenyReason.policy_default
    rule = f"{RULE_SOURCE_PREFIX}{snapshot.raw.kind}"
    return (rule, None) if member else (rule, DenyReason.no_source_membership)


# ---------------------------------------------------------------------- R8 per platform


def platform_identities(principal: Principal, kind: str) -> set[str]:
    """The ids a principal is known by on platform ``kind``.

    ``external_identities[kind]`` when present, else ``principal.id``; for ``gdrive`` and
    ``email`` the principal's ``email`` is added. Email-like values are compared lower-cased by
    the gdrive/email evaluators.
    """

    external = principal.external_identities.get(kind)
    ids = {external} if external else {principal.id}
    if kind in (SourceKind.gdrive, SourceKind.email) and principal.email:
        ids.add(principal.email)
    return ids


def has_source_membership(principal: Principal, raw: object) -> bool | None:
    """Evaluate the platform's own read semantics. ``None`` = unsupported raw kind (→ R10)."""

    match raw:
        case ConfluencePermissions():
            return _confluence(principal, raw)
        case JiraPermissions():
            return _jira(principal, raw)
        case SlackPermissions():
            return _slack(principal, raw)
        case GDrivePermissions():
            return _gdrive(principal, raw)
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
    groups = set(principal.groups)
    if not _in(ids, groups, raw.space_view_users, raw.space_view_groups):
        return False
    if (raw.page_view_users or raw.page_view_groups) and not _in(
        ids, groups, raw.page_view_users, raw.page_view_groups
    ):
        return False
    for ancestor in raw.ancestors:
        if not isinstance(ancestor, ConfluenceAncestor):
            continue  # bare page id: no restriction captured for that ancestor
        if (ancestor.view_users or ancestor.view_groups) and not _in(
            ids, groups, ancestor.view_users, ancestor.view_groups
        ):
            return False
    return True


def _jira(principal: Principal, raw: JiraPermissions) -> bool:
    ids = platform_identities(principal, SourceKind.jira)
    groups = set(principal.groups)
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
    if raw.channel_type == SlackChannelType.public:
        return raw.workspace_member_ids is None or not ids.isdisjoint(raw.workspace_member_ids)
    return not ids.isdisjoint(raw.member_ids)


def _norm_address(value: str) -> str:
    address = parseaddr(value)[1] or value
    return address.strip().lower()


def _gdrive(principal: Principal, raw: GDrivePermissions) -> bool:
    ids = {_norm_address(i) for i in platform_identities(principal, SourceKind.gdrive)}
    domains = {i.rsplit("@", 1)[1] for i in ids if "@" in i}
    groups = {g.lower() for g in principal.groups}
    for ace in raw.acl:
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
