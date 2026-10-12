"""Typed stubs for the platform connectors that are not built yet (owner: Pavan).

Each satisfies the `Connector` protocol shape and raises `NotImplementedError` from every
provider call, so a stub source can be registered and shown, while syncs/webhooks answer
`501 not_implemented` and live verification reports `unknown` (never fresh).
"""

from __future__ import annotations

from typing import Any

from access_control import SourcePermissions
from freshness import ChangePage, NormalizedChange, ProbeUnavailable, ProviderHead

from app.connectors.base import FetchedObject
from app.schemas.domain import Source


class StubConnector:
    kind = "stub"

    def __init__(self, source: Source) -> None:
        self.source = source

    def _stub(self) -> NotImplementedError:
        return NotImplementedError(f"{self.kind} connector is a stub — owner: Pavan")

    async def list_changes(self, cursor: str | None, *, limit: int = 100) -> ChangePage:
        raise self._stub()

    async def fetch(self, external_object_id: str) -> FetchedObject:
        raise self._stub()

    async def head(self, external_object_id: str) -> ProviderHead:
        # A probe must never guess: a missing implementation is "provider unavailable".
        raise ProbeUnavailable(str(self._stub()))

    async def permissions(self, external_object_id: str) -> SourcePermissions:
        raise self._stub()

    def normalize_webhook(self, body: dict[str, Any]) -> NormalizedChange:
        raise self._stub()


class SlackConnector(StubConnector):
    kind = "slack"


class EmailConnector(StubConnector):
    kind = "email"


class ConfluenceConnector(StubConnector):
    kind = "confluence"


class JiraConnector(StubConnector):
    kind = "jira"


class GDriveConnector(StubConnector):
    kind = "gdrive"


class McpExternalConnector(StubConnector):
    kind = "mcp_external"


STUBS: dict[str, type[StubConnector]] = {
    cls.kind: cls
    for cls in (
        SlackConnector,
        EmailConnector,
        ConfluenceConnector,
        JiraConnector,
        GDriveConnector,
        McpExternalConnector,
    )
}
STUBS["google_drive"] = GDriveConnector
