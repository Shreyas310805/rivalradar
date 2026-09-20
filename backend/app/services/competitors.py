"""Competitor and tracked-URL CRUD."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.database.base import utcnow
from app.database.demo_pages import is_demo_competitor
from app.models.entities import Change, Competitor, ScanRun, Snapshot, TrackedURL
from app.schemas.api import (
    CompetitorCreate,
    CompetitorUpdate,
    TrackedURLCreate,
    TrackedURLUpdate,
)
from app.scrapers.url_guard import guess_page_type

logger = get_logger(__name__)

HIGH_IMPACT_THRESHOLD = 70.0


class DuplicateCompetitorError(ValueError):
    """Raised when a competitor name is already taken."""


class NotFoundError(LookupError):
    """Raised when a requested record does not exist."""


def list_competitors(session: Session, *, active_only: bool = False) -> list[Competitor]:
    """Return all competitors, newest last."""
    query = select(Competitor).order_by(Competitor.id)
    if active_only:
        query = query.where(Competitor.active.is_(True))
    return list(session.execute(query).scalars().all())


def get_competitor(session: Session, competitor_id: int) -> Competitor:
    """Return one competitor or raise :class:`NotFoundError`."""
    competitor = session.get(Competitor, competitor_id)
    if competitor is None:
        raise NotFoundError(f"competitor {competitor_id} not found")
    return competitor


def create_competitor(session: Session, payload: CompetitorCreate) -> Competitor:
    """Create a competitor and its initial tracked URLs."""
    existing = session.execute(
        select(Competitor).where(func.lower(Competitor.name) == payload.name.casefold())
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateCompetitorError(f"a competitor named {payload.name!r} already exists")

    competitor = Competitor(
        name=payload.name.strip(),
        website_url=payload.website_url,
        description=payload.description,
        tracking_frequency=payload.tracking_frequency.value,
        active=payload.active,
    )
    session.add(competitor)
    session.flush()

    # Track the homepage by default so a new competitor is never empty.
    urls = payload.tracked_urls or [TrackedURLCreate(url=payload.website_url, label="Homepage")]
    for url_payload in urls:
        _add_tracked_url(session, competitor, url_payload, commit=False)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateCompetitorError(str(exc.orig)) from exc

    session.refresh(competitor)
    logger.info("Created competitor %s (%d)", competitor.name, competitor.id)
    return competitor


def update_competitor(
    session: Session, competitor_id: int, payload: CompetitorUpdate
) -> Competitor:
    """Apply a partial update to a competitor."""
    competitor = get_competitor(session, competitor_id)
    data = payload.model_dump(exclude_unset=True, exclude_none=True)

    if "name" in data:
        clash = session.execute(
            select(Competitor).where(
                func.lower(Competitor.name) == str(data["name"]).casefold(),
                Competitor.id != competitor_id,
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise DuplicateCompetitorError(f"a competitor named {data['name']!r} already exists")

    if "tracking_frequency" in data:
        frequency = data.pop("tracking_frequency")
        competitor.tracking_frequency = getattr(frequency, "value", str(frequency))

    for field, value in data.items():
        setattr(competitor, field, value)

    competitor.updated_at = utcnow()
    session.commit()
    session.refresh(competitor)
    return competitor


def delete_competitor(session: Session, competitor_id: int) -> None:
    """Delete a competitor and everything cascading from it."""
    competitor = get_competitor(session, competitor_id)
    session.delete(competitor)
    session.commit()
    logger.info("Deleted competitor %d", competitor_id)


def set_active(session: Session, competitor_id: int, active: bool) -> Competitor:
    """Enable or disable tracking for a competitor."""
    competitor = get_competitor(session, competitor_id)
    competitor.active = active
    competitor.updated_at = utcnow()
    session.commit()
    session.refresh(competitor)
    return competitor


def _add_tracked_url(
    session: Session,
    competitor: Competitor,
    payload: TrackedURLCreate,
    *,
    commit: bool = True,
) -> TrackedURL:
    """Attach a tracked URL to a competitor."""
    tracked = TrackedURL(
        competitor_id=competitor.id,
        url=payload.url,
        label=payload.label,
        page_type=payload.page_type or guess_page_type(payload.url),
        render_js=payload.render_js,
        active=payload.active,
    )
    session.add(tracked)
    if commit:
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(f"{payload.url} is already tracked for this competitor") from exc
        session.refresh(tracked)
    else:
        session.flush()
    return tracked


def add_tracked_url(
    session: Session, competitor_id: int, payload: TrackedURLCreate
) -> TrackedURL:
    """Public wrapper that resolves the competitor first."""
    competitor = get_competitor(session, competitor_id)
    return _add_tracked_url(session, competitor, payload)


def update_tracked_url(
    session: Session, tracked_url_id: int, payload: TrackedURLUpdate
) -> TrackedURL:
    """Apply a partial update to a tracked URL."""
    tracked = session.get(TrackedURL, tracked_url_id)
    if tracked is None:
        raise NotFoundError(f"tracked URL {tracked_url_id} not found")

    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(tracked, field, value)

    session.commit()
    session.refresh(tracked)
    return tracked


def delete_tracked_url(session: Session, tracked_url_id: int) -> None:
    """Delete a tracked URL and its snapshots."""
    tracked = session.get(TrackedURL, tracked_url_id)
    if tracked is None:
        raise NotFoundError(f"tracked URL {tracked_url_id} not found")
    session.delete(tracked)
    session.commit()


def competitor_summary(session: Session, competitor: Competitor) -> dict:
    """Roll up per-competitor counters for the dashboard."""
    week_ago = utcnow() - timedelta(days=7)

    changes_this_week = (
        session.execute(
            select(func.count(Change.id)).where(
                Change.competitor_id == competitor.id,
                Change.is_noise.is_(False),
                Change.detected_at >= week_ago,
            )
        ).scalar()
        or 0
    )
    high_impact_this_week = (
        session.execute(
            select(func.count(Change.id)).where(
                Change.competitor_id == competitor.id,
                Change.is_noise.is_(False),
                Change.relevance_score >= HIGH_IMPACT_THRESHOLD,
                Change.detected_at >= week_ago,
            )
        ).scalar()
        or 0
    )
    total_changes = (
        session.execute(
            select(func.count(Change.id)).where(
                Change.competitor_id == competitor.id, Change.is_noise.is_(False)
            )
        ).scalar()
        or 0
    )
    last_scan = session.execute(
        select(func.max(ScanRun.finished_at)).where(ScanRun.competitor_id == competitor.id)
    ).scalar()
    if last_scan is None:
        last_scan = session.execute(
            select(func.max(Snapshot.timestamp)).where(Snapshot.competitor_id == competitor.id)
        ).scalar()

    return {
        "is_demo": is_demo_competitor(competitor.name, competitor.website_url),
        "tracked_url_count": len(competitor.tracked_urls),
        "last_scan": last_scan,
        "changes_this_week": int(changes_this_week),
        "high_impact_this_week": int(high_impact_this_week),
        "total_changes": int(total_changes),
    }
