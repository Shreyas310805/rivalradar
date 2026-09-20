"""Evaluation harness.

Runs the real pipeline over real historical web pages and reports the funnel.
Every number in a report is counted from actual execution — nothing here
invents or extrapolates a metric.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.config.logging import get_logger
from app.config.settings import settings
from app.diff.engine import diff_html
from app.diff.noise import filter_noise, noise_breakdown
from app.diff.types import DetectedChange, DiffStats
from app.intelligence.classifier import classify_changes
from app.intelligence.relevance import score_changes
from app.models.entities import ChangeCategory
from app.services.wayback import (
    WaybackError,
    download_snapshot,
    list_snapshots_spread,
    select_snapshot_pair,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class PageEvaluation:
    """Funnel measured for one page comparison."""

    url: str
    snapshot_a: str = ""
    snapshot_b: str = ""
    date_a: str = ""
    date_b: str = ""
    stats: DiffStats = field(default_factory=DiffStats)
    categories: dict[str, int] = field(default_factory=dict)
    noise_reasons: dict[str, int] = field(default_factory=dict)
    top_changes: list[dict] = field(default_factory=list)
    status: str = "completed"
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "snapshot_a": self.snapshot_a,
            "snapshot_b": self.snapshot_b,
            "date_a": self.date_a,
            "date_b": self.date_b,
            "status": self.status,
            "error": self.error,
            **self.stats.to_dict(),
            "categories": self.categories,
            "noise_reasons": self.noise_reasons,
            "top_changes": self.top_changes,
        }


@dataclass(slots=True)
class EvaluationReport:
    """Aggregate result across every evaluated page."""

    kind: str = "wayback"
    targets: list[str] = field(default_factory=list)
    pages: list[PageEvaluation] = field(default_factory=list)
    generated_at: str = ""

    @property
    def successful_pages(self) -> list[PageEvaluation]:
        return [page for page in self.pages if page.status == "completed"]

    @property
    def stats(self) -> DiffStats:
        """Funnel summed across successfully evaluated pages."""
        total = DiffStats()
        for page in self.successful_pages:
            total = total.merge(page.stats)
        return total

    @property
    def categories(self) -> dict[str, int]:
        merged: dict[str, int] = {}
        for page in self.successful_pages:
            for category, count in page.categories.items():
                merged[category] = merged.get(category, 0) + count
        return dict(sorted(merged.items(), key=lambda item: item[1], reverse=True))

    @property
    def noise_reasons(self) -> dict[str, int]:
        merged: dict[str, int] = {}
        for page in self.successful_pages:
            for reason, count in page.noise_reasons.items():
                merged[reason] = merged.get(reason, 0) + count
        return dict(sorted(merged.items(), key=lambda item: item[1], reverse=True))

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "generated_at": self.generated_at,
            "targets": self.targets,
            "pages_evaluated": len(self.successful_pages),
            "pages_failed": len(self.pages) - len(self.successful_pages),
            **self.stats.to_dict(),
            "categories": self.categories,
            "noise_reasons": self.noise_reasons,
            "pages": [page.to_dict() for page in self.pages],
        }


def evaluate_html_pair(
    before_html: str,
    after_html: str,
    *,
    url: str = "",
    top_n: int = 5,
) -> tuple[DiffStats, list[DetectedChange]]:
    """Run the deterministic pipeline over two documents.

    The LLM is deliberately not involved: the funnel must be reproducible and
    free, so evaluation measures the deterministic detection layer.
    """
    changes = diff_html(before_html, after_html, source_url=url)
    filter_noise(changes)
    classify_changes([c for c in changes if not c.is_noise])
    score_changes(changes)
    del top_n
    return DiffStats.from_changes(changes), changes


def _category_counts(changes: list[DetectedChange]) -> dict[str, int]:
    """Count meaningful changes per category, including empty buckets."""
    counts = {category.value: 0 for category in ChangeCategory}
    for change in changes:
        if not change.is_noise:
            counts[change.category] = counts.get(change.category, 0) + 1
    return {name: count for name, count in counts.items() if count}


def _top_changes(changes: list[DetectedChange], limit: int = 5) -> list[dict]:
    """Highest-scoring meaningful changes, for the report body."""
    meaningful = sorted(
        (c for c in changes if not c.is_noise),
        key=lambda c: c.relevance_score,
        reverse=True,
    )
    return [
        {
            "category": change.category,
            "location": change.location,
            "before": (change.before or "")[:200],
            "after": (change.after or "")[:200],
            "relevance_score": change.relevance_score,
            "severity": change.severity,
            "evidence": list(dict.fromkeys(change.evidence))[:3],
        }
        for change in meaningful[:limit]
    ]


def evaluate_wayback_url(
    url: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 40,
) -> PageEvaluation:
    """Evaluate one URL against a pair of its Wayback captures."""
    page = PageEvaluation(url=url)

    try:
        snapshots = list_snapshots_spread(url, from_date=from_date, to_date=to_date, limit=limit)
        if not snapshots:
            page.status = "no_snapshots"
            page.error = "no archived snapshots in the requested window"
            logger.warning("No Wayback snapshots for %s", url)
            return page

        older, newer = select_snapshot_pair(snapshots)
        page.snapshot_a, page.snapshot_b = older.timestamp, newer.timestamp
        page.date_a, page.date_b = older.iso_date, newer.iso_date

        before_html = download_snapshot(older)
        after_html = download_snapshot(newer)
    except WaybackError as exc:
        page.status = "failed"
        page.error = str(exc)
        logger.warning("Wayback evaluation failed for %s: %s", url, exc)
        return page
    except Exception as exc:  # noqa: BLE001 - evaluation must never crash
        page.status = "failed"
        page.error = f"unexpected error: {exc}"
        logger.error("Unexpected Wayback failure for %s", url, exc_info=True)
        return page

    try:
        stats, changes = evaluate_html_pair(before_html, after_html, url=url)
    except Exception as exc:  # noqa: BLE001
        page.status = "failed"
        page.error = f"pipeline error: {exc}"
        logger.error("Pipeline failed on %s", url, exc_info=True)
        return page

    page.stats = stats
    page.categories = _category_counts(changes)
    page.noise_reasons = noise_breakdown(changes)
    page.top_changes = _top_changes(changes)

    logger.info(
        "%s (%s -> %s): %d raw, %d noise, %d meaningful, %d high impact (%.1f%% reduction)",
        url,
        page.date_a,
        page.date_b,
        stats.raw_changes,
        stats.noise_changes,
        stats.meaningful_changes,
        stats.high_impact_changes,
        stats.noise_reduction,
    )
    return page


def evaluate_urls(
    urls: list[str],
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 40,
) -> EvaluationReport:
    """Evaluate several URLs and aggregate the funnel."""
    report = EvaluationReport(
        targets=list(urls), generated_at=datetime.now(UTC).isoformat(timespec="seconds")
    )
    for url in urls:
        report.pages.append(
            evaluate_wayback_url(url, from_date=from_date, to_date=to_date, limit=limit)
        )
    return report


def format_report(report: EvaluationReport, *, title: str = "Wayback Evaluation") -> str:
    """Render a report as the plain-text document stored in data/reports/."""
    stats = report.stats
    lines: list[str] = [
        title,
        "=" * len(title),
        "",
        f"Generated: {report.generated_at}",
        f"Pages evaluated: {len(report.successful_pages)}",
    ]

    failed = [page for page in report.pages if page.status != "completed"]
    if failed:
        lines.append(f"Pages skipped/failed: {len(failed)}")

    lines.extend(["", "FUNNEL", "-" * 40])
    lines.extend(
        [
            f"Raw changes:          {stats.raw_changes}",
            f"Noise removed:        {stats.noise_changes}",
            f"Meaningful changes:   {stats.meaningful_changes}",
            f"High-impact changes:  {stats.high_impact_changes}",
            "",
            f"Noise reduction:      {stats.noise_reduction}%",
        ]
    )

    categories = report.categories
    if categories:
        lines.extend(["", "DETECTION CATEGORIES", "-" * 40])
        lines.extend(f"{name.capitalize():<16}{count}" for name, count in categories.items())

    noise_reasons = report.noise_reasons
    if noise_reasons:
        lines.extend(["", "WHY CHANGES WERE FILTERED", "-" * 40])
        lines.extend(f"{count:>5}  {reason}" for reason, count in noise_reasons.items())

    lines.extend(["", "PER-PAGE RESULTS", "-" * 40])
    for page in report.pages:
        lines.append("")
        lines.append(f"Website: {page.url}")
        if page.status != "completed":
            lines.append(f"  Status: {page.status} ({page.error})")
            continue
        lines.append(f"  Snapshot: {page.date_a} -> {page.date_b}")
        lines.append(
            f"  Raw {page.stats.raw_changes} | noise {page.stats.noise_changes} | "
            f"meaningful {page.stats.meaningful_changes} | "
            f"high-impact {page.stats.high_impact_changes} | "
            f"reduction {page.stats.noise_reduction}%"
        )
        for change in page.top_changes[:3]:
            before = (change["before"] or "")[:60]
            after = (change["after"] or "")[:60]
            lines.append(
                f"    [{change['category']}/{change['severity']} "
                f"{change['relevance_score']:.0f}] {before!r} -> {after!r}"
            )

    lines.append("")
    return "\n".join(lines)


def save_report(report: EvaluationReport, *, slug: str = "wayback") -> tuple[Path, Path]:
    """Write the report to ``data/reports/`` as both text and JSON."""
    settings.ensure_directories()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    base = settings.reports_dir / f"{slug}_{stamp}"

    text_path = base.with_suffix(".txt")
    json_path = base.with_suffix(".json")

    text_path.write_text(format_report(report), encoding="utf-8")
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    logger.info("Evaluation report written to %s", text_path)
    return text_path, json_path
