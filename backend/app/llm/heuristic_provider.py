"""Offline, deterministic provider used when no LLM API key is configured.

This is not a fake LLM.  It is a template engine driven entirely by the
numeric signals the deterministic classifier already extracted (actual price
values, actual role counts, actual partner names).  It never invents a fact
that is not present in the diff, which is exactly what makes the evaluation
numbers citable: the funnel is measured with or without a model in the loop.

Trade-off, stated plainly: prose quality is lower than a real LLM and it
cannot read nuance ("we are sunsetting X").  Set ``OPENROUTER_API_KEY`` for that.
"""

from __future__ import annotations

import json

from app.config.logging import get_logger
from app.llm.base import LLMProvider, LLMResponse
from app.models.entities import ChangeCategory

logger = get_logger(__name__)

# Phrasing per category, chosen by which signals actually fired.
_IMPACT_TEMPLATES: dict[str, str] = {
    ChangeCategory.PRICING.value: (
        "Pricing moves change the deal maths on every competitive bid. "
        "Re-check win/loss on overlapping segments and confirm your own "
        "price-to-value story still holds."
    ),
    ChangeCategory.FEATURES.value: (
        "A shipped capability narrows differentiation. Confirm whether this "
        "overlaps your roadmap and whether sales needs updated battlecards."
    ),
    ChangeCategory.PRODUCT.value: (
        "A product-level move signals where the competitor is investing. "
        "Assess whether it expands them into your core segment."
    ),
    ChangeCategory.HIRING.value: (
        "Hiring is a leading indicator: roles opened now become shipped "
        "capability in two to three quarters."
    ),
    ChangeCategory.INTEGRATIONS.value: (
        "Each integration deepens ecosystem lock-in and can block you from "
        "accounts already standardised on that vendor."
    ),
    ChangeCategory.MESSAGING.value: (
        "Positioning changes usually precede a segment or ICP shift. Watch "
        "whether follow-on pricing and packaging changes arrive next."
    ),
    ChangeCategory.OTHER.value: (
        "Low-signal change recorded for completeness; no immediate action "
        "indicated."
    ),
}

_ACTION_TEMPLATES: dict[str, str] = {
    ChangeCategory.PRICING.value: (
        "Review your equivalent tier and refresh competitive pricing collateral."
    ),
    ChangeCategory.FEATURES.value: "Compare against your roadmap and update sales battlecards.",
    ChangeCategory.PRODUCT.value: "Brief product leadership on the overlap with your roadmap.",
    ChangeCategory.HIRING.value: "Track this team's growth over the next two quarters.",
    ChangeCategory.INTEGRATIONS.value: (
        "Check whether the same integration is worth prioritising for you."
    ),
    ChangeCategory.MESSAGING.value: (
        "Re-read their positioning against your own homepage narrative."
    ),
    ChangeCategory.OTHER.value: "No action required.",
}


def _shorten(text: str, limit: int = 90) -> str:
    """Trim a snippet for use inside a one-line title."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _build_title(context: dict) -> str:
    """Compose a headline from the facts the classifier actually extracted."""
    competitor = context.get("competitor_name") or "Competitor"
    category = context.get("category", ChangeCategory.OTHER.value)
    signals: dict = context.get("signals") or {}
    before = context.get("before") or ""
    after = context.get("after") or ""

    if category == ChangeCategory.PRICING.value:
        direction = signals.get("price_direction")
        if direction == 1.0:
            return f"{competitor} increased pricing"
        if direction == -1.0:
            return f"{competitor} reduced pricing"
        if signals.get("free_tier_shift"):
            return f"{competitor} changed its free-tier positioning"
        return f"{competitor} updated pricing"

    if category == ChangeCategory.HIRING.value:
        ml_roles = int(signals.get("ml_role_count", 0))
        if ml_roles:
            plural = "s" if ml_roles != 1 else ""
            return f"{competitor} opened {ml_roles} AI/ML role{plural}"
        generic = int(signals.get("generic_role_count", 0))
        if generic:
            plural = "s" if generic != 1 else ""
            return f"{competitor} opened {generic} engineering role{plural}"
        return f"{competitor} updated its careers page"

    if category == ChangeCategory.FEATURES.value:
        if signals.get("plan_limit_changed"):
            return f"{competitor} changed plan entitlements"
        if signals.get("ai_mention"):
            return f"{competitor} added AI capability messaging"
        return f"{competitor} announced a feature change"

    if category == ChangeCategory.INTEGRATIONS.value:
        count = int(signals.get("new_partner_count", 0))
        if count:
            plural = "s" if count != 1 else ""
            return f"{competitor} added {count} new integration{plural}"
        return f"{competitor} updated its integrations"

    if category == ChangeCategory.PRODUCT.value:
        return f"{competitor} made a product-level change"

    if category == ChangeCategory.MESSAGING.value:
        return f"{competitor} rewrote key positioning copy"

    subject = _shorten(after or before, 60)
    return f"{competitor} page change: {subject}" if subject else f"{competitor} page change"


def _build_summary(context: dict) -> str:
    """Describe the change using only observed before/after content."""
    before = _shorten(context.get("before") or "", 160)
    after = _shorten(context.get("after") or "", 160)
    location = context.get("location", "body")
    evidence: list[str] = context.get("evidence") or []

    if before and after:
        body = f'On the {location} section, "{before}" became "{after}".'
    elif after:
        body = f'New content appeared in the {location} section: "{after}".'
    elif before:
        body = f'Content was removed from the {location} section: "{before}".'
    else:
        body = f"A change was detected in the {location} section."

    if evidence:
        body += " " + " ".join(dict.fromkeys(evidence[:3])) + "."
    return body


class HeuristicProvider(LLMProvider):
    """Template-driven analysis derived from deterministic signals only."""

    name = "deterministic"
    model = "rule-based-v1"

    def is_available(self) -> bool:
        """Always available: no network, no key, no rate limit."""
        return True

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 900,
        context: dict | None = None,
    ) -> LLMResponse:
        """Render a structured analysis from ``context``.

        The prompts are accepted for interface compatibility but not parsed —
        this provider works from the structured facts, not from prose.
        """
        del system, user, max_tokens
        context = context or {}

        if context.get("task") == "digest":
            payload = self._digest(context)
        else:
            payload = self._analysis(context)

        return LLMResponse(
            text=json.dumps(payload), provider=self.name, model=self.model, tokens_used=0
        )

    def _analysis(self, context: dict) -> dict:
        """Build a :class:`~app.schemas.llm.ChangeAnalysis`-shaped payload."""
        category = context.get("category", ChangeCategory.OTHER.value)
        return {
            "title": _build_title(context),
            "category": category,
            "summary": _build_summary(context),
            "before": context.get("before") or None,
            "after": context.get("after") or None,
            "business_impact": _IMPACT_TEMPLATES.get(
                category, _IMPACT_TEMPLATES[ChangeCategory.OTHER.value]
            ),
            "recommended_action": _ACTION_TEMPLATES.get(category),
            # Defer to the deterministic score; this provider adds no new signal.
            "relevance_score": context.get("deterministic_score", 50.0),
            "confidence": context.get("classifier_confidence", 0.5),
        }

    def _digest(self, context: dict) -> dict:
        """Build a :class:`~app.schemas.llm.DigestNarrative`-shaped payload."""
        items: list[dict] = context.get("items") or []
        stats: dict = context.get("stats") or {}

        highlights = [
            {
                "competitor": item.get("competitor", "Unknown"),
                "category": item.get("category", ChangeCategory.OTHER.value),
                "headline": item.get("title", ""),
                "detail": item.get("summary", ""),
                "impact": item.get("business_impact", ""),
            }
            for item in items[:10]
        ]

        count = len(items)
        if count:
            categories = sorted({item.get("category", "other") for item in items})
            headline = (
                f"{count} important competitive move{'s' if count != 1 else ''} "
                f"detected across {', '.join(categories)}."
            )
        else:
            headline = "No high-impact competitive moves detected this period."

        outlook = (
            f"RivalRadar processed {stats.get('raw_changes', 0)} raw page changes and "
            f"discarded {stats.get('noise_changes', 0)} as noise "
            f"({stats.get('noise_reduction', 0)}% noise reduction), leaving "
            f"{stats.get('meaningful_changes', 0)} meaningful changes of which "
            f"{stats.get('high_impact_changes', 0)} scored as high impact."
        )
        return {"headline": headline, "highlights": highlights, "outlook": outlook}
