"""Shared response shapes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Items[T](BaseModel):
    """List endpoints answer `{"items": [...]}`."""

    items: list[T] = Field(default_factory=list)


class Message(BaseModel):
    status: str
    detail: dict[str, Any] | None = None
