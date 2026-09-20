"""The full evaluation suite behind ``rivalradar evaluate``.

Runs the pipeline over a fixed set of real, historically archived pages and
reports the aggregate funnel.  The numbers it prints are the ones suitable for
a CV — because they come from executing the pipeline, not from an estimate.

The default target set is deliberately varied (docs sites, news, project
homepages, pricing pages) so the measurement is not tuned to one layout.
"""

from __future__ import annotations

from app.config.logging import get_logger
from app.evaluation.runner import EvaluationReport, evaluate_urls, save_report

logger = get_logger(__name__)

# Long-lived sites with dense Wayback coverage.  No competitor claims are made
# about any of them; they are diff-engine test subjects only.
DEFAULT_SUITE: list[str] = [
    "https://www.python.org/",
    "https://www.djangoproject.com/",
    "https://flask.palletsprojects.com/",
    "https://news.ycombinator.com/",
    "https://www.postgresql.org/",
    "https://redis.io/",
    "https://nodejs.org/en",
    "https://kubernetes.io/",
    "https://www.docker.com/",
    "https://fastapi.tiangolo.com/",
    "https://www.sqlite.org/index.html",
    "https://jquery.com/",
]

# Two-year window gives changes room to accumulate.
DEFAULT_FROM = "2023-01-01"
DEFAULT_TO = "2025-01-01"


def run_evaluation_suite(
    *,
    urls: list[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    save: bool = True,
) -> EvaluationReport:
    """Execute the suite and optionally persist the report."""
    targets = urls or DEFAULT_SUITE
    report = evaluate_urls(
        targets,
        from_date=from_date or DEFAULT_FROM,
        to_date=to_date or DEFAULT_TO,
        limit=40,
    )
    report.kind = "suite"

    if save:
        try:
            save_report(report, slug="evaluation_suite")
        except OSError:
            logger.warning("Could not write the evaluation report", exc_info=True)

    return report
