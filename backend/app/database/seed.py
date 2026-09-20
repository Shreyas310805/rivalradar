"""Demo data seeding.

Seeding does *not* insert fabricated change rows.  It stores the v1 revision of
each demo page as a real baseline snapshot, then feeds the v2 revision through
the genuine scan pipeline.  Everything on the dashboard afterwards — every
change, score, category and noise reason — was produced by the real code.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.database.demo_pages import COMPETITORS, tracked_pages
from app.database.session import init_db, session_scope
from app.diff.types import DiffStats
from app.models.entities import (
    Change,
    Competitor,
    Digest,
    Intelligence,
    ScanRun,
    Snapshot,
    TrackedURL,
)
from app.scrapers.fetcher import fetch_html_string
from app.services import snapshots as snapshot_service
from app.services.scan import scan_tracked_url

logger = get_logger(__name__)


def clear_demo_data(session: Session) -> None:
    """Remove every competitor and all data cascading from them."""
    for model in (Intelligence, Change, Snapshot, ScanRun, TrackedURL, Competitor, Digest):
        session.execute(delete(model))
    session.commit()
    logger.info("Cleared existing data")


def _get_or_create_competitor(session: Session, payload: dict) -> Competitor:
    """Fetch a competitor by name, creating it if absent."""
    competitor = session.execute(
        select(Competitor).where(Competitor.name == payload["name"])
    ).scalar_one_or_none()
    if competitor is not None:
        return competitor

    competitor = Competitor(
        name=payload["name"],
        website_url=payload["website_url"],
        description=payload["description"],
        tracking_frequency=payload["tracking_frequency"],
        active=True,
    )
    session.add(competitor)
    session.flush()
    return competitor


def seed(session: Session, *, reset: bool = False, llm_enabled: bool = True) -> DiffStats:
    """Create demo competitors and run the real pipeline over their pages.

    Returns the aggregate funnel measured during seeding.
    """
    if reset:
        clear_demo_data(session)

    competitors: dict[str, Competitor] = {}
    for payload in COMPETITORS:
        competitor = _get_or_create_competitor(session, payload)
        competitors[competitor.name] = competitor
    session.commit()

    pages = tracked_pages()

    # --- Pass 1: store the v1 revision as the baseline snapshot -------------
    tracked_by_url: dict[str, TrackedURL] = {}
    for page in pages:
        competitor = competitors[page["competitor"]]
        tracked = session.execute(
            select(TrackedURL).where(
                TrackedURL.competitor_id == competitor.id, TrackedURL.url == page["url"]
            )
        ).scalar_one_or_none()

        if tracked is None:
            tracked = TrackedURL(
                competitor_id=competitor.id,
                url=page["url"],
                label=page["label"],
                page_type=page["page_type"],
                active=True,
            )
            session.add(tracked)
            session.flush()

        tracked_by_url[page["url"]] = tracked
        baseline = fetch_html_string(page["v1"], url=page["url"])
        snapshot_service.store_snapshot(session, tracked, baseline, source="demo")

    session.commit()
    logger.info("Stored %d baseline snapshots", len(pages))

    # --- Pass 2: scan the v2 revision through the real pipeline -------------
    total = DiffStats()
    per_competitor: dict[str, DiffStats] = {name: DiffStats() for name in competitors}
    for page in pages:
        competitor = competitors[page["competitor"]]
        tracked = tracked_by_url[page["url"]]
        updated = fetch_html_string(page["v2"], url=page["url"])

        outcome = scan_tracked_url(
            session,
            competitor,
            tracked,
            llm_enabled=llm_enabled,
            fetch_result=updated,
        )
        total = total.merge(outcome.stats)
        per_competitor[competitor.name] = per_competitor[competitor.name].merge(outcome.stats)
        logger.info(
            "Seeded %s: %s (%d raw, %d meaningful)",
            page["url"],
            outcome.status,
            outcome.stats.raw_changes,
            outcome.stats.meaningful_changes,
        )

    # Record one scan run per competitor so the dashboard shows a last-scan time.
    from app.database.base import utcnow

    for competitor in competitors.values():
        competitor_stats = per_competitor[competitor.name]
        session.add(
            ScanRun(
                competitor_id=competitor.id,
                started_at=utcnow(),
                finished_at=utcnow(),
                status="completed",
                urls_scanned=sum(1 for p in pages if p["competitor"] == competitor.name),
                raw_changes=competitor_stats.raw_changes,
                noise_changes=competitor_stats.noise_changes,
                meaningful_changes=competitor_stats.meaningful_changes,
                high_impact_changes=competitor_stats.high_impact_changes,
                noise_reduction=competitor_stats.noise_reduction,
            )
        )

    session.commit()
    logger.info(
        "Seeding complete: %d raw, %d noise, %d meaningful, %d high impact (%.1f%% reduction)",
        total.raw_changes,
        total.noise_changes,
        total.meaningful_changes,
        total.high_impact_changes,
        total.noise_reduction,
    )
    return total


def run_seed(*, reset: bool = True, llm_enabled: bool = True) -> DiffStats:
    """Seed the database from a standalone process."""
    init_db()
    with session_scope() as session:
        return seed(session, reset=reset, llm_enabled=llm_enabled)


if __name__ == "__main__":
    from app.config.logging import configure_logging

    configure_logging("INFO")
    stats = run_seed()
    print("\nDemo data seeded. Measured funnel:")
    for key, value in stats.to_dict().items():
        print(f"  {key}: {value}")
