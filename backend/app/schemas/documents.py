"""Document request bodies (responses are built in `services/documents.py`)."""

from __future__ import annotations

from datetime import date

from access_control import Classification
from pydantic import BaseModel, ConfigDict, Field


class ClassificationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Classification
    reason: str | None = Field(default=None, max_length=1000)


class TimelineEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    summary: str = Field(min_length=1, max_length=2000)
    source: str = Field(default="", max_length=200)
    detail: str = Field(default="", max_length=10_000)


class AccessRequestCreate(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
