"""Snapshot persistence.

Large HTML bodies are written to ``data/snapshots/`` and referenced by path so
the database stays small and browsable.  Identical consecutive snapshots are
not duplicated: when the content hash matches the previous one, the existing
row's timestamp is refreshed and no LLM work is scheduled.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.config.settings import settings
from app.database.base import utcnow
from app.models.entities import Snapshot, TrackedURL
from app.scrapers.fetcher import FetchResult

logger = get_logger(__name__)


def _snapshot_path(tracked_url_id: int, timestamp: datetime, content_hash: str) -> Path:
    """Deterministic on-disk location for a snapshot body."""
    directory = settings.snapshots_dir / f"url_{tracked_url_id}"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.strftime("%Y%m%dT%H%M%S")
    return directory / f"{stamp}_{content_hash[:12]}.html"


def get_latest_snapshot(session: Session, tracked_url_id: int) -> Snapshot | None:
    """Return the most recent snapshot for a tracked URL."""
    return session.execute(
        select(Snapshot)
        .where(Snapshot.tracked_url_id == tracked_url_id)
        .order_by(Snapshot.timestamp.desc(), Snapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_previous_snapshot(session: Session, snapshot: Snapshot) -> Snapshot | None:
    """Return the snapshot immediately preceding ``snapshot``."""
    return session.execute(
        select(Snapshot)
        .where(
            Snapshot.tracked_url_id == snapshot.tracked_url_id,
            Snapshot.id != snapshot.id,
            Snapshot.timestamp <= snapshot.timestamp,
        )
        .order_by(Snapshot.timestamp.desc(), Snapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def store_snapshot(
    session: Session,
    tracked_url: TrackedURL,
    result: FetchResult,
    *,
    source: str = "live",
    persist_html: bool = True,
) -> tuple[Snapshot, bool]:
    """Persist a fetch result as a snapshot.

    Returns ``(snapshot, is_new)``.  ``is_new`` is ``False`` when the content
    hash matched the previous snapshot, meaning there is no meaningful page
    change and the expensive downstream stages can be skipped entirely.
    """
    previous = get_latest_snapshot(session, tracked_url.id)

    if previous is not None and previous.content_hash == result.content_hash:
        logger.info(
            "No meaningful page change for %s (hash %s unchanged)",
            tracked_url.url,
            result.content_hash[:12],
        )
        previous.timestamp = utcnow()
        tracked_url.last_checked = utcnow()
        tracked_url.last_status = "unchanged"
        tracked_url.last_error = None
        session.flush()
        return previous, False

    timestamp = utcnow()
    html_path: str | None = None
    if persist_html and result.raw_html:
        try:
            path = _snapshot_path(tracked_url.id, timestamp, result.content_hash)
            path.write_text(result.raw_html, encoding="utf-8", errors="ignore")
            html_path = str(path.relative_to(settings.data_dir.parent))
        except OSError:
            logger.warning("Could not write snapshot body for %s", tracked_url.url, exc_info=True)

    snapshot = Snapshot(
        tracked_url_id=tracked_url.id,
        competitor_id=tracked_url.competitor_id,
        url=tracked_url.url,
        timestamp=timestamp,
        status_code=result.status_code,
        content_hash=result.content_hash,
        raw_html_path=html_path,
        # Keep a bounded copy in the DB so the API can render diffs without disk access.
        raw_html=(result.raw_html or "")[:200_000] or None,
        normalized_text=result.normalized_text,
        title=result.title,
        word_count=result.word_count,
        fetch_duration_ms=result.duration_ms,
        source=source,
    )
    session.add(snapshot)

    tracked_url.last_checked = timestamp
    tracked_url.last_status = "ok"
    tracked_url.last_error = None
    session.flush()

    logger.info(
        "Stored snapshot %d for %s (%d words, hash %s)",
        snapshot.id,
        tracked_url.url,
        snapshot.word_count,
        snapshot.content_hash[:12],
    )
    return snapshot, True


def record_failure(session: Session, tracked_url: TrackedURL, result: FetchResult) -> None:
    """Record a failed fetch against the tracked URL."""
    tracked_url.last_checked = utcnow()
    tracked_url.last_status = result.error_kind or "error"
    tracked_url.last_error = (result.error or "")[:2000]
    session.flush()
    logger.warning("Fetch failed for %s: %s", tracked_url.url, result.error)


def snapshot_to_dict(snapshot: Snapshot | None) -> dict | None:
    """Serialise a snapshot for the LangGraph state."""
    if snapshot is None:
        return None
    return {
        "id": snapshot.id,
        "tracked_url_id": snapshot.tracked_url_id,
        "competitor_id": snapshot.competitor_id,
        "url": snapshot.url,
        "timestamp": snapshot.timestamp.isoformat() if snapshot.timestamp else None,
        "content_hash": snapshot.content_hash,
        "raw_html": snapshot.raw_html or "",
        "normalized_text": snapshot.normalized_text or "",
        "title": snapshot.title,
        "word_count": snapshot.word_count,
    }
