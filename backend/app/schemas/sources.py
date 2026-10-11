"""Source request bodies and the public source shape."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from access_control import SourceKind
from pydantic import BaseModel, ConfigDict, Field


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=200)
    kind: SourceKind
    description: str = ""
    local_path: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class SyncRequest(BaseModel):
    trigger_kind: Literal["delta", "reconcile"] = "reconcile"


class SourceOut(BaseModel):
    id: str
    name: str
    kind: str
    description: str = ""
    connector: str
    last_sync_at: datetime | None = None
    newest_content_at: datetime | None = None
    archived: bool = False
