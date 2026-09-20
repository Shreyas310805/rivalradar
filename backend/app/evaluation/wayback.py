"""CLI entry point for the Wayback evaluation.

Usage::

    python -m app.evaluation.wayback --url https://example.com
    python -m app.evaluation.wayback --url https://a.com --url https://b.com
    python -m app.evaluation.wayback --url https://example.com --from 2024-01-01 --to 2024-12-31

The same code backs ``rivalradar wayback`` and ``POST /api/evaluation/wayback``.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config.logging import configure_logging, get_logger
from app.config.settings import settings
from app.evaluation.runner import EvaluationReport, evaluate_urls, format_report, save_report

logger = get_logger(__name__)

# Sites with long, stable archive histories, used when no --url is supplied.
DEFAULT_TARGETS = [
    "https://www.python.org/",
    "https://news.ycombinator.com/",
    "https://www.djangoproject.com/",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation.wayback",
        description="Benchmark the RivalRadar diff pipeline against Internet Archive snapshots.",
    )
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        metavar="URL",
        help="URL to evaluate; repeat for several. Defaults to a built-in set.",
    )
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", help="earliest capture")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", help="latest capture")
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="max CDX rows to consider per URL (default: 40)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--no-save", action="store_true", help="do not write to data/reports/")
    parser.add_argument("--quiet", action="store_true", help="suppress progress logging")
    return parser


def persist_to_database(report: EvaluationReport, report_path: str | None) -> None:
    """Store aggregate results so the API can serve past evaluations."""
    try:
        from app.database.session import init_db, session_scope
        from app.models.entities import Evaluation

        init_db()
        stats = report.stats
        first = report.successful_pages[0] if report.successful_pages else None
        with session_scope() as session:
            session.add(
                Evaluation(
                    kind=report.kind,
                    target_url=", ".join(report.targets)[:2000],
                    snapshot_a=first.snapshot_a if first else None,
                    snapshot_b=first.snapshot_b if first else None,
                    pages_evaluated=len(report.successful_pages),
                    raw_changes=stats.raw_changes,
                    noise_changes=stats.noise_changes,
                    meaningful_changes=stats.meaningful_changes,
                    high_impact_changes=stats.high_impact_changes,
                    noise_reduction=stats.noise_reduction,
                    category_breakdown=json.dumps(report.categories),
                    report_path=report_path,
                    status="completed" if report.successful_pages else "failed",
                    error=None if report.successful_pages else "no pages evaluated",
                )
            )
    except Exception:  # noqa: BLE001 - reporting must not fail on a DB problem
        logger.warning("Could not persist evaluation to the database", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging("WARNING" if args.quiet else settings.log_level)

    urls = args.urls or DEFAULT_TARGETS
    if not args.quiet:
        print(f"Evaluating {len(urls)} URL(s) against the Wayback Machine...\n", flush=True)

    report = evaluate_urls(
        urls, from_date=args.from_date, to_date=args.to_date, limit=args.limit
    )

    report_path: str | None = None
    if not args.no_save:
        text_path, _ = save_report(report)
        report_path = str(text_path)

    persist_to_database(report, report_path)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))
        if report_path:
            print(f"Report saved to: {report_path}")

    # Non-zero exit when nothing could be evaluated, so CI can catch it.
    return 0 if report.successful_pages else 1


if __name__ == "__main__":
    sys.exit(main())
