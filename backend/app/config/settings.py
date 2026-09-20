"""Application configuration, loaded from the environment.

All secrets come from environment variables (or a local ``.env`` file that is
never committed).  See ``.env.example`` for the full list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config/settings.py -> backend/app/config -> backend/app -> backend
BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent

#: Local development database. Absolute, so the same file is found from any
#: working directory — a relative URL creates one database per directory,
#: which looks exactly like data loss.
LOCAL_SQLITE_URL = f"sqlite:///{BACKEND_ROOT / 'rivalradar.db'}"


def normalise_database_url(url: str) -> str:
    """Return a SQLAlchemy URL with an explicit, installed driver.

    Managed Postgres providers hand out URLs in shapes SQLAlchemy 2 will not
    accept or will resolve to a driver this project does not ship:

      * Supabase and Heroku still emit the legacy ``postgres://`` scheme,
        which SQLAlchemy removed support for.
      * A bare ``postgresql://`` defaults to psycopg2; this project installs
        psycopg 3, so the driver is pinned explicitly.

    A URL that already names a driver (``postgresql+asyncpg://``) is left
    alone, as is anything that is not Postgres.
    """
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    """Runtime settings for the RivalRadar backend."""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General -----------------------------------------------------------
    app_name: str = "RivalRadar"
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # --- Database ----------------------------------------------------------
    # Empty means "decide from the environment": SQLite locally, and a hard
    # failure in production rather than a silent local file nobody can reach.
    # Resolved in _resolve_database_url below, so by the time anything reads
    # this attribute it is always a complete, driver-qualified URL.
    database_url: str = ""

    # --- Demo mode ---------------------------------------------------------
    # OFF by default: the application tracks real competitors the user adds.
    # Demo data is only ever loaded when this is explicitly enabled.
    demo_mode: bool = False

    # --- LLM ---------------------------------------------------------------
    # openrouter | deterministic | openai | auto
    #   openrouter    - OpenRouter's OpenAI-compatible API (free tier friendly)
    #   deterministic - no network, rule-based analysis only
    #   auto          - OpenRouter if a key is set, else deterministic
    llm_provider: str = "openrouter"
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # Hard ceiling on LLM calls per scan. Free models are rate limited, so the
    # pipeline only ever analyses the top-scoring candidate changes.
    llm_max_calls_per_scan: int = 8
    # Candidate changes below this relevance never reach the model.
    llm_min_relevance: float = 40.0
    # Completion token budget. Many free models emit a long hidden "reasoning"
    # block that is billed against this budget before any content appears, so a
    # tight limit shows up as finish_reason='length' with empty content.
    # 2000 leaves room for that; the JSON answer itself needs only ~250.
    llm_max_tokens: int = 2000

    # --- OpenRouter (free tier) --------------------------------------------
    openrouter_api_key: str | None = None
    openrouter_model: str = "openrouter/free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter uses these for attribution on its dashboard; both optional.
    openrouter_site_url: str | None = None
    openrouter_app_name: str = "RivalRadar"

    # --- OpenAI (optional, paid; not required) ------------------------------
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"

    # --- Scraping ----------------------------------------------------------
    scan_user_agent: str = (
        "RivalRadar/1.0 (+https://github.com/yourname/rivalradar; competitive-intelligence bot)"
    )
    request_timeout_seconds: float = 20.0
    request_max_retries: int = 3
    request_delay_seconds: float = 1.5
    max_response_bytes: int = 5_000_000
    respect_robots_txt: bool = True
    allow_private_networks: bool = False
    playwright_enabled: bool = False

    # --- Scheduler ---------------------------------------------------------
    scheduler_enabled: bool = False
    scheduler_interval_minutes: int = 360

    # --- Wayback -----------------------------------------------------------
    wayback_cdx_url: str = "https://web.archive.org/cdx/search/cdx"
    wayback_timeout_seconds: float = 45.0

    # --- Paths -------------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"

    # --- CORS --------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @field_validator("data_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: object) -> Path:
        return Path(str(value))

    @model_validator(mode="after")
    def _resolve_database_url(self) -> Settings:
        """Pick the database, or refuse to start.

        A production deployment that quietly falls back to SQLite on the
        container filesystem looks healthy and loses every record on the next
        restart. That failure is silent and total, so it is turned into a
        startup error instead.
        """
        url = self.database_url.strip()
        if not url:
            if self.is_production:
                raise ValueError(
                    "Production DATABASE_URL is required. Set DATABASE_URL to your "
                    "PostgreSQL connection string (for example the Supabase pooler "
                    "URL) before starting with ENVIRONMENT=production."
                )
            url = LOCAL_SQLITE_URL
        self.database_url = normalise_database_url(url)
        return self

    @model_validator(mode="after")
    def _guard_production_cors(self) -> Settings:
        """A wildcard origin in production would expose the API to any site."""
        if self.is_production and "*" in self.cors_origin_list:
            raise ValueError(
                "CORS_ORIGINS must not contain '*' in production. List the exact "
                "front-end origins, comma separated."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def database_backend(self) -> str:
        """Driver family only — never the URL, which carries credentials."""
        scheme = self.database_url.split("://", 1)[0]
        return scheme.split("+", 1)[0] or "unknown"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def ensure_directories(self) -> None:
        """Create the on-disk data directories if they do not exist yet."""
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


settings = get_settings()
