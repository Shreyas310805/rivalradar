"""Wayback evaluation endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.database.session import get_db
from app.evaluation.runner import evaluate_urls, save_report
from app.models.entities import Evaluation
from app.schemas.api import EvaluationRead, WaybackRequest

logger = get_logger(__name__)

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/wayback", response_model=list[EvaluationRead])
def list_evaluations(
    limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_db)
) -> list[EvaluationRead]:
    """List past Wayback evaluation runs, newest first."""
    rows = (
        session.execute(
            select(Evaluation).order_by(Evaluation.created_at.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return [EvaluationRead.model_validate(row) for row in rows]


@router.get("/wayback/latest", response_model=EvaluationRead)
def latest_evaluation(session: Session = Depends(get_db)) -> EvaluationRead:
    """Return the most recent evaluation run."""
    row = session.execute(
        select(Evaluation).order_by(Evaluation.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no evaluation has been run yet; POST /api/evaluation/wayback first",
        )
    return EvaluationRead.model_validate(row)


@router.post("/wayback", response_model=EvaluationRead)
def run_evaluation(
    payload: WaybackRequest, session: Session = Depends(get_db)
) -> EvaluationRead:
    """Run a Wayback benchmark for one URL and store the result.

    This performs live network calls to the Internet Archive and can take
    30-90 seconds depending on page size and Archive load.
    """
    report = evaluate_urls(
        [payload.url],
        from_date=payload.from_date,
        to_date=payload.to_date,
        limit=payload.limit * 10,
    )

    page = report.pages[0] if report.pages else None
    stats = report.stats

    report_path: str | None = None
    try:
        text_path, _ = save_report(report)
        report_path = str(text_path)
    except OSError:
        logger.warning("Could not write evaluation report to disk", exc_info=True)

    record = Evaluation(
        kind="wayback",
        target_url=payload.url,
        snapshot_a=page.snapshot_a if page else None,
        snapshot_b=page.snapshot_b if page else None,
        pages_evaluated=len(report.successful_pages),
        raw_changes=stats.raw_changes,
        noise_changes=stats.noise_changes,
        meaningful_changes=stats.meaningful_changes,
        high_impact_changes=stats.high_impact_changes,
        noise_reduction=stats.noise_reduction,
        category_breakdown=json.dumps(report.categories),
        report_path=report_path,
        status="completed" if report.successful_pages else "failed",
        error=(page.error if page and page.status != "completed" else None),
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    if not report.successful_pages:
        # Persisted for the audit trail, but tell the caller it did not work.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=record.error or "no usable Wayback snapshots for this URL",
        )

    return EvaluationRead.model_validate(record)
