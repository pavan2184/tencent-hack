"""Async store/provider seams and a pure policy. In-memory implementations ship with the library;
production database and provider adapters are the integrating app's responsibility.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from access_control.models import (
    AccessDecision,
    AccessRequest,
    DocumentAccessContext,
    FilterResult,
    Grant,
    Principal,
    SubjectType,
)
from access_control.permissions import SourcePermissions


class AccessControlError(Exception):
    """Base error for the access_control library (also raised for store conflicts, e.g. a
    duplicate grant id or deciding an already-decided access request → app maps to 409)."""


class GrantNotFound(AccessControlError):
    """No grant with the given id."""


class AccessRequestNotFound(AccessControlError):
    """No access request with the given id."""


@runtime_checkable
class AccessPolicy(Protocol):
    """Decides whether a principal may read a document.

    Invariants:
    - ``decide`` is pure and deterministic: same inputs (incl. ``now``) → same decision; no I/O.
    - ``decide`` never raises. Missing or malformed data fails closed: deny with
      ``unknown_permissions``.
    - Every decision stamps ``matched_rule``, ``policy_version`` (= ``self.policy_version``),
      ``permission_version`` (from the document) and ``evaluated_at = now``.
    - ``filter`` returns exactly one decision per input document, in input order, and
      ``allowed_ids`` ⊆ input ids, in input order (de-duplicated). A denied id never appears in
      ``allowed_ids``.
    - Callers run ``filter`` on retrieval candidates *before* any evidence reaches an LLM.
    """

    policy_version: str

    def decide(
        self, principal: Principal, doc: DocumentAccessContext, *, now: datetime
    ) -> AccessDecision: ...

    def filter(
        self, principal: Principal, docs: Iterable[DocumentAccessContext], *, now: datetime
    ) -> FilterResult: ...


@runtime_checkable
class SourcePermissionVerifier(Protocol):
    """Optional live read check, executed only after local policy allows.

    Check the resolved asker's provider identity, never the connector's broad service account.
    True confirms, False denies, None/errors fail closed. Implementations must bound I/O timeouts.
    This check cannot widen the snapshot/local policy's audience.
    """

    async def verify(
        self, principal: Principal, doc: DocumentAccessContext, *, now: datetime
    ) -> bool | None: ...


@runtime_checkable
class GrantStore(Protocol):
    """Per-document grants.

    Invariants:
    - Revocation is a soft delete: the grant keeps its row with ``revoked_at``/``revoked_by``
      set, and stays visible to ``list_*`` (the policy needs it for ``grant_revoked``).
    - ``list_for_documents`` returns a key for **every** requested id (``[]`` when none), and
      includes revoked grants. Order within a list is insertion order.
    - ``revoke`` is idempotent: revoking an already-revoked grant returns it unchanged (first
      revocation wins). Unknown id → ``GrantNotFound``.
    - ``add`` with an id that already exists → ``AccessControlError``.
    """

    async def list_for_documents(self, document_ids: Sequence[str]) -> dict[str, list[Grant]]: ...

    async def add(self, grant: Grant) -> Grant: ...

    async def revoke(self, grant_id: str, *, by: str, at: datetime) -> Grant: ...

    async def list_for_subject(self, subject_type: SubjectType, subject_id: str) -> list[Grant]:
        """All grants (revoked included) whose subject is exactly ``(subject_type, subject_id)``."""
        ...


@runtime_checkable
class PermissionSnapshotStore(Protocol):
    """Latest raw platform permission snapshot per document (``source_permissions`` table).

    Invariants:
    - ``get_many`` omits ids with no snapshot (the policy then denies ``unknown_permissions``);
      it never invents a default snapshot.
    - ``put`` replaces the document's snapshot (one current snapshot per document).
    """

    async def get_many(self, document_ids: Sequence[str]) -> dict[str, SourcePermissions]: ...

    async def put(self, document_id: str, perms: SourcePermissions) -> None: ...


@runtime_checkable
class PrincipalDirectory(Protocol):
    """Resolves identities at query time.

    Invariants:
    - ``get`` returns inactive principals too (``is_active=False``); callers decide (the app's
      ``get_principal`` answers 401 ``unknown_actor``, the policy denies via R1).
    - ``groups_of`` of an unknown principal is ``[]``, never an error.
    """

    async def get(self, principal_id: str) -> Principal | None: ...

    async def list(self) -> list[Principal]: ...

    async def groups_of(self, principal_id: str) -> list[str]: ...


@runtime_checkable
class AccessRequestStore(Protocol):
    """Access requests (``access_requests`` table).

    Invariants:
    - ``create`` stores the request as given (status normally ``pending``); duplicate id →
      ``AccessControlError``.
    - ``list_pending`` returns pending requests in creation order.
    - ``decide`` moves a pending request to ``approved``/``denied`` and stamps
      ``decided_at``/``decided_by``. Unknown id → ``AccessRequestNotFound``; already decided →
      ``AccessControlError``. Approving does **not** create a grant — the caller does that.
    """

    async def create(self, req: AccessRequest) -> AccessRequest: ...

    async def list_pending(self) -> list[AccessRequest]: ...

    async def decide(
        self, request_id: str, *, approved: bool, by: str, at: datetime
    ) -> AccessRequest: ...
