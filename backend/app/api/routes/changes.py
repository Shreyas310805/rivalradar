"""Change, intelligence, digest and analytics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.database.session import get_db
from app.diff.engine import inline_word_diff
from app.intelligence import digest as digest_service
from app.models.entities import Change, Competitor, Intelligence
from app.schemas.api import (
    AnalyticsResponse,
    ChangeDetail,
    ChangeRead,
    DashboardStats,
    DiffSegment,
    DigestGenerateRequest,
    DigestRead,
    IntelligenceItem,
    IntelligenceRead,
)
from app.services import analytics as analytics_service

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["intelligence"])


@router.get("/changes", response_model=list[ChangeDetail])
def list_changes(
    competitor_id: int | None = Query(None),
    category: str | None = Query(None),
    severity: str | None = Query(None),
    include_noise: bool = Query(False, description="include changes rejected as noise"),
    min_score: float | None = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
) -> list[ChangeDetail]:
    """List detected changes, newest first.

    Noise is excluded by default; pass ``include_noise=true`` to inspect what
    the filter discarded and why.
    """
    query = (
        select(Change, Competitor.name)
        .join(Competitor, Competitor.id == Change.competitor_id)
        .order_by(Change.detected_at.desc(), Change.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if not include_noise:
        query = query.where(Change.is_noise.is_(False))
    if competitor_id is not None:
        query = query.where(Change.competitor_id == competitor_id)
    if category:
        query = query.where(Change.category == category)
    if severity:
        query = query.where(Change.severity == severity)
    if min_score is not None:
        query = query.where(Change.relevance_score >= min_score)

    results: list[ChangeDetail] = []
    for change, competitor_name in session.execute(query).all():
        detail = ChangeDetail(
            **ChangeRead.model_validate(change).model_dump(),
            competitor_name=competitor_name,
            intelligence=(
                IntelligenceRead.model_validate(change.intelligence)
                if change.intelligence
                else None
            ),
        )
        results.append(detail)
    return results


@router.get("/changes/{change_id}", response_model=ChangeDetail)
def get_change(change_id: int, session: Session = Depends(get_db)) -> ChangeDetail:
    """Fetch one change with its analysis and a word-level before/after diff."""
    row = session.execute(
        select(Change, Competitor.name)
        .join(Competitor, Competitor.id == Change.competitor_id)
        .where(Change.id == change_id)
    ).one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"change {change_id} not found"
        )

    change, competitor_name = row
    segments = [
        DiffSegment(**segment)
        for segment in inline_word_diff(change.before or "", change.after or "")
    ]
    return ChangeDetail(
        **ChangeRead.model_validate(change).model_dump(),
        competitor_name=competitor_name,
        intelligence=(
            IntelligenceRead.model_validate(change.intelligence) if change.intelligence else None
        ),
        diff_segments=segments,
    )


@router.get("/intelligence", response_model=list[IntelligenceItem])
def list_intelligence(
    competitor_id: int | None = Query(None),
    category: str | None = Query(None),
    min_score: float | None = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[IntelligenceItem]:
    """List AI-generated competitive intelligence, newest first."""
    rows = analytics_service.recent_intelligence(
        session,
        limit=limit,
        competitor_id=competitor_id,
        min_score=min_score,
        category=category,
    )
    items: list[IntelligenceItem] = []
    for intel, competitor_name, source_url, change_type, location in rows:
        payload = IntelligenceRead.model_validate(intel).model_dump()
        # Older records may predate the stored source_url; fall back to the
        # change's URL so "View source" always has something to point at.
        payload["source_url"] = payload.get("source_url") or (source_url or "")
        items.append(
            IntelligenceItem(
                **payload,
                competitor_name=competitor_name,
                change_type=change_type or "",
                location=location or "",
            )
        )
    return items


@router.get("/intelligence/{intelligence_id}", response_model=IntelligenceRead)
def get_intelligence(
    intelligence_id: int, session: Session = Depends(get_db)
) -> IntelligenceRead:
    """Fetch one intelligence record."""
    intel = session.get(Intelligence, intelligence_id)
    if intel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"intelligence {intelligence_id} not found",
        )
    return IntelligenceRead.model_validate(intel)


# --- Digest -----------------------------------------------------------------


@router.get("/digest/latest", response_model=DigestRead)
def latest_digest(session: Session = Depends(get_db)) -> DigestRead:
    """Return the most recent weekly digest."""
    digest = digest_service.get_latest_digest(session)
    if digest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no digest has been generated yet; POST /api/digest/generate first",
        )
    return DigestRead.model_validate(digest)


@router.get("/digest", response_model=list[DigestRead])
def list_digests(
    limit: int = Query(10, ge=1, le=100), session: Session = Depends(get_db)
) -> list[DigestRead]:
    """List generated digests, newest first."""
    from app.models.entities import Digest

    digests = (
        session.execute(select(Digest).order_by(Digest.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return [DigestRead.model_validate(digest) for digest in digests]


@router.post("/digest/generate", response_model=DigestRead)
def generate_digest(
    payload: DigestGenerateRequest | None = None, session: Session = Depends(get_db)
) -> DigestRead:
    """Generate a digest covering the last N days."""
    options = payload or DigestGenerateRequest()
    digest = digest_service.generate_digest(
        session, days=options.days, competitor_id=options.competitor_id
    )
    return DigestRead.model_validate(digest)


# --- Analytics --------------------------------------------------------------


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(session: Session = Depends(get_db)) -> DashboardStats:
    """Headline dashboard metrics."""
    return DashboardStats(**analytics_service.dashboard_stats(session))


@router.get("/analytics", response_model=AnalyticsResponse)
def analytics(
    days: int = Query(30, ge=1, le=365), session: Session = Depends(get_db)
) -> AnalyticsResponse:
    """Full analytics payload: funnel, categories, timeline and noise reasons."""
    payload = analytics_service.analytics_payload(session, days=days)
    return AnalyticsResponse(
        stats=DashboardStats(**payload["stats"]),
        categories=payload["categories"],
        timeline=payload["timeline"],
        noise_reasons=payload["noise_reasons"],
        severity_distribution=payload["severity_distribution"],
        top_competitors=payload["top_competitors"],
    )
