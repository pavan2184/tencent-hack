"""Query-time orchestration. Reload authority, filter candidates, optionally confirm live access.

No content, model calls, network clients or cached allow decisions belong in this service.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime

from access_control.models import (
    AccessDecision,
    DenyReason,
    DocumentAccessContext,
    Effect,
    FilterResult,
    Principal,
)
from access_control.policy import DefaultAccessPolicy
from access_control.protocols import (
    AccessPolicy,
    GrantStore,
    PermissionSnapshotStore,
    PrincipalDirectory,
    SourcePermissionVerifier,
)


class AccessControlService:
    """Use with server-owned document metadata and an authenticated principal id.

    The snapshot store must contain current connector state; an optional live verifier closes
    the gap between connector runs. Recheck cached answers before publishing their citations.
    """

    def __init__(
        self,
        *,
        directory: PrincipalDirectory,
        grants: GrantStore,
        snapshots: PermissionSnapshotStore,
        policy: AccessPolicy | None = None,
        verifier: SourcePermissionVerifier | None = None,
    ) -> None:
        self.directory = directory
        self.grants = grants
        self.snapshots = snapshots
        self.policy = policy or DefaultAccessPolicy()
        self.verifier = verifier

    async def filter(
        self, principal_id: str, docs: Iterable[DocumentAccessContext], *, now: datetime
    ) -> FilterResult:
        candidates = list(docs)
        if not candidates:
            return FilterResult(allowed_ids=[], decisions=[])
        try:
            principal = await self.directory.get(principal_id)
            if principal is None or principal.id != principal_id:
                return self._deny_all(candidates, now, "SERVICE:unknown_principal")
            ids = list(dict.fromkeys(doc.document_id for doc in candidates))
            groups, grants, snapshots = await asyncio.gather(
                self.directory.groups_of(principal_id),
                self.grants.list_for_documents(ids),
                self.snapshots.get_many(ids),
            )
            principal = Principal.model_validate(
                {**principal.model_dump(warnings="error"), "groups": groups}
            )
            # A missing grant-store key is an incomplete read, not an empty grant list.
            hydrated = [
                DocumentAccessContext.model_validate(
                    {
                        **doc.model_dump(
                            exclude={"grants", "source_permissions"}, warnings="error"
                        ),
                        "grants": [g.model_dump(warnings="error") for g in grants[doc.document_id]],
                        "source_permissions": (
                            snapshots[doc.document_id].model_dump(warnings="error")
                            if doc.document_id in snapshots
                            else None
                        ),
                    }
                )
                for doc in candidates
            ]
            result = self.policy.filter(principal, hydrated, now=now)
        except Exception:
            return self._deny_all(candidates, now, "SERVICE:authority_unavailable")

        if self.verifier is None:
            return result
        failed: set[str] = set()
        allowed = set(result.allowed_ids)
        for index, doc in enumerate(hydrated):
            if doc.document_id not in allowed:
                continue
            try:
                verified = await self.verifier.verify(principal, doc, now=now)
            except Exception:
                verified = None
            if verified is not True:
                failed.add(doc.document_id)
                result.decisions[index] = self._denial(
                    doc,
                    now,
                    "LIVE:source_denied" if verified is False else "LIVE:unknown_permissions",
                    DenyReason.no_source_membership
                    if verified is False
                    else DenyReason.unknown_permissions,
                )
        result.allowed_ids = [doc_id for doc_id in result.allowed_ids if doc_id not in failed]
        return result

    def _denial(
        self,
        doc: DocumentAccessContext,
        now: datetime,
        rule: str,
        reason: DenyReason = DenyReason.unknown_permissions,
    ) -> AccessDecision:
        return AccessDecision(
            document_id=doc.document_id,
            decision=Effect.deny,
            reason=reason,
            matched_rule=rule,
            permission_version=doc.permission_version,
            policy_version=self.policy.policy_version,
            evaluated_at=now,
        )

    def _deny_all(
        self, docs: list[DocumentAccessContext], now: datetime, rule: str
    ) -> FilterResult:
        return FilterResult(
            allowed_ids=[], decisions=[self._denial(doc, now, rule) for doc in docs]
        )
