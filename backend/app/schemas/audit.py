"""Audit responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.domain import AuditEvent


class AuditVerify(BaseModel):
    ok: bool
    length: int
    head_hash: str | None = None
    first_broken_seq: int | None = None


class AuditEventDetail(AuditEvent):
    reconstruction: dict[str, Any] | None = None


class RevealRequest(BaseModel):
    """Why an auditor needs to see answer content they could not otherwise read."""

    reason: str = Field(min_length=10, max_length=500)
