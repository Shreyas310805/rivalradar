"""SQLAlchemy declarative base."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp (SQLite has no native tz support)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for every RivalRadar ORM model."""
