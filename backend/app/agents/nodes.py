"""LangGraph node implementations.

Each node is a pure ``state -> state-fragment`` function so it can be unit
tested in isolation and reordered without touching the others.  Nodes never
raise: failures are appended to ``state["errors"]`` and the graph continues,
because one broken page must not abort a whole scan.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.config.logging import get_logger
from app.diff.engine import diff_html, diff_text
from app.diff.noise import filter_noise, meaningful_only, noise_breakdown
from app.diff.types import DetectedChange, DiffStats
from app.intelligence.analyzer import analyse_changes
from app.intelligence.classifier import classify_changes
from app.intelligence.relevance import score_changes
from app.llm.factory import get_provider
from app.models.entities import Severity
from app.redaction import summarise_error
from app.schemas.llm import ChangeAnalysis

logger = get_logger(__name__)

# Relevance at or above this is "high impact" and worth a founder's attention.
HIGH_IMPACT_THRESHOLD = 70.0
# Changes below this are not worth an LLM call.
LLM_MIN_RELEVANCE = 40.0


def _to_change(payload: dict) -> DetectedChange:
    """Rehydrate a DetectedChange from its dict form in the graph state."""
    return DetectedChange(
        change_type=payload.get("change_type") or payload.get("type", "modified"),
        location=payload.get("location", "body"),
        before=payload.get("before", "") or "",
        after=payload.get("after", "") or "",
        magnitude=float(payload.get("magnitude", 0.0) or 0.0),
        category=payload.get("category", "other"),
        is_noise=bool(payload.get("is_noise", False)),
        noise_reason=payload.get("noise_reason"),
        relevance_score=float(payload.get("relevance_score", 0.0) or 0.0),
        severity=payload.get("severity", Severity.NOISE.value),
        classifier_confidence=float(payload.get("classifier_confidence", 0.0) or 0.0),
        signals=dict(payload.get("signals") or {}),
        evidence=list(payload.get("evidence") or []),
        source_url=payload.get("source_url", "") or "",
    )


def fetch_snapshot(state: dict) -> dict:
    """Validate that the graph was handed a usable snapshot pair.

    The actual network fetch happens in the scan service (it needs a database
    session); this node normalises what it was given and decides whether the
    rest of the graph should run at all.
    """
    current = state.get("current_snapshot") or {}
    previous = state.get("previous_snapshot")

    if not current:
        return {
            "skipped": True,
            "skip_reason": "no current snapshot available",
            "errors": ["fetch_snapshot: missing current snapshot"],
        }

    if previous is None:
        # First ever scan of this page: there is nothing to compare against.
        return {
            "skipped": True,
            "skip_reason": "baseline snapshot captured (no previous snapshot to compare)",
        }

    if previous.get("content_hash") and previous["content_hash"] == current.get("content_hash"):
        return {
            "skipped": True,
            "skip_reason": "No meaningful page change (content hash identical)",
        }

    return {"skipped": False, "skip_reason": None}


def normalize(state: dict) -> dict:
    """Expose the normalised text of both snapshots on the state."""
    if state.get("skipped"):
        return {}
    current = state.get("current_snapshot") or {}
    previous = state.get("previous_snapshot") or {}
    return {
        "normalized_before": previous.get("normalized_text", "") or "",
        "normalized_after": current.get("normalized_text", "") or "",
    }


def diff_snapshots(state: dict) -> dict:
    """Produce raw structural changes between the two snapshots."""
    if state.get("skipped"):
        return {"raw_changes": []}

    current = state.get("current_snapshot") or {}
    previous = state.get("previous_snapshot") or {}
    source_url = current.get("url", "")

    try:
        before_html = previous.get("raw_html") or ""
        after_html = current.get("raw_html") or ""
        if before_html and after_html:
            changes = diff_html(before_html, after_html, source_url=source_url)
        else:
            # Snapshots stored without HTML still diff on their extracted text.
            changes = diff_text(
                state.get("normalized_before", ""),
                state.get("normalized_after", ""),
                source_url=source_url,
            )
    except Exception as exc:  # noqa: BLE001 - a broken page must not kill the scan
        logger.error("Diff failed for %s", source_url, exc_info=True)
        return {"raw_changes": [], "errors": [f"diff_snapshots: {exc}"]}

    logger.info("Detected %d raw changes for %s", len(changes), source_url or "<unknown>")
    return {"raw_changes": [change.to_dict() for change in changes]}


def filter_noise_node(state: dict) -> dict:
    """Annotate every raw change as noise or meaningful."""
    raw = state.get("raw_changes") or []
    if not raw:
        return {"filtered_changes": [], "noise_reasons": {}}

    changes = [_to_change(item) for item in raw]
    try:
        filter_noise(changes)
    except Exception as exc:  # noqa: BLE001
        logger.error("Noise filtering failed", exc_info=True)
        return {"filtered_changes": raw, "errors": [f"filter_noise: {exc}"]}

    dropped = sum(1 for c in changes if c.is_noise)
    logger.info("Noise filter discarded %d of %d raw changes", dropped, len(changes))
    return {
        "filtered_changes": [change.to_dict() for change in changes],
        "noise_reasons": noise_breakdown(changes),
    }


def classify(state: dict) -> dict:
    """Classify the meaningful changes deterministically."""
    filtered = state.get("filtered_changes") or []
    if not filtered:
        return {"classified_changes": []}

    changes = [_to_change(item) for item in filtered]
    survivors = meaningful_only(changes)
    try:
        classify_changes(survivors)
    except Exception as exc:  # noqa: BLE001
        logger.error("Classification failed", exc_info=True)
        return {
            "classified_changes": [c.to_dict() for c in changes],
            "errors": [f"classify: {exc}"],
        }

    # Keep noise entries in the list so the funnel stays countable end to end.
    return {"classified_changes": [change.to_dict() for change in changes]}


def calculate_relevance(state: dict) -> dict:
    """Score every classified change and select the important ones."""
    classified = state.get("classified_changes") or []
    if not classified:
        return {"important_changes": [], "stats": DiffStats().to_dict()}

    changes = [_to_change(item) for item in classified]
    try:
        score_changes(changes)
    except Exception as exc:  # noqa: BLE001
        logger.error("Relevance scoring failed", exc_info=True)
        return {"important_changes": [], "errors": [f"calculate_relevance: {exc}"]}

    important = [
        change
        for change in changes
        if not change.is_noise and change.relevance_score >= LLM_MIN_RELEVANCE
    ]
    important.sort(key=lambda c: c.relevance_score, reverse=True)

    stats = DiffStats.from_changes(changes)
    logger.info(
        "Funnel: %d raw -> %d noise -> %d meaningful -> %d high impact (%.1f%% noise reduction)",
        stats.raw_changes,
        stats.noise_changes,
        stats.meaningful_changes,
        stats.high_impact_changes,
        stats.noise_reduction,
    )
    return {
        "classified_changes": [change.to_dict() for change in changes],
        "important_changes": [change.to_dict() for change in important],
        "stats": stats.to_dict(),
    }


def llm_analysis(state: dict) -> dict:
    """Run LLM analysis over the candidate changes only.

    Cost control lives here and in :func:`analyse_changes`:
    zero candidates means zero LLM calls, which is the common case.
    """
    important = state.get("important_changes") or []

    if not important:
        # Nothing survived filtering — never spend a request on nothing.
        logger.info("No candidate changes; skipping LLM entirely")
        return {"analyses": [], "llm_calls": 0, "llm_status": "skipped"}

    if not state.get("llm_enabled", True):
        return {"analyses": [], "llm_calls": 0, "llm_status": "skipped"}

    competitor = state.get("competitor") or {}
    competitor_name = competitor.get("name", "Competitor")
    changes = [_to_change(item) for item in important]

    try:
        provider = get_provider()
        results = analyse_changes(
            changes,
            competitor_name,
            provider=provider,
            limit=state.get("analysis_limit"),
        )
    except Exception as exc:  # noqa: BLE001 - analyzer already degrades internally
        logger.error("LLM analysis stage failed", exc_info=True)
        return {
            "analyses": [],
            "llm_calls": 0,
            "llm_status": "failed",
            # Type and status only: the message of an LLM-call failure can
            # quote the request's Authorization header.
            "errors": [f"llm_analysis: {summarise_error(exc)}"],
        }

    analyses = [
        {
            "change": result.change.to_dict(),
            "analysis": result.analysis.model_dump(),
            "analysed_by": result.analysed_by,
            "llm_status": result.llm_status,
            "llm_error": result.llm_error,
            "llm_model": (provider.model if result.used_llm else None),
        }
        for result in results
    ]

    llm_calls = sum(1 for r in results if r.used_llm)
    # The worst status across the batch is what the UI should surface.
    statuses = {r.llm_status for r in results}
    for candidate in ("rate_limited", "failed", "budget", "ok", "skipped"):
        if candidate in statuses:
            overall = candidate
            break
    else:  # pragma: no cover - statuses is never empty here
        overall = "skipped"

    logger.info(
        "Analysed %d candidate change(s) for %s (%d via LLM, status=%s)",
        len(analyses),
        competitor_name,
        llm_calls,
        overall,
    )
    return {"analyses": analyses, "llm_calls": llm_calls, "llm_status": overall}


def validate_output(state: dict) -> dict:
    """Validate every LLM analysis before it can become stored intelligence.

    The analyzer already parses responses through Pydantic, but this node is
    the explicit gate in the graph: anything that fails re-validation, invents
    content absent from the diff, or is marked ``is_meaningful=false`` by the
    model is dropped here rather than written to the database.
    """
    analyses = state.get("analyses") or []
    if not analyses:
        return {"analyses": [], "rejected_analyses": 0}

    validated: list[dict] = []
    rejected = 0

    for item in analyses:
        payload = item.get("analysis") or {}
        try:
            analysis = ChangeAnalysis.model_validate(payload)
        except ValidationError as exc:
            rejected += 1
            logger.warning("Dropping analysis that failed validation: %s", exc)
            continue

        # The model explicitly judged this not worth reporting. Trust it to
        # suppress, never to promote — promotion stays deterministic.
        if not analysis.is_meaningful and item.get("llm_status") == "ok":
            rejected += 1
            logger.info("Model marked change as not meaningful: %s", analysis.title)
            continue

        change = item.get("change") or {}
        if _invents_content(analysis, change):
            rejected += 1
            logger.warning(
                "Dropping analysis whose before/after is not grounded in the diff: %s",
                analysis.title,
            )
            continue

        validated.append({**item, "analysis": analysis.model_dump()})

    if rejected:
        logger.info("Validation dropped %d of %d analyses", rejected, len(analyses))
    return {"analyses": validated, "rejected_analyses": rejected}


def _invents_content(analysis: ChangeAnalysis, change: dict) -> bool:
    """True when the model's before/after is not grounded in the actual diff.

    A model on a free tier will occasionally paraphrase or hallucinate the
    values. The observed diff is the source of truth, so a before/after that
    does not appear in it is treated as invented.
    """
    observed_before = (change.get("before") or "").strip()
    observed_after = (change.get("after") or "").strip()

    def grounded(claimed: str | None, observed: str) -> bool:
        if not claimed:
            return True
        claimed = claimed.strip()
        if not claimed or not observed:
            return not claimed
        a, b = claimed.casefold(), observed.casefold()
        return a in b or b in a

    return not (
        grounded(analysis.before, observed_before) and grounded(analysis.after, observed_after)
    )


def generate_intelligence(state: dict) -> dict:
    """Assemble the final intelligence records and recompute the funnel.

    The LLM may have nudged relevance scores, so the high-impact count is
    recalculated here from the post-analysis scores.
    """
    analyses = state.get("analyses") or []
    competitor = state.get("competitor") or {}

    intelligence: list[dict] = []
    for item in analyses:
        analysis = item.get("analysis") or {}
        change = item.get("change") or {}
        score = float(analysis.get("relevance_score", change.get("relevance_score", 0.0)))
        intelligence.append(
            {
                "competitor_id": competitor.get("id"),
                "competitor_name": competitor.get("name", "Competitor"),
                "title": analysis.get("title", ""),
                "category": analysis.get("category", change.get("category", "other")),
                "summary": analysis.get("summary", ""),
                "before": analysis.get("before") or change.get("before"),
                "after": analysis.get("after") or change.get("after"),
                "business_impact": analysis.get("business_impact", ""),
                "recommended_action": analysis.get("recommended_action"),
                "relevance_score": score,
                "severity": Severity.from_score(score).value,
                "confidence": float(analysis.get("confidence", 0.5)),
                "analysed_by": item.get("analysed_by", "deterministic"),
                "llm_status": item.get("llm_status", "skipped"),
                "llm_error": item.get("llm_error"),
                "llm_model": item.get("llm_model"),
                "source_url": change.get("source_url", ""),
                "change": change,
            }
        )

    stats = dict(state.get("stats") or {})
    if intelligence:
        stats["high_impact_changes"] = sum(
            1 for i in intelligence if i["relevance_score"] >= HIGH_IMPACT_THRESHOLD
        )

    intelligence.sort(key=lambda i: i["relevance_score"], reverse=True)
    return {"intelligence": intelligence, "stats": stats}


def store_result(state: dict) -> dict:
    """Terminal node.

    Database writes happen in the scan service, which owns the session; this
    node finalises the funnel numbers that callers read off the state.
    """
    stats = dict(state.get("stats") or {})
    if state.get("skipped") and not stats:
        stats = DiffStats().to_dict()
        stats["skipped"] = True
        stats["skip_reason"] = state.get("skip_reason")
    return {"stats": stats}
