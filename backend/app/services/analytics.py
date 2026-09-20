"""Aggregate queries for the dashboard and analytics pages."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.config.settings import settings
from app.database.base import utcnow
from app.database.dialects import day_bucket
from app.llm.factory import describe_analyst
from app.models.entities import (
    Change,
    Competitor,
    Intelligence,
    ScanRun,
    Snapshot,
    TrackedURL,
)

logger = get_logger(__name__)

HIGH_IMPACT_THRESHOLD = 70.0


def _analyst_fields(session: Session) -> dict:
    """Describe the analyst honestly.

    Reports the provider that will actually be used, plus the status of the
    most recent analysis, so the dashboard never claims an LLM produced a
    record when it did not.
    """
    analyst = describe_analyst()
    last_status = session.execute(
        select(Intelligence.llm_status)
        .order_by(Intelligence.created_at.desc(), Intelligence.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    return {
        "llm_provider": analyst["provider"],
        "llm_model": analyst["model"],
        "llm_is_llm": bool(analyst["is_llm"]),
        "llm_label": analyst["label"],
        "llm_configured": bool(settings.openrouter_api_key or settings.openai_api_key),
        "llm_last_status": last_status,
        "demo_mode": settings.demo_mode,
    }


def dashboard_stats(session: Session) -> dict:
    """Headline numbers for the dashboard, all counted from stored rows."""
    week_ago = utcnow() - timedelta(days=7)

    totals = session.execute(
        select(
            func.count(Change.id),
            func.sum(func.cast(Change.is_noise, Integer)),
            func.sum(func.cast(Change.relevance_score >= HIGH_IMPACT_THRESHOLD, Integer)),
        )
    ).one()
    raw = int(totals[0] or 0)
    noise = int(totals[1] or 0)
    high_impact = int(totals[2] or 0)

    changes_this_week = (
        session.execute(
            select(func.count(Change.id)).where(
                Change.is_noise.is_(False), Change.detected_at >= week_ago
            )
        ).scalar()
        or 0
    )
    high_impact_this_week = (
        session.execute(
            select(func.count(Change.id)).where(
                Change.is_noise.is_(False),
                Change.relevance_score >= HIGH_IMPACT_THRESHOLD,
                Change.detected_at >= week_ago,
            )
        ).scalar()
        or 0
    )

    last_scan = session.execute(select(func.max(ScanRun.finished_at))).scalar()
    if last_scan is None:
        last_scan = session.execute(select(func.max(Snapshot.timestamp))).scalar()

    return {
        "tracked_competitors": int(
            session.execute(select(func.count(Competitor.id))).scalar() or 0
        ),
        "active_competitors": int(
            session.execute(
                select(func.count(Competitor.id)).where(Competitor.active.is_(True))
            ).scalar()
            or 0
        ),
        "tracked_urls": int(session.execute(select(func.count(TrackedURL.id))).scalar() or 0),
        "total_snapshots": int(session.execute(select(func.count(Snapshot.id))).scalar() or 0),
        "raw_changes": raw,
        "noise_changes": noise,
        "meaningful_changes": raw - noise,
        "high_impact_changes": high_impact,
        "noise_reduction": round(noise / raw * 100, 2) if raw else 0.0,
        "changes_this_week": int(changes_this_week),
        "high_impact_this_week": int(high_impact_this_week),
        "last_scan": last_scan,
        **_analyst_fields(session),
    }


def category_distribution(session: Session, *, days: int | None = None) -> list[dict]:
    """Count meaningful changes per category."""
    query = (
        select(Change.category, func.count(Change.id))
        .where(Change.is_noise.is_(False))
        .group_by(Change.category)
        .order_by(func.count(Change.id).desc())
    )
    if days:
        query = query.where(Change.detected_at >= utcnow() - timedelta(days=days))
    return [
        {"category": category, "count": int(count)}
        for category, count in session.execute(query).all()
    ]


def severity_distribution(session: Session) -> list[dict]:
    """Count meaningful changes per severity band."""
    rows = session.execute(
        select(Change.severity, func.count(Change.id))
        .where(Change.is_noise.is_(False))
        .group_by(Change.severity)
    ).all()
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "noise": 4}
    return sorted(
        ({"category": severity, "count": int(count)} for severity, count in rows),
        key=lambda item: order.get(item["category"], 9),
    )


def activity_timeline(session: Session, *, days: int = 30) -> list[dict]:
    """Daily change volume over the last ``days`` days."""
    since = utcnow() - timedelta(days=days)
    rows = session.execute(
        select(
            day_bucket(Change.detected_at).label("day"),
            func.count(Change.id),
            func.sum(func.cast(Change.is_noise, Integer)),
            func.sum(func.cast(Change.relevance_score >= HIGH_IMPACT_THRESHOLD, Integer)),
        )
        .where(Change.detected_at >= since)
        .group_by("day")
        .order_by("day")
    ).all()

    return [
        {
            "date": str(day),
            "raw_changes": int(total or 0),
            "meaningful_changes": int((total or 0) - (noise or 0)),
            "high_impact_changes": int(high or 0),
        }
        for day, total, noise, high in rows
    ]


def noise_reason_breakdown(session: Session, *, limit: int = 12) -> list[dict]:
    """Which noise rules discarded the most changes."""
    rows = session.execute(
        select(Change.noise_reason, func.count(Change.id))
        .where(Change.is_noise.is_(True), Change.noise_reason.is_not(None))
        .group_by(Change.noise_reason)
        .order_by(func.count(Change.id).desc())
        .limit(limit)
    ).all()
    return [{"reason": reason, "count": int(count)} for reason, count in rows]


def top_competitors(session: Session, *, limit: int = 5) -> list[dict]:
    """Competitors ranked by high-impact activity."""
    rows = session.execute(
        select(
            Competitor.id,
            Competitor.name,
            func.count(Change.id),
            func.sum(func.cast(Change.relevance_score >= HIGH_IMPACT_THRESHOLD, Integer)),
        )
        .join(Change, Change.competitor_id == Competitor.id, isouter=True)
        .where((Change.is_noise.is_(False)) | (Change.id.is_(None)))
        .group_by(Competitor.id, Competitor.name)
        .order_by(func.count(Change.id).desc())
        .limit(limit)
    ).all()

    return [
        {
            "competitor_id": competitor_id,
            "name": name,
            "meaningful_changes": int(total or 0),
            "high_impact_changes": int(high or 0),
        }
        for competitor_id, name, total, high in rows
    ]


def analytics_payload(session: Session, *, days: int = 30) -> dict:
    """Everything the analytics page needs, in one query batch."""
    return {
        "stats": dashboard_stats(session),
        "categories": category_distribution(session),
        "timeline": activity_timeline(session, days=days),
        "noise_reasons": noise_reason_breakdown(session),
        "severity_distribution": severity_distribution(session),
        "top_competitors": top_competitors(session),
    }


def recent_intelligence(
    session: Session,
    *,
    limit: int = 20,
    competitor_id: int | None = None,
    min_score: float | None = None,
    category: str | None = None,
) -> list[tuple[Intelligence, str, str, str, str]]:
    """Recent intelligence joined with competitor and change context."""
    query = (
        select(
            Intelligence,
            Competitor.name,
            Change.source_url,
            Change.change_type,
            Change.location,
        )
        .join(Competitor, Competitor.id == Intelligence.competitor_id)
        .join(Change, Change.id == Intelligence.change_id)
        .order_by(Intelligence.created_at.desc(), Intelligence.relevance_score.desc())
        .limit(limit)
    )
    if competitor_id is not None:
        query = query.where(Intelligence.competitor_id == competitor_id)
    if min_score is not None:
        query = query.where(Intelligence.relevance_score >= min_score)
    if category:
        query = query.where(Intelligence.category == category)

    return list(session.execute(query).all())
