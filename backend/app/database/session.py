"""Engine and session management.

SQLite is the local default and PostgreSQL is used in production. Everything
above this module goes through SQLAlchemy and a single ``DATABASE_URL``, so
the switch is configuration rather than code — but the two engines want
different connection options, and that difference lives here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config.logging import get_logger
from app.config.settings import settings

logger = get_logger(__name__)


def _build_engine(url: str) -> Engine:
    """Create an engine with driver-appropriate options."""
    kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}

    if url.startswith("sqlite"):
        # FastAPI + APScheduler touch the DB from several threads.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        return create_engine(url, **kwargs)

    # --- PostgreSQL ------------------------------------------------------
    # Sized for a free-tier deployment, not a fleet: one small web service
    # against a database with a low connection ceiling. A large pool here just
    # exhausts the server's limit.
    kwargs["pool_size"] = 5
    kwargs["max_overflow"] = 5
    # Managed Postgres closes idle connections; recycle before it does, or the
    # first request after a quiet period fails.
    kwargs["pool_recycle"] = 280
    kwargs["pool_timeout"] = 30

    if url.startswith("postgresql+psycopg"):
        # Supabase's pooled endpoint runs pgbouncer in transaction mode, which
        # cannot carry server-side prepared statements across checkouts.
        # psycopg 3 starts preparing after a few executions, so a query that
        # works all day suddenly fails with "prepared statement does not
        # exist". Disabling the threshold costs a little planning time and
        # makes the pooled and direct endpoints behave identically.
        kwargs["connect_args"] = {"prepare_threshold": None}

    return create_engine(url, **kwargs)


engine = _build_engine(settings.database_url)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
        """WAL + foreign keys make concurrent scans far less fragile."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Prepare the database for use.

    Locally this creates the schema, which keeps first-run setup to zero
    steps. In production it does not: the schema there is owned by Alembic, so
    ``create_all`` would build tables behind the migration history's back and
    leave ``alembic_version`` empty — after which every later migration either
    fails or silently skips. Production only checks that the migrations have
    already been applied, and says so plainly when they have not.
    """
    from app.models import entities  # noqa: F401  (registers models on Base)

    if not settings.is_production:
        entities.Base.metadata.create_all(bind=engine)
        logger.info("Database ready (%s, schema auto-created)", settings.database_backend)
        return

    tables = set(inspect(engine).get_table_names())
    if "competitors" not in tables:
        raise RuntimeError(
            "The production database has no schema. Run 'alembic upgrade head' "
            "against DATABASE_URL before starting the service."
        )
    if "alembic_version" not in tables:
        logger.warning(
            "Schema present but no alembic_version table: this database was not "
            "created by migrations. Run 'alembic stamp head' to adopt it."
        )
    logger.info("Database ready (%s, schema managed by Alembic)", settings.database_backend)


def database_healthy() -> bool:
    """Round-trip a trivial query. Used by the health endpoint."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.error("Database health check failed: %s", exc.__class__.__name__)
        return False


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts, the CLI and background jobs."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
