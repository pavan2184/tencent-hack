"""`access_control` store Protocols over Postgres.

- `SqlGrantStore` (`grants`, 0200): soft revoke (rows are never deleted; `revoked_at`/`revoked_by`
  set once — first revocation wins, later calls return it unchanged); `list_for_documents` has a
  key for every requested id and includes revoked grants; duplicate id (or a second ACTIVE grant
  for the same document/subject/effect/scope, `uq_grants_active`) → `AccessControlError`.
- `SqlPermissionSnapshotStore` (`source_permissions`, 0200): one raw snapshot per page; `raw` is
  the discriminated permissions object as JSON and round-trips through
  `access_control.parse_raw_permissions` → `SourcePermissions`. Ids without a (valid) snapshot
  are omitted so the policy fails closed (`unknown_permissions`).
- `SqlPrincipalDirectory` (`principals`, `groups`, `group_memberships`, 0001):
  `Principal.groups` = the principal's membership group ids, sorted.
- `SqlAccessRequestStore` (`access_requests`, 0001): pending → approved/denied exactly once.
- `SqlGroupDirectory` (`access_group_parents`, `access_group_platform_ids`, 0201): group
  hierarchy and per-platform group ids. `put` replaces a group's whole definition in one
  transaction; both groups of a parent link must exist (else `AccessControlError`).

"Insertion order" for grants is `(granted_at, id)` — the table has no sequence column.
Malformed (non-UUID) document/grant/request ids read as misses, never as database errors.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from access_control import (
    AccessControlError,
    AccessRequest,
    AccessRequestNotFound,
    AccessRequestStatus,
    Grant,
    GrantNotFound,
    GroupDefinition,
    Principal,
    SourcePermissions,
    SubjectType,
    parse_raw_permissions,
)
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AccessRequestRow,
    GrantRow,
    GroupMembershipRow,
    GroupRow,
    PrincipalRow,
    SourcePermissionRow,
    canonical_uuid,
    is_uuid,
)

__all__ = [
    "SqlAccessRequestStore",
    "SqlGrantStore",
    "SqlGroupDirectory",
    "SqlPermissionSnapshotStore",
    "SqlPrincipalDirectory",
]

log = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


class _SqlStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _tx(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session, session.begin():
            yield session


def _db_reason(exc: Exception) -> str:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", None)
    return constraint or (orig or exc).__class__.__name__


# ------------------------------------------------------------------------------------- grants

_GRANT_COLS = [GrantRow.__table__.c[name] for name in Grant.model_fields]


def _grant(row: Any) -> Grant:
    return Grant.model_validate(dict(row._mapping))


class SqlGrantStore(_SqlStore):
    """Satisfies :class:`access_control.GrantStore`."""

    async def list_for_documents(self, document_ids: Sequence[str]) -> dict[str, list[Grant]]:
        out: dict[str, list[Grant]] = {doc_id: [] for doc_id in document_ids}
        # canonical UUID -> every caller spelling of it (keys are the caller's ids)
        canon: dict[str, list[str]] = {}
        for doc_id in out:
            c = canonical_uuid(doc_id)
            if c is not None:
                canon.setdefault(c, []).append(doc_id)
        if not canon:
            return out
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(*_GRANT_COLS)
                    .where(GrantRow.document_id.in_(list(canon)))
                    .order_by(GrantRow.granted_at, GrantRow.id)
                )
            ).all()
        for row in rows:
            for key in canon.get(row.document_id, []):
                out[key].append(_grant(row).model_copy(update={"document_id": key}))
        return out

    async def add(self, grant: Grant) -> Grant:
        if not is_uuid(grant.id):
            raise AccessControlError(f"grant id {grant.id!r} is not a UUID")
        if not is_uuid(grant.document_id):
            raise AccessControlError(f"grant document_id {grant.document_id!r} is not a UUID")
        values = {k: getattr(v, "value", v) for k, v in grant.model_dump(mode="python").items()}
        try:
            async with self._tx() as s:
                row = (
                    await s.execute(pg_insert(GrantRow).values(**values).returning(*_GRANT_COLS))
                ).one()
        except (IntegrityError, DataError) as exc:
            raise AccessControlError(
                f"grant {grant.id!r} rejected ({_db_reason(exc)}): duplicate id, an identical "
                "active grant, or an unknown document"
            ) from exc
        return _grant(row)

    async def revoke(self, grant_id: str, *, by: str, at: datetime) -> Grant:
        if not is_uuid(grant_id):
            raise GrantNotFound(grant_id)
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_GRANT_COLS).where(GrantRow.id == grant_id).with_for_update()
                )
            ).first()
            if row is None:
                raise GrantNotFound(grant_id)
            if row.revoked_at is not None:  # idempotent: first revocation wins
                return _grant(row)
            row = (
                await s.execute(
                    update(GrantRow)
                    .where(GrantRow.id == grant_id)
                    .values(revoked_at=at, revoked_by=by)
                    .returning(*_GRANT_COLS)
                )
            ).one()
        return _grant(row)

    async def list_for_subject(self, subject_type: SubjectType, subject_id: str) -> list[Grant]:
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(*_GRANT_COLS)
                    .where(
                        GrantRow.subject_type == SubjectType(subject_type).value,
                        GrantRow.subject_id == subject_id,
                    )
                    .order_by(GrantRow.granted_at, GrantRow.id)
                )
            ).all()
        return [_grant(r) for r in rows]


# --------------------------------------------------------------------- permission snapshots


class SqlPermissionSnapshotStore(_SqlStore):
    """Satisfies :class:`access_control.PermissionSnapshotStore`."""

    async def get_many(self, document_ids: Sequence[str]) -> dict[str, SourcePermissions]:
        canon: dict[str, list[str]] = {}
        for doc_id in dict.fromkeys(document_ids):
            c = canonical_uuid(doc_id)
            if c is not None:
                canon.setdefault(c, []).append(doc_id)
        if not canon:
            return {}
        T = SourcePermissionRow
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(
                        T.page_id,
                        T.kind,
                        T.raw,
                        T.permission_version,
                        T.captured_at,
                        T.connector_run_id,
                    ).where(T.page_id.in_(list(canon)))
                )
            ).all()
        out: dict[str, SourcePermissions] = {}
        for row in rows:
            try:
                perms = SourcePermissions(
                    kind=row.kind,
                    raw=parse_raw_permissions(row.raw),
                    permission_version=row.permission_version,
                    captured_at=row.captured_at,
                    connector_run_id=row.connector_run_id,
                )
            except ValidationError as exc:
                # Fail closed: a snapshot we cannot parse is treated as missing.
                log.warning(
                    "source_permissions for %s is malformed; omitting (%d errors)",
                    row.page_id,
                    exc.error_count(),
                )
                continue
            for key in canon.get(row.page_id, []):
                out[key] = perms
        return out

    async def put(self, document_id: str, perms: SourcePermissions) -> None:
        if not is_uuid(document_id):
            raise AccessControlError(f"document_id {document_id!r} is not a UUID")
        run_id = perms.connector_run_id
        if run_id is not None and not is_uuid(run_id):
            # connector_run_id is a soft reference to sync_runs (UUID); a non-UUID cannot point
            # at a run, so it is not stored.
            log.warning(
                "source_permissions.connector_run_id %r is not a UUID; storing NULL", run_id
            )
            run_id = None
        values = {
            "page_id": document_id,
            "kind": perms.kind.value,
            "raw": perms.raw.model_dump(mode="json"),
            "permission_version": perms.permission_version,
            "captured_at": perms.captured_at,
            "connector_run_id": run_id,
        }
        stmt = pg_insert(SourcePermissionRow).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SourcePermissionRow.page_id],
            set_={k: stmt.excluded[k] for k in values if k != "page_id"},
        )
        try:
            async with self._tx() as s:
                await s.execute(stmt)
        except (IntegrityError, DataError) as exc:
            raise AccessControlError(
                f"permission snapshot for {document_id!r} rejected ({_db_reason(exc)})"
            ) from exc


# ------------------------------------------------------------------------------- principals


async def load_principals(
    session: AsyncSession, ids: Sequence[str] | None = None
) -> list[Principal]:
    """Principals (ordered by id, codepoint order) with sorted membership group ids."""
    stmt = select(
        PrincipalRow.id,
        PrincipalRow.display_name,
        PrincipalRow.email,
        PrincipalRow.roles,
        PrincipalRow.external_identities,
        PrincipalRow.is_active,
    )
    mstmt = select(GroupMembershipRow.principal_id, GroupMembershipRow.group_id)
    if ids is not None:
        stmt = stmt.where(PrincipalRow.id.in_(list(ids)))
        mstmt = mstmt.where(GroupMembershipRow.principal_id.in_(list(ids)))
    rows = (await session.execute(stmt)).all()
    groups: dict[str, list[str]] = {}
    for principal_id, group_id in (await session.execute(mstmt)).all():
        groups.setdefault(principal_id, []).append(group_id)
    principals = [
        Principal(
            id=row.id,
            display_name=row.display_name,
            email=row.email,
            roles=list(row.roles or []),
            groups=sorted(groups.get(row.id, [])),
            external_identities=dict(row.external_identities or {}),
            is_active=row.is_active,
        )
        for row in rows
    ]
    return sorted(principals, key=lambda p: p.id)


async def write_principal(session: AsyncSession, principal: Principal) -> None:
    """Insert or update one principal row (memberships untouched)."""
    values = {
        "id": principal.id,
        "display_name": principal.display_name,
        "email": principal.email,
        "roles": list(principal.roles),
        "external_identities": dict(principal.external_identities),
        "is_active": principal.is_active,
    }
    stmt = pg_insert(PrincipalRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[PrincipalRow.id],
        set_={
            **{k: stmt.excluded[k] for k in values if k != "id"},
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)


async def replace_memberships(
    session: AsyncSession, principal_id: str, group_ids: Sequence[str], *, create_groups: bool
) -> None:
    """Make the principal's memberships exactly `group_ids` (optionally creating groups)."""
    wanted = list(dict.fromkeys(group_ids))
    if create_groups and wanted:
        await session.execute(
            pg_insert(GroupRow)
            .values([{"id": g, "name": g} for g in wanted])
            .on_conflict_do_nothing(index_elements=[GroupRow.id])
        )
    stale = delete(GroupMembershipRow).where(GroupMembershipRow.principal_id == principal_id)
    if wanted:
        stale = stale.where(GroupMembershipRow.group_id.not_in(wanted))
    await session.execute(stale)
    if wanted:
        await session.execute(
            pg_insert(GroupMembershipRow)
            .values([{"principal_id": principal_id, "group_id": g} for g in wanted])
            .on_conflict_do_nothing()
        )


class SqlPrincipalDirectory(_SqlStore):
    """Satisfies :class:`access_control.PrincipalDirectory`."""

    async def get(self, principal_id: str) -> Principal | None:
        async with self._tx() as s:
            found = await load_principals(s, [principal_id])
        return found[0] if found else None

    async def list(self) -> list[Principal]:
        async with self._tx() as s:
            return await load_principals(s)

    async def groups_of(self, principal_id: str) -> list[str]:
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(GroupMembershipRow.group_id).where(
                        GroupMembershipRow.principal_id == principal_id
                    )
                )
            ).scalars()
            return sorted(rows)

    async def upsert(self, principal: Principal) -> None:
        """Seed/test helper (not part of the Protocol; async, unlike the in-memory one): insert or
        replace a principal AND set its memberships to `principal.groups` (missing groups are
        created with name = id)."""
        async with self._tx() as s:
            await write_principal(s, principal)
            await replace_memberships(s, principal.id, principal.groups, create_groups=True)


# ------------------------------------------------------------------------- group directory


class SqlGroupDirectory(_SqlStore):
    """Satisfies :class:`access_control.GroupDirectory`."""

    async def list_definitions(self) -> list[GroupDefinition]:
        async with self._tx() as s:
            parents = (
                await s.execute(
                    text(
                        "SELECT group_id, parent_group_id FROM access_group_parents "
                        "ORDER BY group_id, parent_group_id"
                    )
                )
            ).all()
            platform = (
                await s.execute(
                    text(
                        "SELECT group_id, source_kind, platform_group_id "
                        "FROM access_group_platform_ids ORDER BY group_id, source_kind"
                    )
                )
            ).all()
        by_id: dict[str, dict[str, Any]] = {}
        for group_id, parent_id in parents:
            by_id.setdefault(group_id, {"parent_ids": [], "platform_ids": {}})
            by_id[group_id]["parent_ids"].append(parent_id)
        for group_id, kind, platform_id in platform:
            by_id.setdefault(group_id, {"parent_ids": [], "platform_ids": {}})
            by_id[group_id]["platform_ids"][kind] = platform_id
        return [GroupDefinition(id=gid, **fields) for gid, fields in sorted(by_id.items())]

    async def put(self, definition: GroupDefinition) -> None:
        params = {"group_id": definition.id}
        try:
            async with self._tx() as s:
                await s.execute(
                    text("DELETE FROM access_group_parents WHERE group_id = :group_id"), params
                )
                await s.execute(
                    text("DELETE FROM access_group_platform_ids WHERE group_id = :group_id"),
                    params,
                )
                parents = list(dict.fromkeys(definition.parent_ids))
                if parents:
                    await s.execute(
                        text(
                            "INSERT INTO access_group_parents (group_id, parent_group_id) "
                            "VALUES (:group_id, :parent_group_id)"
                        ),
                        [{**params, "parent_group_id": p} for p in parents],
                    )
                if definition.platform_ids:
                    await s.execute(
                        text(
                            "INSERT INTO access_group_platform_ids "
                            "(group_id, source_kind, platform_group_id) "
                            "VALUES (:group_id, :source_kind, :platform_group_id)"
                        ),
                        [
                            {**params, "source_kind": str(kind), "platform_group_id": pid}
                            for kind, pid in definition.platform_ids.items()
                        ],
                    )
        except IntegrityError as exc:
            raise AccessControlError(
                f"group definition {definition.id!r}: {_db_reason(exc)}"
            ) from exc


# --------------------------------------------------------------------------- access requests

_REQUEST_COLS = [AccessRequestRow.__table__.c[name] for name in AccessRequest.model_fields]


def _request(row: Any) -> AccessRequest:
    return AccessRequest.model_validate(dict(row._mapping))


class SqlAccessRequestStore(_SqlStore):
    """Satisfies :class:`access_control.AccessRequestStore`.

    `access_requests.document_id` is a UUID with no FK: a non-UUID id cannot be stored and raises
    `AccessControlError` — the router must keep answering 202 for it (no existence signal).
    """

    async def create(self, req: AccessRequest) -> AccessRequest:
        if not is_uuid(req.id):
            raise AccessControlError(f"access request id {req.id!r} is not a UUID")
        if not is_uuid(req.document_id):
            raise AccessControlError(
                f"access request document_id {req.document_id!r} is not a UUID"
            )
        values = {k: getattr(v, "value", v) for k, v in req.model_dump(mode="python").items()}
        try:
            async with self._tx() as s:
                row = (
                    await s.execute(
                        pg_insert(AccessRequestRow).values(**values).returning(*_REQUEST_COLS)
                    )
                ).one()
        except (IntegrityError, DataError) as exc:
            raise AccessControlError(
                f"access request {req.id!r} rejected ({_db_reason(exc)}): duplicate id or "
                "unknown principal"
            ) from exc
        return _request(row)

    async def list_pending(self) -> list[AccessRequest]:
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(*_REQUEST_COLS)
                    .where(AccessRequestRow.status == AccessRequestStatus.pending.value)
                    .order_by(AccessRequestRow.created_at, AccessRequestRow.id)
                )
            ).all()
        return [_request(r) for r in rows]

    async def decide(
        self, request_id: str, *, approved: bool, by: str, at: datetime
    ) -> AccessRequest:
        if not is_uuid(request_id):
            raise AccessRequestNotFound(request_id)
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_REQUEST_COLS)
                    .where(AccessRequestRow.id == request_id)
                    .with_for_update()
                )
            ).first()
            if row is None:
                raise AccessRequestNotFound(request_id)
            if row.status != AccessRequestStatus.pending.value:
                raise AccessControlError(f"access request {request_id!r} is already {row.status}")
            status = AccessRequestStatus.approved if approved else AccessRequestStatus.denied
            row = (
                await s.execute(
                    update(AccessRequestRow)
                    .where(AccessRequestRow.id == request_id)
                    .values(status=status.value, decided_at=at, decided_by=by)
                    .returning(*_REQUEST_COLS)
                )
            ).one()
        return _request(row)
