"""Weekly competitive-intelligence digest generation.

The digest is assembled from intelligence records already in the database.  The
funnel counters are summed from stored ``Change`` rows, so the analytics block
at the bottom of every digest reports measured values, never estimates.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.database.base import utcnow
from app.diff.types import DiffStats
from app.llm.base import LLMError, LLMProvider
from app.llm.factory import get_provider
from app.llm.heuristic_provider import HeuristicProvider
from app.models.entities import Change, Competitor, Digest, Intelligence
from app.schemas.llm import DigestNarrative

logger = get_logger(__name__)

HIGH_IMPACT_THRESHOLD = 70.0
MAX_HIGHLIGHTS = 8

SYSTEM_PROMPT = """You are a competitive intelligence analyst writing a weekly briefing
for a startup founder. You are given the important competitor changes detected this period.

Write a short, factual briefing. Do not invent changes that are not in the input.
Respond with a single JSON object:
{
  "headline": "one sentence summarising the period",
  "highlights": [
    {"competitor": "...", "category": "...", "headline": "...", "detail": "...", "impact": "..."}
  ],
  "outlook": "two sentences on what to watch next"
}"""


def _period_bounds(days: int, end: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the (start, end) datetimes for a digest period."""
    period_end = end or utcnow()
    return period_end - timedelta(days=days), period_end


def collect_period_stats(
    session: Session,
    period_start: datetime,
    period_end: datetime,
    *,
    competitor_id: int | None = None,
) -> DiffStats:
    """Sum the change funnel over a period, straight from stored rows."""
    filters = [Change.detected_at >= period_start, Change.detected_at <= period_end]
    if competitor_id is not None:
        filters.append(Change.competitor_id == competitor_id)

    row = session.execute(
        select(
            func.count(Change.id),
            func.sum(func.cast(Change.is_noise, Integer)),
            func.sum(func.cast(Change.relevance_score >= HIGH_IMPACT_THRESHOLD, Integer)),
        ).where(*filters)
    ).one()

    raw = int(row[0] or 0)
    noise = int(row[1] or 0)
    high = int(row[2] or 0)
    return DiffStats(
        raw_changes=raw,
        noise_changes=noise,
        meaningful_changes=raw - noise,
        high_impact_changes=high,
    )


def collect_highlights(
    session: Session,
    period_start: datetime,
    period_end: datetime,
    *,
    competitor_id: int | None = None,
    limit: int = MAX_HIGHLIGHTS,
) -> list[dict]:
    """Fetch the top intelligence records for a period."""
    filters = [Intelligence.created_at >= period_start, Intelligence.created_at <= period_end]
    if competitor_id is not None:
        filters.append(Intelligence.competitor_id == competitor_id)

    rows = session.execute(
        select(Intelligence, Competitor.name)
        .join(Competitor, Competitor.id == Intelligence.competitor_id)
        .where(*filters)
        .order_by(Intelligence.relevance_score.desc(), Intelligence.created_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "competitor": name,
            "category": intel.category,
            "title": intel.title,
            "summary": intel.summary,
            "business_impact": intel.business_impact,
            "before": intel.before,
            "after": intel.after,
            "relevance_score": intel.relevance_score,
            "severity": intel.severity,
            "confidence": intel.confidence,
        }
        for intel, name in rows
    ]


def _generate_narrative(
    items: list[dict], stats: DiffStats, *, provider: LLMProvider | None = None
) -> tuple[DigestNarrative, str]:
    """Produce the prose portion, degrading to templates on any failure."""
    provider = provider or get_provider()
    context = {"task": "digest", "items": items, "stats": stats.to_dict()}

    user_prompt = (
        f"Period funnel: {json.dumps(stats.to_dict())}\n\n"
        f"Important changes detected ({len(items)}):\n"
        + "\n".join(
            f"- [{item['competitor']} / {item['category']} / "
            f"score {item['relevance_score']:.0f}] {item['title']}: {item['summary']}"
            for item in items
        )
    )

    try:
        payload = provider.complete_json(
            system=SYSTEM_PROMPT, user=user_prompt, max_tokens=1400, context=context
        )
        return DigestNarrative.model_validate(payload), provider.name
    except (LLMError, ValidationError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Digest LLM generation failed (%s); using heuristic fallback", exc)
    except Exception:  # noqa: BLE001
        logger.error("Unexpected digest LLM failure; using heuristic fallback", exc_info=True)

    fallback = HeuristicProvider()
    payload = fallback.complete_json(system=SYSTEM_PROMPT, user=user_prompt, context=context)
    return DigestNarrative.model_validate(payload), fallback.name


def render_digest(
    narrative: DigestNarrative,
    items: list[dict],
    stats: DiffStats,
    period_start: datetime,
    period_end: datetime,
) -> str:
    """Render the digest as the plain-text report shown in the UI."""
    divider = "━" * 46
    # %-d is not portable (it fails on Windows), so day numbers are formatted
    # with plain int conversion instead.
    if period_start.month == period_end.month and period_start.year == period_end.year:
        date_range = (
            f"{period_start.strftime('%B')} {period_start.day}–"
            f"{period_end.day}, {period_end.year}"
        )
    else:
        date_range = (
            f"{period_start.strftime('%B')} {period_start.day} – "
            f"{period_end.strftime('%B')} {period_end.day}, {period_end.year}"
        )

    lines = [
        "RIVALRADAR",
        "Weekly Competitive Intelligence",
        date_range,
        "",
        divider,
        "",
    ]

    high_impact = [item for item in items if item["relevance_score"] >= HIGH_IMPACT_THRESHOLD]
    headline_items = high_impact or items

    if headline_items:
        noun = "IMPORTANT MOVE" if len(headline_items) == 1 else "IMPORTANT MOVES"
        lines.append(f"{len(headline_items)} {noun}")
        lines.append("")
        for index, item in enumerate(headline_items[:MAX_HIGHLIGHTS], start=1):
            lines.append(f"{index:02d} — {item['competitor']}")
            lines.append(item["category"].capitalize())
            lines.append(item["title"])
            if item.get("before") and item.get("after"):
                lines.append(f"{item['before']} → {item['after']}")
            lines.append("")
            if item.get("business_impact"):
                lines.append("Impact:")
                lines.append(item["business_impact"])
                lines.append("")
            lines.append(
                f"Relevance: {item['relevance_score']:.0f}/100  "
                f"Confidence: {item['confidence'] * 100:.0f}%"
            )
            lines.append("")
    else:
        lines.append("NO IMPORTANT MOVES DETECTED THIS PERIOD")
        lines.append("")

    lines.extend([divider, "", "CHANGE ANALYTICS", ""])
    lines.extend(
        [
            f"Raw changes detected:  {stats.raw_changes}",
            f"Filtered as noise:     {stats.noise_changes}",
            f"Meaningful changes:    {stats.meaningful_changes}",
            f"High-impact changes:   {stats.high_impact_changes}",
            "",
            f"Noise reduction:       {stats.noise_reduction}%",
            "",
        ]
    )

    if narrative.outlook:
        lines.extend([divider, "", "OUTLOOK", "", narrative.outlook, ""])

    return "\n".join(lines)


def generate_digest(
    session: Session,
    *,
    days: int = 7,
    competitor_id: int | None = None,
    provider: LLMProvider | None = None,
    persist: bool = True,
) -> Digest:
    """Generate (and optionally store) a digest for the last ``days`` days."""
    period_start, period_end = _period_bounds(days)

    stats = collect_period_stats(session, period_start, period_end, competitor_id=competitor_id)
    items = collect_highlights(session, period_start, period_end, competitor_id=competitor_id)
    narrative, generated_by = _generate_narrative(items, stats, provider=provider)
    content = render_digest(narrative, items, stats, period_start, period_end)

    digest = Digest(
        period_start=period_start,
        period_end=period_end,
        title=f"Weekly Competitive Intelligence ({period_start:%Y-%m-%d} to {period_end:%Y-%m-%d})",
        content=content,
        headline=narrative.headline,
        raw_changes=stats.raw_changes,
        noise_changes=stats.noise_changes,
        meaningful_changes=stats.meaningful_changes,
        high_impact_changes=stats.high_impact_changes,
        noise_reduction=stats.noise_reduction,
        generated_by=generated_by,
    )

    if persist:
        session.add(digest)
        session.commit()
        session.refresh(digest)
        logger.info(
            "Generated digest %d covering %d changes (%.1f%% noise reduction)",
            digest.id,
            stats.raw_changes,
            stats.noise_reduction,
        )
    return digest


def get_latest_digest(session: Session) -> Digest | None:
    """Return the most recently generated digest."""
    return session.execute(
        select(Digest).order_by(Digest.created_at.desc(), Digest.id.desc()).limit(1)
    ).scalar_one_or_none()
