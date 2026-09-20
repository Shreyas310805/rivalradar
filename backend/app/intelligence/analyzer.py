"""LLM analysis of candidate changes.

Only changes that survived noise filtering *and* scored above
``LLM_MIN_RELEVANCE`` reach this module. Everything else would be wasted
tokens — which matters because the default provider is a rate-limited free
tier.

The LLM's job is interpretation (what does this move mean commercially), not
detection and not scoring: the final relevance score is the deterministic one,
adjusted by at most a bounded amount.

Every analysis carries an ``llm_status`` recording what actually happened:

``ok``          the model answered and the response validated
``skipped``     no LLM configured; deterministic analysis was used
``failed``      the model was called and errored (rate limit, timeout, bad JSON)
``rate_limited``the free tier throttled us
``budget``      the per-scan call ceiling was reached
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.config.logging import get_logger
from app.config.settings import settings
from app.diff.types import DetectedChange
from app.intelligence.relevance import blend_with_llm_score
from app.llm.base import LLMError, LLMProvider
from app.llm.factory import get_provider
from app.llm.heuristic_provider import HeuristicProvider
from app.llm.openrouter_provider import OpenRouterRateLimited
from app.models.entities import Severity
from app.schemas.llm import ChangeAnalysis

logger = get_logger(__name__)

# llm_status values, kept as constants so the API and UI agree.
STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_BUDGET = "budget"

SYSTEM_PROMPT = """You are a competitive intelligence analyst working for a startup founder.
You are given ONE change detected on a competitor's website, already filtered and classified
by a deterministic pipeline.

Your job is to decide whether the change matters commercially, and explain why.

HARD RULES — these are absolute:
- Use ONLY the BEFORE and AFTER content provided below. Nothing else.
- NEVER invent prices, dates, product names, company facts or numbers.
- If a value is not present in BEFORE/AFTER, do not state it.
- If the evidence is thin, set is_meaningful to false and lower your confidence.
- Keep summary under 60 words and business_impact under 60 words.
- Respond with a single JSON object and nothing else. No markdown, no prose.

Required JSON shape:
{
  "is_meaningful": true or false,
  "title": "short headline, max 12 words",
  "category": "pricing|features|product|hiring|integrations|messaging|other",
  "summary": "what concretely changed, quoting the given content",
  "before": "the prior value, copied from BEFORE, or null",
  "after": "the new value, copied from AFTER, or null",
  "business_impact": "why a founder should care",
  "recommended_action": "one concrete next step, or null",
  "relevance_score": 0-100,
  "confidence": 0.0-1.0
}"""


@dataclass(slots=True)
class AnalysisResult:
    """One analysed change plus provenance of how it was analysed."""

    change: DetectedChange
    analysis: ChangeAnalysis
    analysed_by: str
    llm_status: str
    llm_error: str | None = None

    @property
    def used_llm(self) -> bool:
        return self.llm_status == STATUS_OK


def _build_context(change: DetectedChange, competitor_name: str) -> dict:
    """Assemble the structured facts shared by the prompt and the fallback."""
    return {
        "task": "analysis",
        "competitor_name": competitor_name,
        "category": change.category,
        "change_type": change.change_type,
        "location": change.location,
        "before": change.before,
        "after": change.after,
        "magnitude": round(change.magnitude, 3),
        "deterministic_score": change.relevance_score,
        "classifier_confidence": change.classifier_confidence,
        "signals": dict(change.signals),
        "evidence": list(dict.fromkeys(change.evidence)),
        "source_url": change.source_url,
    }


def _build_user_prompt(context: dict) -> str:
    """Render the structured facts into the user message."""
    return (
        f"Competitor: {context['competitor_name']}\n"
        f"Page section: {context['location']}\n"
        f"Source URL: {context['source_url'] or 'n/a'}\n"
        f"Deterministic classification: {context['category']} "
        f"(confidence {context['classifier_confidence']:.2f})\n"
        f"Deterministic relevance score: {context['deterministic_score']:.1f}/100\n"
        f"Change magnitude: {context['magnitude']:.2f}\n"
        f"Detected signals: {json.dumps(context['signals'], default=str)}\n"
        f"Rule-based evidence: {'; '.join(context['evidence']) or 'none'}\n\n"
        f"BEFORE:\n{context['before'] or '(nothing)'}\n\n"
        f"AFTER:\n{context['after'] or '(nothing)'}\n"
    )


def _deterministic_analysis(
    context: dict, change: DetectedChange, competitor_name: str
) -> ChangeAnalysis:
    """Render analysis from extracted signals only — no network, no invention."""
    fallback = HeuristicProvider()
    try:
        payload = fallback.complete_json(system=SYSTEM_PROMPT, user="", context=context)
        return ChangeAnalysis.model_validate(payload)
    except Exception:  # pragma: no cover - the fallback is pure templating
        logger.error("Deterministic analysis failed; emitting minimal record", exc_info=True)
        return ChangeAnalysis(
            title=f"{competitor_name} page change",
            category=change.category,
            summary=f"Change detected in {change.location}.",
            before=change.before or None,
            after=change.after or None,
            business_impact="Unable to analyse automatically.",
            relevance_score=change.relevance_score,
            confidence=0.2,
        )


def analyse_change(
    change: DetectedChange,
    competitor_name: str,
    *,
    provider: LLMProvider | None = None,
) -> AnalysisResult:
    """Analyse one change.

    Never raises. A provider failure is recorded as ``llm_status='failed'``
    and deterministic analysis takes over, so a rate limit degrades the
    quality of the writing without losing the detection.
    """
    provider = provider or get_provider()
    context = _build_context(change, competitor_name)
    user_prompt = _build_user_prompt(context)

    is_llm_provider = provider.name not in {"deterministic", "heuristic"}

    # No LLM configured: do not pretend one ran.
    if not is_llm_provider:
        analysis = _deterministic_analysis(context, change, competitor_name)
        return _finalise(change, analysis, "deterministic", STATUS_SKIPPED, None)

    try:
        payload = provider.complete_json(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            context=context,
            max_tokens=settings.llm_max_tokens,
        )
        analysis = ChangeAnalysis.model_validate(payload)
        return _finalise(change, analysis, provider.name, STATUS_OK, None)

    except OpenRouterRateLimited as exc:
        logger.warning("LLM rate limited; using deterministic analysis: %s", exc)
        status, error = STATUS_RATE_LIMITED, str(exc)
    except (LLMError, ValidationError, ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "LLM analysis failed for %s change (%s); using deterministic analysis: %s",
            change.category,
            competitor_name,
            exc,
        )
        status, error = STATUS_FAILED, str(exc)
    except Exception as exc:  # noqa: BLE001 - never let a scan die here
        logger.error("Unexpected LLM failure; using deterministic analysis", exc_info=True)
        status, error = STATUS_FAILED, str(exc)

    analysis = _deterministic_analysis(context, change, competitor_name)
    return _finalise(change, analysis, "deterministic", status, error)


def _finalise(
    change: DetectedChange,
    analysis: ChangeAnalysis,
    analysed_by: str,
    status: str,
    error: str | None,
) -> AnalysisResult:
    """Apply scoring policy and package the result."""
    # The deterministic score stays in charge; the model may nudge it only.
    analysis.relevance_score = blend_with_llm_score(
        change.relevance_score, analysis.relevance_score
    )
    # The deterministic classifier owns the category unless it had no opinion.
    if change.category != "other":
        analysis.category = change.category

    return AnalysisResult(
        change=change,
        analysis=analysis,
        analysed_by=analysed_by,
        llm_status=status,
        llm_error=(error or None),
    )


def analyse_changes(
    changes: list[DetectedChange],
    competitor_name: str,
    *,
    provider: LLMProvider | None = None,
    limit: int | None = None,
    min_relevance: float | None = None,
) -> list[AnalysisResult]:
    """Analyse candidate changes, highest relevance first.

    Cost control, in order:

    1. changes below ``min_relevance`` never reach the model,
    2. at most ``limit`` changes are sent per scan,
    3. once the provider rate-limits or fails hard, the remaining changes go
       straight to deterministic analysis instead of hammering the endpoint.
    """
    if not changes:
        return []

    provider = provider or get_provider()
    threshold = settings.llm_min_relevance if min_relevance is None else min_relevance
    budget = settings.llm_max_calls_per_scan if limit is None else limit

    ordered = sorted(changes, key=lambda c: c.relevance_score, reverse=True)
    results: list[AnalysisResult] = []

    calls_made = 0
    provider_down = False

    for change in ordered:
        below_threshold = change.relevance_score < threshold
        out_of_budget = calls_made >= budget

        if provider_down or below_threshold or out_of_budget:
            context = _build_context(change, competitor_name)
            analysis = _deterministic_analysis(context, change, competitor_name)
            status = (
                STATUS_BUDGET
                if (out_of_budget and not provider_down and not below_threshold)
                else STATUS_SKIPPED
            )
            results.append(_finalise(change, analysis, "deterministic", status, None))
            continue

        result = analyse_change(change, competitor_name, provider=provider)
        if result.llm_status in {STATUS_OK, STATUS_FAILED, STATUS_RATE_LIMITED}:
            calls_made += 1
        # Stop calling a provider that is throttling or erroring.
        if result.llm_status in {STATUS_RATE_LIMITED, STATUS_FAILED}:
            provider_down = True
            logger.info(
                "Pausing LLM calls for the rest of this scan (%s)", result.llm_status
            )
        results.append(result)

    # Keep the change objects consistent with the final scores.
    for result in results:
        result.change.relevance_score = result.analysis.relevance_score
        result.change.severity = Severity.from_score(result.analysis.relevance_score).value

    llm_used = sum(1 for r in results if r.used_llm)
    logger.info(
        "Analysed %d change(s): %d via LLM, %d deterministic (budget %d, threshold %.0f)",
        len(results),
        llm_used,
        len(results) - llm_used,
        budget,
        threshold,
    )
    return results
