"""Grant and access-request request bodies, and the access-map response."""

from __future__ import annotations

from datetime import datetime

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


# ---------------------------------------------------------------------------- access map
class AccessMapPrincipal(BaseModel):
    id: str
    display_name: str
    roles: list[str]
    groups: list[str]


class AccessMapGroup(BaseModel):
    id: str
    name: str


class AccessMapSource(BaseModel):
    id: str
    name: str
    kind: str


class AccessMapDocument(BaseModel):
    """A document the caller can read. The permission times come from the caller's own decision:
    when its source permissions were last synced, and when that sync stops counting (after which
    the document is denied to everyone, and drops off the map, until the next sync). Both are
    null for uploads, whose permissions are managed locally."""

    id: str
    title: str
    slug: str
    source_id: str
    source_kind: str
    classification: str
    permissions_synced_at: datetime | None = None
    permissions_expire_at: datetime | None = None


class AccessMapGrantRef(BaseModel):
    """The active allow grant behind an `R5:explicit_grant` edge."""

    grant_id: str
    subject_type: SubjectType
    subject_id: str


class AccessMapEdge(BaseModel):
    """One ALLOW decision. Denied pairs are never serialised; a missing edge means no access."""

    principal_id: str
    document_id: str
    rule: str
    via: list[AccessMapGrantRef] = Field(default_factory=list)


class AccessMap(BaseModel):
    policy_version: str
    generated_at: datetime
    principals: list[AccessMapPrincipal]
    groups: list[AccessMapGroup]
    sources: list[AccessMapSource]
    documents: list[AccessMapDocument]
    edges: list[AccessMapEdge]
