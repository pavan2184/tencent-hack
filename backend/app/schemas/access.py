"""Grant and access-request request bodies."""

from __future__ import annotations

from access_control import Effect, SubjectType
from pydantic import BaseModel, ConfigDict, Field


class GrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    subject_type: SubjectType
    subject_id: str = Field(min_length=1)
    effect: Effect = Effect.allow
    scope: str = "read"
    reason: str | None = None


class GrantRevoke(BaseModel):
    reason: str | None = None
