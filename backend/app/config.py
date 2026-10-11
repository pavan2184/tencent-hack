"""Central typed configuration.

Every external key has a mock-safe blank default so the whole stack boots with no secrets.
Production fails loudly when a selected real provider has no credentials. Keep every
environment variable in `.env.example` in sync with this class.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Runtime ---
    ENV: Literal["development", "production", "test"] = "development"
    ROLE: Literal["api", "worker", "beat", "migrate", "seed"] = "api"
    PROVIDER_MODE: Literal["mock", "real"] = "mock"
    LOG_LEVEL: str = "info"
    # "sql" uses Postgres through SQLAlchemy; "memory" boots the API with in-process stores
    # (tests, quick local runs without a database).
    REPO_BACKEND: Literal["sql", "memory"] = "sql"

    # --- API ---
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:3000"
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # --- Database / Redis / Celery ---
    DATABASE_URL: str = "postgresql+psycopg://brain:brain@postgres:5432/brain"
    DB_POOL_SIZE: int = 5
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # --- Identity (demo personas; no auth) ---
    ACTOR_HEADER: str = "X-Actor-Id"

    # --- Models / providers (mock by default) ---
    LLM_PROVIDER: Literal["openai_compatible", "tencent_adp_app"] = "openai_compatible"
    LLM_BASE_URL: str = "https://api.lkeap.cloud.tencent.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-v3"
    LLM_TIMEOUT_S: float = 30.0
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = ""
    # ADP custom vector models are 1024-dimensional. Changing this requires `make reset`.
    EMBEDDING_DIM: int = 1024
    TENCENT_ADP_APP_KEY: str = ""
    TENCENT_ADP_CHAT_URL: str = "https://wss.lke.tencentcloud.com/adp/v2/chat"

    # --- Governed pipeline ---
    ASK_TOP_K: int = 8
    ASK_OVERFETCH_FACTOR: int = 4
    ASK_MAX_CONTEXT_CHARS: int = 12000
    GROUNDING_MIN_COVERAGE: float = 0.6
    FRESHNESS_LIVE_VERIFY_CRITICAL: bool = True
    DEFAULT_POLICY_ID: str = "default"

    # --- Upload & budget caps (placeholders; final numbers TBD by the user) ---
    UPLOAD_DIR: str = "/data/uploads"
    UPLOAD_ALLOWED_EXTENSIONS: str = "md,txt"
    UPLOAD_MAX_FILE_BYTES: int = 1_000_000
    UPLOAD_MAX_FILES_TOTAL: int = 200
    UPLOAD_MAX_FILES_PER_ACTOR_PER_DAY: int = 20
    EMBEDDING_DAILY_CALL_BUDGET: int = 2000

    # --- Sync / workers ---
    SYNC_DELTA_INTERVAL_S: int = 60
    SYNC_RECONCILE_INTERVAL_S: int = 600
    WATCHDOG_INTERVAL_S: int = 60
    TASK_MAX_RETRIES: int = 3

    # --- Seed ---
    SEED_DIR: str = "/app/seed"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def upload_allowed_extensions(self) -> set[str]:
        return {e.strip().lower().lstrip(".") for e in self.UPLOAD_ALLOWED_EXTENSIONS.split(",")}

    @property
    def is_mock(self) -> bool:
        return self.PROVIDER_MODE == "mock"

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        for name in (
            "UPLOAD_MAX_FILE_BYTES",
            "UPLOAD_MAX_FILES_TOTAL",
            "UPLOAD_MAX_FILES_PER_ACTOR_PER_DAY",
            "EMBEDDING_DAILY_CALL_BUDGET",
            "EMBEDDING_DIM",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.PROVIDER_MODE == "real":
            missing: list[str] = []
            if self.LLM_PROVIDER == "openai_compatible" and not self.LLM_API_KEY:
                missing.append("LLM_API_KEY")
            if self.LLM_PROVIDER == "tencent_adp_app" and not self.TENCENT_ADP_APP_KEY:
                missing.append("TENCENT_ADP_APP_KEY")
            for name in ("EMBEDDING_BASE_URL", "EMBEDDING_MODEL"):
                if not getattr(self, name):
                    missing.append(name)
            if missing:
                raise ValueError(
                    "PROVIDER_MODE=real but required settings are blank: " + ", ".join(missing)
                )
        if self.ENV == "production" and self.REPO_BACKEND != "sql":
            raise ValueError("REPO_BACKEND must be 'sql' in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
