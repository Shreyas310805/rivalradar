"""Uniform error handling.

Every error leaves the API in the same shape (``{"detail": ..., "code": ...}``)
and unexpected exceptions are logged with a traceback but never leak internals
to the client.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.logging import get_logger
from app.scrapers.url_guard import UnsafeURLError
from app.services.competitors import DuplicateCompetitorError, NotFoundError

logger = get_logger(__name__)


def _json(status_code: int, detail: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, "code": code})


def register_error_handlers(app: FastAPI) -> None:
    """Attach every exception handler to the application."""

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """Flatten pydantic errors into a readable sentence."""
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error.get('loc', [])[1:]) or 'body'}: "
            f"{error.get('msg', 'invalid')}"
            for error in exc.errors()
        )
        return _json(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            problems or "invalid request",
            "validation_error",
        )

    @app.exception_handler(NotFoundError)
    async def not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return _json(status.HTTP_404_NOT_FOUND, str(exc), "not_found")

    @app.exception_handler(DuplicateCompetitorError)
    async def duplicate(_request: Request, exc: DuplicateCompetitorError) -> JSONResponse:
        return _json(status.HTTP_409_CONFLICT, str(exc), "duplicate")

    @app.exception_handler(UnsafeURLError)
    async def unsafe_url(_request: Request, exc: UnsafeURLError) -> JSONResponse:
        return _json(status.HTTP_400_BAD_REQUEST, str(exc), "unsafe_url")

    @app.exception_handler(IntegrityError)
    async def integrity(_request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("Database integrity error: %s", exc)
        return _json(
            status.HTTP_409_CONFLICT, "the record conflicts with an existing one", "conflict"
        )

    @app.exception_handler(OperationalError)
    async def operational(_request: Request, exc: OperationalError) -> JSONResponse:
        """Transient database trouble (SQLite lock contention, dropped pool)."""
        logger.error("Database operational error: %s", exc)
        return _json(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the database is temporarily unavailable; please retry",
            "database_unavailable",
        )

    @app.exception_handler(SQLAlchemyError)
    async def database(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("Database error", exc_info=exc)
        return _json(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "a database error occurred", "database_error"
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _json(exc.status_code, str(exc.detail), "http_error")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return _json(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "an unexpected error occurred",
            "internal_error",
        )
