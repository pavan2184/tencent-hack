# syntax=docker/dockerfile:1
# One backend image for every role: ROLE=api|worker|beat|migrate|seed (see entrypoint.sh).
# Build context is ./backend. Migrations (infra/postgres/migrations) are NOT in the context:
# compose mounts them read-only at /app/migrations and sets MIGRATIONS_DIR.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    ROLE=api \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    LOG_LEVEL=info \
    SEED_DIR=/app/seed \
    UPLOAD_DIR=/data/uploads \
    MIGRATIONS_DIR=/app/migrations

# curl for the compose api healthcheck (it falls back to python urllib if curl is absent).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Phase 1: third-party dependencies only (cached until the lockfile or a pyproject changes).
# The workspace members' pyproject.toml files must be present for the lock to resolve.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=libs/groundedness/pyproject.toml,target=libs/groundedness/pyproject.toml \
    --mount=type=bind,source=libs/freshness/pyproject.toml,target=libs/freshness/pyproject.toml \
    --mount=type=bind,source=libs/access_control/pyproject.toml,target=libs/access_control/pyproject.toml \
    uv sync --locked --all-packages --no-install-project --no-install-workspace

# Phase 2: the app and the three workspace libraries.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --all-packages \
    && chmod +x /app/entrypoint.sh

# Non-root runtime user; /data/uploads is pre-created so the named volume inherits ownership.
RUN groupadd --gid 10001 brain \
    && useradd --uid 10001 --gid brain --no-create-home --home-dir /app --shell /usr/sbin/nologin brain \
    && mkdir -p /data/uploads /app/migrations \
    && chown -R brain:brain /data
USER brain

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
