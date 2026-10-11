"""Request-scoped correlation fields carried through API -> services -> tasks via ContextVars."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
actor_id_var: ContextVar[str | None] = ContextVar("actor_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def get_request_id() -> str | None:
    return request_id_var.get()


def get_actor_id() -> str | None:
    return actor_id_var.get()
