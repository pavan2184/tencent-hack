"""In-memory store implementations, used by this library's tests and by the app's test conftest.

Every store hands out deep copies, so callers can never mutate stored state by accident.
Single-event-loop safe (no ``await`` between read and write).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from access_control.groups import GroupDefinition
from access_control.models import (
    AccessRequest,
    AccessRequestStatus,
    Grant,
    Principal,
    SubjectType,
)
from access_control.permissions import SourcePermissions
from access_control.protocols import (
    AccessControlError,
    AccessRequestNotFound,
    GrantNotFound,
)


class InMemoryGrantStore:
    """Satisfies :class:`access_control.protocols.GrantStore`."""

    def __init__(self, grants: Iterable[Grant] = ()) -> None:
        self._grants: dict[str, Grant] = {}
        for grant in grants:
            self._insert(grant)

    def _insert(self, grant: Grant) -> Grant:
        if grant.id in self._grants:
            raise AccessControlError(f"grant {grant.id!r} already exists")
        self._grants[grant.id] = grant.model_copy(deep=True)
        return grant.model_copy(deep=True)

    async def list_for_documents(self, document_ids: Sequence[str]) -> dict[str, list[Grant]]:
        out: dict[str, list[Grant]] = {doc_id: [] for doc_id in document_ids}
        for grant in self._grants.values():
            if grant.document_id in out:
                out[grant.document_id].append(grant.model_copy(deep=True))
        return out

    async def add(self, grant: Grant) -> Grant:
        return self._insert(grant)

    async def revoke(self, grant_id: str, *, by: str, at: datetime) -> Grant:
        grant = self._grants.get(grant_id)
        if grant is None:
            raise GrantNotFound(grant_id)
        if grant.revoked_at is None:
            grant = grant.model_copy(update={"revoked_at": at, "revoked_by": by})
            self._grants[grant_id] = grant
        return grant.model_copy(deep=True)

    async def list_for_subject(self, subject_type: SubjectType, subject_id: str) -> list[Grant]:
        return [
            g.model_copy(deep=True)
            for g in self._grants.values()
            if g.subject_type == subject_type and g.subject_id == subject_id
        ]


class InMemoryPermissionSnapshotStore:
    """Satisfies :class:`access_control.protocols.PermissionSnapshotStore`."""

    def __init__(self, snapshots: Mapping[str, SourcePermissions] | None = None) -> None:
        self._snapshots: dict[str, SourcePermissions] = {
            doc_id: perms.model_copy(deep=True) for doc_id, perms in (snapshots or {}).items()
        }

    async def get_many(self, document_ids: Sequence[str]) -> dict[str, SourcePermissions]:
        return {
            doc_id: self._snapshots[doc_id].model_copy(deep=True)
            for doc_id in document_ids
            if doc_id in self._snapshots
        }

    async def put(self, document_id: str, perms: SourcePermissions) -> None:
        self._snapshots[document_id] = perms.model_copy(deep=True)


class InMemoryPrincipalDirectory:
    """Satisfies :class:`access_control.protocols.PrincipalDirectory`."""

    def __init__(self, principals: Iterable[Principal] = ()) -> None:
        self._principals: dict[str, Principal] = {}
        for principal in principals:
            self.upsert(principal)

    def upsert(self, principal: Principal) -> None:
        """Test/seed helper (not part of the Protocol): insert or replace a principal."""
        self._principals[principal.id] = principal.model_copy(deep=True)

    async def get(self, principal_id: str) -> Principal | None:
        principal = self._principals.get(principal_id)
        return principal.model_copy(deep=True) if principal is not None else None

    async def list(self) -> list[Principal]:
        return [p.model_copy(deep=True) for p in self._principals.values()]

    async def groups_of(self, principal_id: str) -> list[str]:
        principal = self._principals.get(principal_id)
        return [*principal.groups] if principal is not None else []


class InMemoryGroupDirectory:
    """Satisfies :class:`access_control.protocols.GroupDirectory`."""

    def __init__(self, definitions: Iterable[GroupDefinition] = ()) -> None:
        self._definitions: dict[str, GroupDefinition] = {}
        for definition in definitions:
            self._definitions[definition.id] = definition.model_copy(deep=True)

    async def list_definitions(self) -> list[GroupDefinition]:
        return [d.model_copy(deep=True) for _, d in sorted(self._definitions.items())]

    async def put(self, definition: GroupDefinition) -> None:
        self._definitions[definition.id] = definition.model_copy(deep=True)


class InMemoryAccessRequestStore:
    """Satisfies :class:`access_control.protocols.AccessRequestStore`."""

    def __init__(self, requests: Iterable[AccessRequest] = ()) -> None:
        self._requests: dict[str, AccessRequest] = {}
        for req in requests:
            self._insert(req)

    def _insert(self, req: AccessRequest) -> AccessRequest:
        if req.id in self._requests:
            raise AccessControlError(f"access request {req.id!r} already exists")
        self._requests[req.id] = req.model_copy(deep=True)
        return req.model_copy(deep=True)

    async def create(self, req: AccessRequest) -> AccessRequest:
        return self._insert(req)

    async def list_pending(self) -> list[AccessRequest]:
        return [
            r.model_copy(deep=True)
            for r in self._requests.values()
            if r.status == AccessRequestStatus.pending
        ]

    async def decide(
        self, request_id: str, *, approved: bool, by: str, at: datetime
    ) -> AccessRequest:
        req = self._requests.get(request_id)
        if req is None:
            raise AccessRequestNotFound(request_id)
        if req.status != AccessRequestStatus.pending:
            raise AccessControlError(f"access request {request_id!r} is already {req.status}")
        status = AccessRequestStatus.approved if approved else AccessRequestStatus.denied
        req = req.model_copy(update={"status": status, "decided_at": at, "decided_by": by})
        self._requests[request_id] = req
        return req.model_copy(deep=True)
