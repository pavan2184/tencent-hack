"""`get_connector(source)`: the connector implementation for a source.

Resolution: `source.config["connector"]` if set; else `upload` for upload sources; else
`gbrain_import` when the source has a `local_path`; else the platform stub for `source.kind`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.connectors.base import Connector
from app.connectors.gbrain_import import GbrainImportConnector
from app.connectors.stubs import STUBS, StubConnector
from app.connectors.upload import UploadConnector
from app.schemas.domain import Source

if TYPE_CHECKING:
    from app.services.wiring import Services


def connector_name(source: Source) -> str:
    configured = (source.config or {}).get("connector")
    if configured:
        return str(configured)
    if str(source.kind) == "upload":
        return "upload"
    if source.local_path:
        return "gbrain_import"
    return str(source.kind)


def is_stub(source: Source) -> bool:
    return connector_name(source) not in ("gbrain_import", "upload")


def get_connector(source: Source, services: Services | None = None) -> Connector:
    name = connector_name(source)
    clock = services.clock if services is not None else None
    if name == "gbrain_import":
        return GbrainImportConnector(source, clock=clock)
    if name == "upload":
        return UploadConnector(source, services, clock=clock)
    stub = STUBS.get(name, StubConnector)
    return stub(source)
