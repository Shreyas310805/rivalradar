"""Competitor, tracked-URL and scan endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.database.session import get_db
from app.schemas.api import (
    CompetitorCreate,
    CompetitorRead,
    CompetitorSummary,
    CompetitorUpdate,
    ScanResponse,
    ScanRunRead,
    ScanStats,
    ScanURLResult,
    TrackedURLCreate,
    TrackedURLRead,
    TrackedURLUpdate,
)
from app.services import competitors as competitor_service
from app.services.competitors import DuplicateCompetitorError, NotFoundError
from app.services.scan import scan_competitor

logger = get_logger(__name__)

router = APIRouter(prefix="/api/competitors", tags=["competitors"])


@router.get("", response_model=list[CompetitorSummary])
def list_competitors(
    active_only: bool = Query(False, description="only return competitors with tracking enabled"),
    session: Session = Depends(get_db),
) -> list[CompetitorSummary]:
    """List every tracked competitor with rolled-up activity counters."""
    records = competitor_service.list_competitors(session, active_only=active_only)
    return [
        CompetitorSummary(
            **CompetitorRead.model_validate(competitor).model_dump(),
            **competitor_service.competitor_summary(session, competitor),
        )
        for competitor in records
    ]


@router.post("", response_model=CompetitorRead, status_code=status.HTTP_201_CREATED)
def create_competitor(
    payload: CompetitorCreate, session: Session = Depends(get_db)
) -> CompetitorRead:
    """Create a competitor. Defaults to tracking the homepage."""
    try:
        competitor = competitor_service.create_competitor(session, payload)
    except DuplicateCompetitorError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CompetitorRead.model_validate(competitor)


@router.get("/{competitor_id}", response_model=CompetitorSummary)
def get_competitor(competitor_id: int, session: Session = Depends(get_db)) -> CompetitorSummary:
    """Fetch one competitor."""
    try:
        competitor = competitor_service.get_competitor(session, competitor_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CompetitorSummary(
        **CompetitorRead.model_validate(competitor).model_dump(),
        **competitor_service.competitor_summary(session, competitor),
    )


@router.put("/{competitor_id}", response_model=CompetitorRead)
def update_competitor(
    competitor_id: int, payload: CompetitorUpdate, session: Session = Depends(get_db)
) -> CompetitorRead:
    """Update a competitor."""
    try:
        competitor = competitor_service.update_competitor(session, competitor_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateCompetitorError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CompetitorRead.model_validate(competitor)


@router.delete("/{competitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competitor(competitor_id: int, session: Session = Depends(get_db)) -> None:
    """Delete a competitor and all of its data."""
    try:
        competitor_service.delete_competitor(session, competitor_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{competitor_id}/toggle", response_model=CompetitorRead)
def toggle_competitor(
    competitor_id: int,
    active: bool = Query(..., description="enable or disable tracking"),
    session: Session = Depends(get_db),
) -> CompetitorRead:
    """Enable or disable tracking for a competitor."""
    try:
        competitor = competitor_service.set_active(session, competitor_id, active)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CompetitorRead.model_validate(competitor)


# --- Tracked URLs -----------------------------------------------------------


@router.get("/{competitor_id}/urls", response_model=list[TrackedURLRead])
def list_tracked_urls(
    competitor_id: int, session: Session = Depends(get_db)
) -> list[TrackedURLRead]:
    """List the pages tracked for a competitor."""
    try:
        competitor = competitor_service.get_competitor(session, competitor_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [TrackedURLRead.model_validate(url) for url in competitor.tracked_urls]


@router.post(
    "/{competitor_id}/urls", response_model=TrackedURLRead, status_code=status.HTTP_201_CREATED
)
def add_tracked_url(
    competitor_id: int, payload: TrackedURLCreate, session: Session = Depends(get_db)
) -> TrackedURLRead:
    """Track an additional page for a competitor."""
    try:
        tracked = competitor_service.add_tracked_url(session, competitor_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TrackedURLRead.model_validate(tracked)


@router.put("/urls/{tracked_url_id}", response_model=TrackedURLRead)
def update_tracked_url(
    tracked_url_id: int, payload: TrackedURLUpdate, session: Session = Depends(get_db)
) -> TrackedURLRead:
    """Update a tracked page."""
    try:
        tracked = competitor_service.update_tracked_url(session, tracked_url_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TrackedURLRead.model_validate(tracked)


@router.delete("/urls/{tracked_url_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tracked_url(tracked_url_id: int, session: Session = Depends(get_db)) -> None:
    """Stop tracking a page."""
    try:
        competitor_service.delete_tracked_url(session, tracked_url_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- Scanning ---------------------------------------------------------------


@router.post("/{competitor_id}/scan", response_model=ScanResponse)
def scan(
    competitor_id: int,
    use_llm: bool = Query(True, description="run LLM analysis on meaningful changes"),
    session: Session = Depends(get_db),
) -> ScanResponse:
    """Run a scan for one competitor immediately.

    Synchronous by design: a portfolio demo should show the funnel numbers in
    the response rather than making the reviewer poll a job queue.
    """
    try:
        competitor = competitor_service.get_competitor(session, competitor_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    outcome = scan_competitor(session, competitor, llm_enabled=use_llm)

    return ScanResponse(
        scan_run_id=outcome.scan_run_id,
        competitor_id=outcome.competitor_id,
        competitor_name=outcome.competitor_name,
        status=outcome.status,
        urls_scanned=outcome.urls_scanned,
        urls_failed=outcome.urls_failed,
        stats=ScanStats(**outcome.stats.to_dict()),
        results=[
            ScanURLResult(
                url=result.url,
                status=result.status,
                message=result.message,
                stats=ScanStats(**result.stats.to_dict()),
            )
            for result in outcome.results
        ],
        errors=outcome.errors,
    )


@router.get("/{competitor_id}/scans", response_model=list[ScanRunRead])
def list_scan_runs(
    competitor_id: int,
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[ScanRunRead]:
    """Scan history for a competitor."""
    from sqlalchemy import select

    from app.models.entities import ScanRun

    runs = (
        session.execute(
            select(ScanRun)
            .where(ScanRun.competitor_id == competitor_id)
            .order_by(ScanRun.started_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [ScanRunRead.model_validate(run) for run in runs]
