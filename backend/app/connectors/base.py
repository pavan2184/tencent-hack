"""The connector contract.

A connector is bound to one `Source`. It is simultaneously a `freshness.ChangeSource`
(`list_changes`) and a `freshness.ProviderProbe` (`head`), and it fetches full objects for
ingestion (`fetch`) including their raw platform permissions (`permissions`). The freshness
library's `NormalizedChange` / `ChangePage` / `ProviderHead` types are reused verbatim.

`connector_kind` on emitted changes is the FRESHNESS kind of the source's platform
(`freshness.ConnectorKind(source.kind)`, e.g. `gdrive` -> `google_drive`), so freshness policies
are per platform; `kind` below is the connector implementation (`gbrain_import`, `upload`, ...).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from access_control import Classification, SourcePermissions
from freshness import ChangePage, ConnectorKind, EvidenceClass, NormalizedChange, ProviderHead
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.domain import Source


class FetchedObject(BaseModel):
    """One provider object, fetched for indexing."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    external_object_id: str
    markdown: str
    provider_version: str | None = None
    version_order: int | None = None
    modified_at: datetime | None = None
    content_hash: str | None = None
    permissions: SourcePermissions | None = None
    evidence_class: EvidenceClass = EvidenceClass.standard
    classification: Classification = Classification.internal
    owner_principal_id: str | None = None
    title: str
    slug: str
    page_type: str = "note"
    tags: list[str] = Field(default_factory=list)
    grants: list[dict[str, Any]] = Field(default_factory=list)
    permission_version: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Connector(Protocol):
    kind: str
    source: Source

    async def list_changes(self, cursor: str | None, *, limit: int = 100) -> ChangePage:
        """`freshness.ChangeSource`: one page of normalized changes from `cursor`."""
        ...

    async def fetch(self, external_object_id: str) -> FetchedObject:
        """Full object for indexing. Raises `KeyError` when the object does not exist."""
        ...

    async def head(self, external_object_id: str) -> ProviderHead:
        """`freshness.ProviderProbe`: current provider version. Transport failure raises
        `freshness.ProbeUnavailable`; never guesses."""
        ...

    async def permissions(self, external_object_id: str) -> SourcePermissions:
        """Current raw platform permissions of the object."""
        ...

    def normalize_webhook(self, body: dict[str, Any]) -> NormalizedChange:
        """Provider webhook body -> `NormalizedChange` (stubs raise `NotImplementedError`)."""
        ...


def freshness_kind(source: Source) -> ConnectorKind:
    """The freshness `ConnectorKind` for a source's platform (`gdrive` -> `google_drive`)."""
    return ConnectorKind(str(source.kind))
