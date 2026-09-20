"""FastAPI application entry point.

Run with::

    uvicorn app.main:app --reload --port 8000

Interactive docs are served at ``/docs``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_error_handlers
from app.api.routes import changes, competitors, evaluation
from app.config.logging import configure_logging, get_logger
from app.config.settings import settings
from app.database.session import database_healthy, init_db
from app.llm.factory import describe_analyst, get_provider
from app.scheduler.jobs import shutdown_scheduler, start_scheduler

configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create tables and start the scheduler on boot; clean up on shutdown."""
    settings.ensure_directories()
    init_db()
    provider = get_provider()
    logger.info(
        "%s v%s starting (env=%s, llm=%s/%s)",
        settings.app_name,
        __version__,
        settings.environment,
        provider.name,
        provider.model,
    )
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        logger.info("%s shutting down", settings.app_name)


app = FastAPI(
    title="RivalRadar API",
    version=__version__,
    description=(
        "AI-powered competitor intelligence. Turns raw website diffs into "
        "ranked, explained competitive signals."
    ),
    lifespan=lifespan,
    # FastAPI's default 422 body echoes the submitted payload. The custom
    # validation handler replaces it with a flat sentence, so nothing a client
    # sent is reflected back verbatim.
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:  # noqa: ANN001
    """Baseline hardening for a JSON API served cross-origin.

    This API returns JSON and never renders HTML, so the useful headers are
    the ones that stop a browser from treating a response as something else.
    HSTS is only set in production, where TLS is terminated by the platform —
    sending it over plain http://localhost would pin the browser to https for
    the whole origin and break local development.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(competitors.router)
app.include_router(changes.router)
app.include_router(evaluation.router)


def _health_payload() -> dict:
    """Operational summary.

    Everything here is non-secret by construction. In particular the database
    is reported by *driver family* only: the URL itself carries the Supabase
    username and password, and an earlier version of this endpoint published
    it — ``url.split("///")[-1]`` returns the whole string for a
    ``postgresql://user:pass@host/db`` URL, because there is no ``///`` in it.
    """
    analyst = describe_analyst()
    connected = database_healthy()
    return {
        "status": "ok" if connected else "degraded",
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        "database": {
            "backend": settings.database_backend,
            "connected": connected,
        },
        "llm_provider": analyst["provider"],
        "llm_model": analyst["model"],
        "llm_is_llm": analyst["is_llm"],
        "demo_mode": settings.demo_mode,
        "scheduler_enabled": settings.scheduler_enabled,
    }


@app.get("/health", tags=["system"])
def health() -> dict:
    """Platform health probe. Render polls this to decide if the service is up."""
    return _health_payload()


@app.get("/api/health", tags=["system"])
def api_health() -> dict:
    """Same payload under the /api prefix, which is what the frontend calls."""
    return _health_payload()


@app.get("/", tags=["system"])
def root() -> dict:
    """Service banner."""
    return {
        "name": "RivalRadar",
        "description": "AI competitor tracking agent",
        "docs": "/docs",
        "health": "/health",
    }
