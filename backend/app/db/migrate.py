"""SQL-file migration runner (what `ROLE=migrate` runs): `python -m app.db.migrate`.

- Synchronous psycopg v3 (the app itself uses the async driver through SQLAlchemy).
- Applies `infra/postgres/migrations/*.sql` in filename order, each file in ONE transaction,
  skipping files already recorded in `schema_migrations` (filename, applied_at, sha256 checksum).
- `__EMBEDDING_DIMS__` is substituted with `settings.EMBEDDING_DIM` before execution.
- Ensures the extensions from `infra/postgres/init/01_extensions.sql` exist first, so a database
  not created by compose (CI, a managed Postgres, a throwaway container) works too.
- Serialises concurrent runners with a session advisory lock.
- Prints one line per file: `applied <file>` or `skipped <file>`.

Migrations directory: `settings.MIGRATIONS_DIR`, else the `MIGRATIONS_DIR` env var, else found by
walking up from this file to the first `infra/postgres/migrations` (repo checkout, or `/app/infra/…`
in the image). Never edit an applied file — add a new numbered one (checksum drift is reported).
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

import psycopg

from app.config import settings

__all__ = [
    "REQUIRED_EXTENSIONS",
    "find_migrations_dir",
    "main",
    "run_migrations",
    "to_psycopg_dsn",
]

REQUIRED_EXTENSIONS = ("vector", "pg_trgm", "pgcrypto")
DIMS_PLACEHOLDER = "__EMBEDDING_DIMS__"
_LOCK_KEY = "schema_migrations"

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum   TEXT        NOT NULL
)
"""


def to_psycopg_dsn(url: str) -> str:
    """`postgresql+psycopg://…` (SQLAlchemy URL) → `postgresql://…` (libpq DSN)."""
    return re.sub(r"^postgres(?:ql)?(?:\+[a-z0-9_]+)?://", "postgresql://", url.strip())


def find_migrations_dir(start: Path | None = None) -> Path:
    """Resolve the migrations directory (settings → env → walk up to `infra/`)."""
    configured = settings.MIGRATIONS_DIR or os.environ.get("MIGRATIONS_DIR", "")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"MIGRATIONS_DIR={configured!r} is not a directory")
        return path
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / "infra" / "postgres" / "migrations"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "could not find infra/postgres/migrations above "
        f"{here}; set MIGRATIONS_DIR to the directory holding the *.sql files"
    )


def _extensions_sql(migrations_dir: Path) -> str:
    init_file = migrations_dir.parent / "init" / "01_extensions.sql"
    if init_file.is_file():
        return init_file.read_text(encoding="utf-8")
    return "\n".join(f"CREATE EXTENSION IF NOT EXISTS {ext};" for ext in REQUIRED_EXTENSIONS)


def _ensure_extensions(conn: psycopg.Connection, migrations_dir: Path) -> None:
    present = {
        row[0]
        for row in conn.execute(
            "SELECT extname FROM pg_extension WHERE extname = ANY(%s)", [list(REQUIRED_EXTENSIONS)]
        ).fetchall()
    }
    if set(REQUIRED_EXTENSIONS) <= present:
        return
    with conn.transaction():
        conn.execute(_extensions_sql(migrations_dir))  # type: ignore[arg-type]


def run_migrations(
    dsn: str | None = None,
    *,
    migrations_dir: Path | None = None,
    embedding_dim: int | None = None,
    out: Callable[[str], None] = print,
) -> list[tuple[str, str]]:
    """Apply pending migrations; return `[(filename, "applied"|"skipped"), …]` in order."""
    directory = migrations_dir or find_migrations_dir()
    dims = int(embedding_dim if embedding_dim is not None else settings.EMBEDDING_DIM)
    files = sorted(p for p in directory.glob("*.sql") if p.is_file())
    results: list[tuple[str, str]] = []

    with psycopg.connect(to_psycopg_dsn(dsn or settings.DATABASE_URL), autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext(%s))", [_LOCK_KEY])
        try:
            _ensure_extensions(conn, directory)
            conn.execute(_LEDGER_DDL)  # type: ignore[arg-type]
            applied = {
                row[0]: row[1]
                for row in conn.execute("SELECT filename, checksum FROM schema_migrations")
            }
            for path in files:
                raw = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                if path.name in applied:
                    if applied[path.name] != checksum:
                        print(
                            f"warning: {path.name} changed after it was applied "
                            "(never edit an applied migration; add a new file)",
                            file=sys.stderr,
                        )
                    results.append((path.name, "skipped"))
                    out(f"skipped {path.name}")
                    continue
                sql = raw.replace(DIMS_PLACEHOLDER, str(dims))
                with conn.transaction():
                    conn.execute(sql)  # type: ignore[arg-type]  # no params: '%' is literal
                    conn.execute(
                        "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                        [path.name, checksum],
                    )
                results.append((path.name, "applied"))
                out(f"applied {path.name}")
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", [_LOCK_KEY])
    return results


def main(argv: list[str] | None = None) -> int:
    try:
        run_migrations()
    except (psycopg.Error, FileNotFoundError) as exc:
        print(f"migration failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
