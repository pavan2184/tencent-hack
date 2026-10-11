"""The `Services` container: one object graph shared by REST, MCP, Celery tasks and the seed.

`build_services()` picks implementations from settings:
- `REPO_BACKEND=memory`: `InMemoryRepo` + the libraries' in-memory stores (tests, quick runs).
- `REPO_BACKEND=sql`: `SqlRepo` + the SQL adapters in `app/adapters/` (imported lazily).
Providers come from `app.providers.factory` (`PROVIDER_MODE=mock|real`).

`get_services()` / `set_services()` hold the process singleton; FastAPI dependencies, MCP tools
and tasks call `get_services()`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from access_control import (
    AccessPolicy,
    AccessRequestStore,
    DefaultAccessPolicy,
    GrantStore,
    InMemoryAccessRequestStore,
    InMemoryGrantStore,
    InMemoryPermissionSnapshotStore,
    PermissionSnapshotStore,
    Principal,
    PrincipalDirectory,
)
from freshness import Clock, FreshnessService, FreshnessStore, InMemoryFreshnessStore, SystemClock
from groundedness import (
    AbstentionPolicy,
    AnswerComposer,
    DefaultAbstentionPolicy,
    EvidenceSanitizer,
    ExtractiveComposer,
    LexicalOverlapVerifier,
    LLMComposer,
    LLMPort,
    RegexInjectionSanitizer,
    SupportVerifier,
)

from app.adapters.llm_port import ChatProviderLLMPort
from app.config import Settings, get_settings
from app.db.repo import Repo
from app.providers.base import ChatProvider, EmbeddingProvider
from app.providers.factory import get_chat_provider, get_embedding_provider


@dataclass
class Services:
    settings: Settings
    repo: Repo
    clock: Clock
    freshness: FreshnessService
    freshness_store: FreshnessStore
    access_policy: AccessPolicy
    grant_store: GrantStore
    permission_store: PermissionSnapshotStore
    principal_directory: PrincipalDirectory
    access_request_store: AccessRequestStore
    chat: ChatProvider
    embedder: EmbeddingProvider
    sanitizer: EvidenceSanitizer
    composer: AnswerComposer
    verifier: SupportVerifier
    abstention: AbstentionPolicy
    llm_port: LLMPort | None


class RepoPrincipalDirectory:
    """`access_control.PrincipalDirectory` backed by the app `Repo` (memory mode)."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo

    async def get(self, principal_id: str) -> Principal | None:
        return await self.repo.get_principal(principal_id)

    async def list(self) -> Sequence[Principal]:  # type: ignore[override]
        return await self.repo.list_principals()

    async def groups_of(self, principal_id: str) -> list[str]:
        principal = await self.repo.get_principal(principal_id)
        return list(principal.groups) if principal is not None else []


def _sql_stores() -> tuple[Repo, FreshnessStore, GrantStore, PermissionSnapshotStore, Any, Any]:
    try:
        from app.adapters.access_stores import (
            SqlAccessRequestStore,
            SqlGrantStore,
            SqlPermissionSnapshotStore,
            SqlPrincipalDirectory,
        )
        from app.adapters.freshness_store import SqlFreshnessStore
        from app.db.repo_sql import SqlRepo
        from app.db.session import async_session_factory
    except ImportError as exc:
        raise RuntimeError(
            f"REPO_BACKEND=sql but a SQL module is missing or broken: {exc}. "
            "Expected app.db.repo_sql.SqlRepo, app.db.session.async_session_factory, "
            "app.adapters.freshness_store.SqlFreshnessStore and app.adapters.access_stores."
            "{SqlGrantStore, SqlPermissionSnapshotStore, SqlPrincipalDirectory, "
            "SqlAccessRequestStore}. Use REPO_BACKEND=memory to run without Postgres."
        ) from exc
    sf = async_session_factory
    return (
        SqlRepo(sf),
        SqlFreshnessStore(sf),
        SqlGrantStore(sf),
        SqlPermissionSnapshotStore(sf),
        SqlPrincipalDirectory(sf),
        SqlAccessRequestStore(sf),
    )


def build_services(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    chat: ChatProvider | None = None,
    embedder: EmbeddingProvider | None = None,
) -> Services:
    settings = settings or get_settings()
    clock = clock or SystemClock()
    if settings.REPO_BACKEND == "sql":
        repo, freshness_store, grants, perms, directory, requests = _sql_stores()
    else:
        from app.db.repo_memory import InMemoryRepo

        repo = InMemoryRepo()
        freshness_store = InMemoryFreshnessStore()
        grants = InMemoryGrantStore()
        perms = InMemoryPermissionSnapshotStore()
        directory = RepoPrincipalDirectory(repo)
        requests = InMemoryAccessRequestStore()

    chat = chat or get_chat_provider(settings)
    embedder = embedder or get_embedding_provider(settings)
    llm_port: LLMPort | None = ChatProviderLLMPort(chat)
    composer: AnswerComposer
    if settings.is_mock:
        # Deterministic offline answers; the LLM port is wired but the extractive composer
        # never calls it.
        composer = ExtractiveComposer()
    else:
        composer = LLMComposer(llm_port, fallback="extractive", on_provider_error="raise")

    return Services(
        settings=settings,
        repo=repo,
        clock=clock,
        freshness=FreshnessService(freshness_store, clock),
        freshness_store=freshness_store,
        access_policy=DefaultAccessPolicy(),
        grant_store=grants,
        permission_store=perms,
        principal_directory=directory,
        access_request_store=requests,
        chat=chat,
        embedder=embedder,
        sanitizer=RegexInjectionSanitizer(),
        composer=composer,
        verifier=LexicalOverlapVerifier(),
        abstention=DefaultAbstentionPolicy(),
        llm_port=llm_port,
    )


_services: Services | None = None


def get_services() -> Services:
    """The process singleton, built from settings on first use."""
    global _services
    if _services is None:
        _services = build_services()
    return _services


def set_services(services: Services | None) -> None:
    """Install (or clear with None) the process singleton (tests, lifespan, worker init)."""
    global _services
    _services = services


def current_services() -> Services | None:
    """The installed singleton without building one."""
    return _services
