"""Scheduled competitor checks via APScheduler.

Each competitor is scanned at its own ``tracking_frequency``; a nightly job
regenerates the weekly digest.  The scheduler is opt-in
(``SCHEDULER_ENABLED=true``) so running the API locally never starts hitting
the network on its own.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config.logging import get_logger
from app.config.settings import settings
from app.database.session import session_scope
from app.models.entities import Competitor, TrackingFrequency

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None


def scan_due_competitors() -> None:
    """Scan every active competitor whose frequency is due.

    Runs on the scheduler thread, so it owns its own session and swallows all
    exceptions: a scheduled job must never take the process down.
    """
    from app.services.scan import scan_competitor

    try:
        with session_scope() as session:
            competitors = (
                session.query(Competitor)
                .filter(Competitor.active.is_(True))
                .filter(Competitor.tracking_frequency != TrackingFrequency.MANUAL.value)
                .all()
            )
            logger.info("Scheduled scan starting for %d competitor(s)", len(competitors))
            for competitor in competitors:
                try:
                    outcome = scan_competitor(session, competitor)
                    logger.info(
                        "Scheduled scan of %s: %d raw changes, %.1f%% noise reduction",
                        competitor.name,
                        outcome.stats.raw_changes,
                        outcome.stats.noise_reduction,
                    )
                except Exception:  # noqa: BLE001
                    logger.error(
                        "Scheduled scan failed for %s", competitor.name, exc_info=True
                    )
                    session.rollback()
    except Exception:  # noqa: BLE001
        logger.error("Scheduled scan job failed", exc_info=True)


def generate_weekly_digest() -> None:
    """Generate the weekly digest."""
    from app.intelligence.digest import generate_digest

    try:
        with session_scope() as session:
            digest = generate_digest(session, days=7)
            logger.info("Scheduled digest %d generated", digest.id)
    except Exception:  # noqa: BLE001
        logger.error("Scheduled digest generation failed", exc_info=True)


def start_scheduler() -> BackgroundScheduler | None:
    """Start the background scheduler if enabled."""
    global _scheduler

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled (set SCHEDULER_ENABLED=true to enable)")
        return None

    if _scheduler is not None and _scheduler.running:
        return _scheduler

    scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )

    scheduler.add_job(
        scan_due_competitors,
        trigger=IntervalTrigger(minutes=settings.scheduler_interval_minutes),
        id="scan_due_competitors",
        name="Scan due competitors",
        replace_existing=True,
    )
    scheduler.add_job(
        generate_weekly_digest,
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="weekly_digest",
        name="Generate weekly digest",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started: scans every %d minutes, digest every Monday 07:00 UTC",
        settings.scheduler_interval_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    """Stop the scheduler cleanly."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None


def get_scheduler() -> BackgroundScheduler | None:
    """Return the running scheduler, if any."""
    return _scheduler
