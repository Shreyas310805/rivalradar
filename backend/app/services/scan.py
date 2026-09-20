"""Scan orchestration.

Owns the database session and the network calls; delegates all reasoning to
the LangGraph pipeline.  One scan covers every active tracked URL of one
competitor, and a failure on one page never aborts the others.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agents.graph import run_pipeline
from app.config.logging import get_logger
from app.config.settings import settings
from app.database.base import utcnow
from app.database.demo_pages import demo_html_for
from app.diff.types import DiffStats
from app.models.entities import Change, Competitor, Intelligence, ScanRun, Severity, TrackedURL
from app.scrapers.fetcher import FetchResult, fetch_html_string, fetch_url
from app.services import snapshots as snapshot_service

logger = get_logger(__name__)


@dataclass(slots=True)
class URLScanOutcome:
    """Result of scanning one tracked URL."""

    url: str
    status: str
    message: str | None = None
    stats: DiffStats = field(default_factory=DiffStats)
    intelligence_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ScanOutcome:
    """Result of scanning one competitor."""

    competitor_id: int
    competitor_name: str
    status: str = "completed"
    scan_run_id: int | None = None
    urls_scanned: int = 0
    urls_failed: int = 0
    stats: DiffStats = field(default_factory=DiffStats)
    results: list[URLScanOutcome] = field(default_factory=list)
    intelligence_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _persist_changes(
    session: Session,
    competitor: Competitor,
    snapshot_id: int,
    previous_snapshot_id: int | None,
    state: dict,
    tracked_url_id: int | None = None,
) -> list[int]:
    """Write the annotated funnel and its intelligence records to the database.

    Every change is stored, noise included — the discarded rows are the
    evidence behind the noise-reduction metric and power the analytics page.
    """
    classified = state.get("classified_changes") or []
    intelligence_items = state.get("intelligence") or []

    # Index analyses by the change they describe so rows can be linked up.
    analysis_by_key: dict[tuple[str, str], dict] = {}
    for item in intelligence_items:
        change = item.get("change") or {}
        key = ((change.get("before") or "")[:200], (change.get("after") or "")[:200])
        analysis_by_key[key] = item

    created_intelligence: list[int] = []

    for payload in classified:
        change_row = Change(
            snapshot_id=snapshot_id,
            previous_snapshot_id=previous_snapshot_id,
            competitor_id=competitor.id,
            change_type=payload.get("change_type", "modified"),
            category=payload.get("category", "other"),
            location=payload.get("location", "body"),
            before=payload.get("before") or None,
            after=payload.get("after") or None,
            magnitude=float(payload.get("magnitude", 0.0) or 0.0),
            is_noise=bool(payload.get("is_noise", False)),
            noise_reason=payload.get("noise_reason"),
            relevance_score=float(payload.get("relevance_score", 0.0) or 0.0),
            severity=payload.get("severity", Severity.NOISE.value),
            classifier_confidence=float(payload.get("classifier_confidence", 0.0) or 0.0),
            source_url=payload.get("source_url", "") or "",
            detected_at=utcnow(),
        )
        session.add(change_row)
        session.flush()

        key = ((payload.get("before") or "")[:200], (payload.get("after") or "")[:200])
        item = analysis_by_key.get(key)
        if item is None:
            continue

        intel = Intelligence(
            change_id=change_row.id,
            competitor_id=competitor.id,
            title=item.get("title") or f"{competitor.name} page change",
            category=item.get("category", change_row.category),
            summary=item.get("summary", ""),
            before=item.get("before"),
            after=item.get("after"),
            business_impact=item.get("business_impact", ""),
            recommended_action=item.get("recommended_action"),
            relevance_score=float(item.get("relevance_score", change_row.relevance_score)),
            severity=item.get("severity", change_row.severity),
            confidence=float(item.get("confidence", 0.5)),
            analysed_by=item.get("analysed_by", "deterministic"),
            llm_status=item.get("llm_status", "skipped"),
            llm_error=(item.get("llm_error") or None),
            llm_model=item.get("llm_model"),
            # Traceability: point back at the exact evidence.
            tracked_url_id=tracked_url_id,
            snapshot_id=snapshot_id,
            previous_snapshot_id=previous_snapshot_id,
            source_url=(change_row.source_url or ""),
        )
        session.add(intel)
        session.flush()
        created_intelligence.append(intel.id)

        # Keep the change row consistent with the post-analysis score.
        change_row.relevance_score = intel.relevance_score
        change_row.severity = intel.severity

    return created_intelligence


def scan_tracked_url(
    session: Session,
    competitor: Competitor,
    tracked_url: TrackedURL,
    *,
    llm_enabled: bool = True,
    fetch_result: FetchResult | None = None,
) -> URLScanOutcome:
    """Fetch, diff and analyse a single tracked URL.

    ``fetch_result`` lets callers (demo seeding, tests) supply content directly
    instead of hitting the network.
    """
    logger.info("Scanning %s (%s)", tracked_url.url, competitor.name)

    result = fetch_result
    if result is None:
        # Demo fixtures are ONLY served when DEMO_MODE is explicitly enabled.
        # With DEMO_MODE=false (the default) every scan is a real HTTP fetch.
        demo_html = demo_html_for(tracked_url.url) if settings.demo_mode else None
        result = (
            fetch_html_string(demo_html, url=tracked_url.url)
            if demo_html is not None
            else fetch_url(tracked_url.url, render_js=tracked_url.render_js, check_robots=True)
        )

    if not result.ok:
        snapshot_service.record_failure(session, tracked_url, result)
        return URLScanOutcome(
            url=tracked_url.url,
            status="failed",
            message=f"{result.error_kind}: {result.error}",
        )

    previous = snapshot_service.get_latest_snapshot(session, tracked_url.id)
    previous_payload = snapshot_service.snapshot_to_dict(previous)

    snapshot, is_new = snapshot_service.store_snapshot(session, tracked_url, result)

    if not is_new:
        return URLScanOutcome(
            url=tracked_url.url,
            status="unchanged",
            message="No meaningful page change (content hash identical)",
        )

    if previous is None:
        return URLScanOutcome(
            url=tracked_url.url,
            status="baseline",
            message="Baseline snapshot created. Run a second scan to detect changes.",
        )

    state = run_pipeline(
        competitor={"id": competitor.id, "name": competitor.name},
        tracked_url={"id": tracked_url.id, "url": tracked_url.url},
        current_snapshot=snapshot_service.snapshot_to_dict(snapshot) or {},
        previous_snapshot=previous_payload,
        llm_enabled=llm_enabled,
    )

    if state.get("skipped"):
        return URLScanOutcome(
            url=tracked_url.url,
            status="unchanged",
            message=state.get("skip_reason") or "no comparable change",
        )

    intelligence_ids = _persist_changes(
        session,
        competitor,
        snapshot.id,
        previous.id if previous else None,
        state,
        tracked_url_id=tracked_url.id,
    )

    raw_stats = state.get("stats") or {}
    stats = DiffStats(
        raw_changes=int(raw_stats.get("raw_changes", 0)),
        noise_changes=int(raw_stats.get("noise_changes", 0)),
        meaningful_changes=int(raw_stats.get("meaningful_changes", 0)),
        high_impact_changes=int(raw_stats.get("high_impact_changes", 0)),
    )

    return URLScanOutcome(
        url=tracked_url.url,
        status="changed",
        message=f"{stats.meaningful_changes} meaningful change(s) detected",
        stats=stats,
        intelligence_ids=intelligence_ids,
    )


def scan_competitor(
    session: Session,
    competitor: Competitor,
    *,
    llm_enabled: bool = True,
    record_run: bool = True,
) -> ScanOutcome:
    """Scan every active tracked URL of a competitor."""
    outcome = ScanOutcome(competitor_id=competitor.id, competitor_name=competitor.name)

    run: ScanRun | None = None
    if record_run:
        run = ScanRun(competitor_id=competitor.id, started_at=utcnow(), status="running")
        session.add(run)
        session.flush()
        outcome.scan_run_id = run.id

    active_urls = [url for url in competitor.tracked_urls if url.active]
    if not active_urls:
        outcome.errors.append("competitor has no active tracked URLs")

    total = DiffStats()
    for tracked_url in active_urls:
        try:
            url_outcome = scan_tracked_url(
                session, competitor, tracked_url, llm_enabled=llm_enabled
            )
        except Exception as exc:  # noqa: BLE001 - one bad page must not stop the scan
            logger.error("Scan failed for %s", tracked_url.url, exc_info=True)
            session.rollback()
            url_outcome = URLScanOutcome(
                url=tracked_url.url, status="failed", message=f"unexpected error: {exc}"
            )
            outcome.errors.append(f"{tracked_url.url}: {exc}")

        outcome.results.append(url_outcome)
        outcome.intelligence_ids.extend(url_outcome.intelligence_ids)
        if url_outcome.status == "failed":
            outcome.urls_failed += 1
        else:
            outcome.urls_scanned += 1
            total = total.merge(url_outcome.stats)

    outcome.stats = total

    if not active_urls:
        status = "no_urls"
    elif outcome.urls_failed == len(active_urls):
        status = "failed"
    else:
        status = "completed"

    if run is not None:
        run.finished_at = utcnow()
        run.status = status
        run.urls_scanned = outcome.urls_scanned
        run.urls_failed = outcome.urls_failed
        run.raw_changes = total.raw_changes
        run.noise_changes = total.noise_changes
        run.meaningful_changes = total.meaningful_changes
        run.high_impact_changes = total.high_impact_changes
        run.noise_reduction = total.noise_reduction
        run.error = "; ".join(outcome.errors)[:2000] or None

    outcome.status = status

    session.commit()
    logger.info(
        "Scan complete for %s: %d URLs, %d raw changes, %.1f%% noise reduction",
        competitor.name,
        outcome.urls_scanned,
        total.raw_changes,
        total.noise_reduction,
    )
    return outcome


def scan_all(session: Session, *, llm_enabled: bool = True) -> list[ScanOutcome]:
    """Scan every active competitor."""
    from sqlalchemy import select

    competitors = (
        session.execute(select(Competitor).where(Competitor.active.is_(True)).order_by(Competitor.id))
        .scalars()
        .all()
    )
    outcomes: list[ScanOutcome] = []
    for competitor in competitors:
        try:
            outcomes.append(scan_competitor(session, competitor, llm_enabled=llm_enabled))
        except Exception as exc:  # noqa: BLE001
            logger.error("Scan failed for competitor %s", competitor.name, exc_info=True)
            session.rollback()
            outcomes.append(
                ScanOutcome(
                    competitor_id=competitor.id,
                    competitor_name=competitor.name,
                    status="failed",
                    errors=[str(exc)],
                )
            )
    return outcomes
