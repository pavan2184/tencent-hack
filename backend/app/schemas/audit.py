"""Audit responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.schemas.domain import AuditEvent


class AuditVerify(BaseModel):
    ok: bool
    length: int
    head_hash: str | None = None
    first_broken_seq: int | None = None


class AuditEventDetail(AuditEvent):
    reconstruction: dict[str, Any] | None = None
