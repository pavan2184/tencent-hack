"""access_control — permission-aware retrieval for Brain Sauce (owner: Chai).

Principals, groups and roles; per-platform raw permission semantics (never flattened);
classification; grant/revoke; access requests; and a pure, ordered policy whose decisions are
taken **before** any evidence reaches an LLM, without leaking the existence of denied documents.

This package never imports ``app``; the app implements the async store Protocols.
"""

from __future__ import annotations

from access_control.connectors import (
    gdrive_permissions_from_api,
    permission_fingerprint,
    slack_permissions_from_api,
)
from access_control.memory import (
    InMemoryAccessRequestStore,
    InMemoryGrantStore,
    InMemoryPermissionSnapshotStore,
    InMemoryPrincipalDirectory,
)
from access_control.models import (
    AccessDecision,
    AccessRequest,
    AccessRequestStatus,
    AccessSummary,
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
    GDriveAce,
    GDriveAceType,
    GDrivePermissions,
    GDriveRole,
    JiraPermissions,
    McpExternalPermissions,
    RawPermissions,
    SlackChannelType,
    SlackPermissions,
    SourceKind,
    SourcePermissions,
    UploadPermissions,
    parse_raw_permissions,
)
from access_control.policy import (
    ADMIN_ROLE,
    DEFAULT_MAX_PERMISSION_AGE,
    DEFAULT_POLICY_VERSION,
    DefaultAccessPolicy,
    has_source_membership,
    platform_identities,
)
from access_control.protocols import (
    AccessControlError,
    AccessPolicy,
    AccessRequestNotFound,
    AccessRequestStore,
    GrantNotFound,
    GrantStore,
    PermissionSnapshotStore,
    PrincipalDirectory,
    SourcePermissionVerifier,
)
from access_control.service import AccessControlService

SCHEMA_VERSION = 1
__version__ = "0.1.0"

__all__ = [
    "ADMIN_ROLE",
    "DEFAULT_MAX_PERMISSION_AGE",
    "DEFAULT_POLICY_VERSION",
    "SCHEMA_VERSION",
    "AccessControlError",
    "AccessControlService",
    "AccessDecision",
    "AccessPolicy",
    "AccessRequest",
    "AccessRequestNotFound",
    "AccessRequestStatus",
    "AccessRequestStore",
    "AccessSummary",
    "Classification",
    "ConfluenceAncestor",
    "ConfluencePermissions",
    "DefaultAccessPolicy",
    "DenyReason",
    "DocumentAccessContext",
    "Effect",
    "EmailPermissions",
    "FilterResult",
    "GDriveAce",
    "GDriveAceType",
    "GDrivePermissions",
    "GDriveRole",
    "Grant",
    "GrantNotFound",
    "GrantStore",
    "InMemoryAccessRequestStore",
    "InMemoryGrantStore",
    "InMemoryPermissionSnapshotStore",
    "InMemoryPrincipalDirectory",
    "JiraPermissions",
    "McpExternalPermissions",
    "PermissionSnapshotStore",
    "Principal",
    "PrincipalDirectory",
    "RawPermissions",
    "SlackChannelType",
    "SlackPermissions",
    "SourceKind",
    "SourcePermissions",
    "SourcePermissionVerifier",
    "SubjectType",
    "UploadPermissions",
    "__version__",
    "has_source_membership",
    "gdrive_permissions_from_api",
    "parse_raw_permissions",
    "platform_identities",
    "permission_fingerprint",
    "slack_permissions_from_api",
]
