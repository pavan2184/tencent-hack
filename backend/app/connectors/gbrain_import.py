"""`gbrain_import` connector: a directory of gbrain pages (`**/*.md` with YAML frontmatter).

Real (no network): walks `source.local_path`, one page per file (README.md files are skipped).
Frontmatter fields follow `backend/seed/corpus/README.md`; `permissions:` becomes a raw
`SourcePermissions` snapshot, `grants:` are returned for the ingester to store. The demo-only
`simulate: {live_version, deleted, indexed_at}` block is honoured: `head()` reports
`live_version`/`deleted` as the provider truth, and `indexed_at` is passed through in
`FetchedObject.raw["simulate"]` for the ingester to backdate the index time.

Paging: the cursor is a decimal offset into the sorted listing; the final page returns cursor
`"0"` so the next delta run re-lists from the start (versions make re-listing idempotent).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter
from access_control import Classification, SourcePermissions
from freshness import (
    ChangeKind,
    ChangePage,
    Clock,
    EvidenceClass,
    NormalizedChange,
    ProbeUnavailable,
    ProviderHead,
    SystemClock,
)

from app.connectors.base import FetchedObject, freshness_kind
from app.schemas.domain import Source


def parse_datetime(value: Any) -> datetime | None:
    """ISO string / datetime / date -> aware UTC datetime (naive values are taken as UTC)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class _Entry:
    path: Path
    rel: str
    text: str
    meta: dict[str, Any]
    content_hash: str

    @property
    def slug(self) -> str:
        return str(self.meta.get("slug") or self.rel.removesuffix(".md")).strip("/")

    @property
    def external_object_id(self) -> str:
        return str(self.meta.get("external_object_id") or self.slug)

    @property
    def simulate(self) -> dict[str, Any]:
        sim = self.meta.get("simulate")
        return sim if isinstance(sim, dict) else {}


class GbrainImportConnector:
    kind = "gbrain_import"

    def __init__(self, source: Source, *, clock: Clock | None = None) -> None:
        local_path = source.local_path or (source.config or {}).get("local_path")
        if not local_path:
            raise ValueError(f"source {source.id!r} has no local_path (gbrain_import connector)")
        self.source = source
        self.root = Path(str(local_path))
        self.clock: Clock = clock or SystemClock()
        self._entries: dict[str, _Entry] | None = None

    # ---------------------------------------------------------------- scanning
    def _scan(self) -> dict[str, _Entry]:
        if self._entries is not None:
            return self._entries
        entries: dict[str, _Entry] = {}
        if self.root.is_dir():
            for path in sorted(self.root.rglob("*.md")):
                if path.name.lower() == "readme.md" or not path.is_file():
                    continue
                raw = path.read_bytes()
                text = raw.decode("utf-8")
                post = frontmatter.loads(text)
                entry = _Entry(
                    path=path,
                    rel=path.relative_to(self.root).as_posix(),
                    text=text,
                    meta=dict(post.metadata),
                    content_hash=hashlib.sha256(raw).hexdigest(),
                )
                entries[entry.external_object_id] = entry
        self._entries = entries
        return entries

    def _entry(self, external_object_id: str) -> _Entry:
        entry = self._scan().get(external_object_id)
        if entry is None:
            raise KeyError(external_object_id)
        return entry

    # ---------------------------------------------------------------- ChangeSource
    def _change(self, entry: _Entry, now: datetime) -> NormalizedChange:
        meta = entry.meta
        return NormalizedChange.model_validate(
            {
                "source_id": self.source.id,
                "connector_kind": freshness_kind(self.source),
                "provider_event_id": "",
                "external_object_id": entry.external_object_id,
                "change_kind": ChangeKind.upsert,
                "provider_version": _opt_str(meta.get("provider_version")),
                "version_order": _opt_int(meta.get("version_order")),
                "provider_modified_at": parse_datetime(meta.get("provider_modified_at")),
                "observed_at": now,
                "content_hash": entry.content_hash,
            }
        )

    async def list_changes(self, cursor: str | None, *, limit: int = 100) -> ChangePage:
        entries = list(self._scan().values())
        try:
            offset = max(0, int(cursor)) if cursor else 0
        except ValueError:
            offset = 0
        now = self.clock.now()
        page = entries[offset : offset + limit]
        has_more = offset + limit < len(entries)
        return ChangePage(
            changes=[self._change(e, now) for e in page],
            next_cursor=str(offset + limit) if has_more else "0",
            has_more=has_more,
        )

    # ---------------------------------------------------------------- fetch / head
    def _permissions(self, entry: _Entry) -> SourcePermissions | None:
        raw = entry.meta.get("permissions")
        if not isinstance(raw, dict):
            return None
        return SourcePermissions.from_raw(
            raw,
            permission_version=str(entry.meta.get("permission_version") or "v1"),
            captured_at=self.clock.now(),
        )

    async def fetch(self, external_object_id: str) -> FetchedObject:
        entry = self._entry(external_object_id)
        meta = entry.meta
        tags = meta.get("tags") or []
        grants = meta.get("grants") or []
        return FetchedObject(
            external_object_id=entry.external_object_id,
            markdown=entry.text,
            provider_version=_opt_str(meta.get("provider_version")),
            version_order=_opt_int(meta.get("version_order")),
            modified_at=parse_datetime(meta.get("provider_modified_at")),
            content_hash=entry.content_hash,
            permissions=self._permissions(entry),
            evidence_class=EvidenceClass(str(meta.get("evidence_class") or "standard")),
            classification=Classification(str(meta.get("classification") or "internal")),
            owner_principal_id=_opt_str(meta.get("owner")),
            title=str(meta.get("title") or entry.slug),
            slug=entry.slug,
            page_type=str(meta.get("type") or "note"),
            tags=[str(t) for t in tags] if isinstance(tags, list) else [],
            grants=[g for g in grants if isinstance(g, dict)] if isinstance(grants, list) else [],
            permission_version=_opt_str(meta.get("permission_version")),
            raw={"path": entry.rel, "frontmatter": meta, "simulate": entry.simulate},
        )

    async def head(self, external_object_id: str) -> ProviderHead:
        self._entries = None  # always re-read: a probe reports the provider's current truth
        try:
            entries = self._scan()
        except (OSError, UnicodeDecodeError) as exc:
            raise ProbeUnavailable(f"gbrain_import: cannot read {self.root}: {exc}") from exc
        entry = entries.get(external_object_id)
        if entry is None:
            return ProviderHead(deleted=True)
        sim = entry.simulate
        if sim.get("deleted"):
            return ProviderHead(deleted=True)
        version = _opt_str(entry.meta.get("provider_version"))
        order = _opt_int(entry.meta.get("version_order"))
        content_hash: str | None = entry.content_hash
        if sim.get("live_version") is not None:
            version = str(sim["live_version"])
            order = _opt_int(version) if order is not None else None
            content_hash = None  # the simulated live revision's content is unknown
        return ProviderHead(
            provider_version=version,
            version_order=order,
            modified_at=parse_datetime(entry.meta.get("provider_modified_at")),
            deleted=False,
            content_hash=content_hash,
        )

    async def permissions(self, external_object_id: str) -> SourcePermissions:
        perms = self._permissions(self._entry(external_object_id))
        if perms is None:
            raise KeyError(f"{external_object_id}: no permissions in frontmatter")
        return perms

    # ---------------------------------------------------------------- webhooks
    def normalize_webhook(self, body: dict[str, Any]) -> NormalizedChange:
        """Generic normalized-change body (see docs/API_CONTRACT.md, webhooks)."""
        if not body.get("external_object_id"):
            raise ValueError("external_object_id is required")
        observed = parse_datetime(body.get("observed_at")) or self.clock.now()
        return NormalizedChange.model_validate(
            {
                "source_id": self.source.id,
                "scope_key": str(body.get("scope_key") or "default"),
                "connector_kind": freshness_kind(self.source),
                "provider_event_id": str(body.get("provider_event_id") or ""),
                "external_object_id": str(body["external_object_id"]),
                "change_kind": ChangeKind(str(body.get("change_kind") or "upsert")),
                "provider_version": _opt_str(body.get("provider_version")),
                "version_order": _opt_int(body.get("version_order")),
                "provider_modified_at": parse_datetime(body.get("provider_modified_at")),
                "observed_at": observed,
                "content_hash": _opt_str(body.get("content_hash")),
            }
        )
