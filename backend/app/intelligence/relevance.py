"""Transparent relevance scoring.

The score is a weighted sum of five explainable components rather than a number
an LLM invented::

    relevance = 0.30 * business_impact
              + 0.20 * customer_impact
              + 0.20 * strategic_significance
              + 0.15 * change_magnitude
              + 0.15 * confidence

Each component is in [0, 1]; the result is scaled to 0-100.  An LLM may later
nudge the score, but only within a bounded band (see
:func:`blend_with_llm_score`) so the deterministic signal always dominates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.diff.types import DetectedChange
from app.models.entities import ChangeCategory, Severity

# Component weights.  Kept as a module constant so the README and the API can
# quote the exact formula the code uses.
WEIGHTS: dict[str, float] = {
    "business_impact": 0.30,
    "customer_impact": 0.20,
    "strategic_significance": 0.20,
    "change_magnitude": 0.15,
    "confidence": 0.15,
}

# How much each category inherently matters to a founder watching rivals.
_CATEGORY_BUSINESS_WEIGHT: dict[str, float] = {
    ChangeCategory.PRICING.value: 0.95,
    ChangeCategory.PRODUCT.value: 0.80,
    ChangeCategory.FEATURES.value: 0.75,
    ChangeCategory.INTEGRATIONS.value: 0.65,
    ChangeCategory.HIRING.value: 0.55,
    ChangeCategory.MESSAGING.value: 0.50,
    ChangeCategory.OTHER.value: 0.20,
}

_CATEGORY_CUSTOMER_WEIGHT: dict[str, float] = {
    ChangeCategory.PRICING.value: 1.00,
    ChangeCategory.FEATURES.value: 0.80,
    ChangeCategory.PRODUCT.value: 0.70,
    ChangeCategory.INTEGRATIONS.value: 0.60,
    ChangeCategory.MESSAGING.value: 0.45,
    ChangeCategory.HIRING.value: 0.15,
    ChangeCategory.OTHER.value: 0.15,
}

_CATEGORY_STRATEGIC_WEIGHT: dict[str, float] = {
    ChangeCategory.PRICING.value: 0.85,
    ChangeCategory.PRODUCT.value: 0.85,
    ChangeCategory.HIRING.value: 0.75,
    ChangeCategory.FEATURES.value: 0.65,
    ChangeCategory.INTEGRATIONS.value: 0.60,
    ChangeCategory.MESSAGING.value: 0.55,
    ChangeCategory.OTHER.value: 0.20,
}

# Page regions that amplify a change's importance.
_LOCATION_MULTIPLIER: dict[str, float] = {
    "pricing": 1.15,
    "careers": 1.05,
    "product": 1.08,
    "integrations": 1.05,
    "header": 1.05,
    "main": 1.02,
    "blog": 1.0,
    "body": 0.95,
    "navigation": 0.7,
    "footer": 0.6,
    "sidebar": 0.7,
    "cookie_banner": 0.4,
    "advertisement": 0.4,
}


@dataclass(slots=True)
class RelevanceBreakdown:
    """Per-component explanation of a relevance score."""

    business_impact: float = 0.0
    customer_impact: float = 0.0
    strategic_significance: float = 0.0
    change_magnitude: float = 0.0
    confidence: float = 0.0
    location_multiplier: float = 1.0
    score: float = 0.0
    severity: str = Severity.NOISE.value
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "business_impact": round(self.business_impact, 3),
            "customer_impact": round(self.customer_impact, 3),
            "strategic_significance": round(self.strategic_significance, 3),
            "change_magnitude": round(self.change_magnitude, 3),
            "confidence": round(self.confidence, 3),
            "location_multiplier": round(self.location_multiplier, 3),
            "weights": WEIGHTS,
            "score": round(self.score, 2),
            "severity": self.severity,
            "notes": list(self.notes),
        }


def _business_impact(change: DetectedChange) -> tuple[float, list[str]]:
    """How much this affects the competitor's commercial position."""
    notes: list[str] = []
    base = _CATEGORY_BUSINESS_WEIGHT.get(change.category, 0.2)

    # A large price move is the single strongest business signal available.
    delta = change.signals.get("price_delta_ratio", 0.0)
    if delta > 0:
        bump = min(0.35, delta * 0.7)
        base = min(1.0, base + bump)
        notes.append(f"Price moved by {delta * 100:.0f}% of the original value")
    if change.signals.get("free_tier_shift"):
        base = min(1.0, base + 0.15)
        notes.append("Free-tier availability changed")
    if change.signals.get("ml_role_count", 0) >= 2:
        base = min(1.0, base + 0.15)
        notes.append("Multiple AI/ML roles opened simultaneously")
    if change.signals.get("new_partner_count", 0) >= 1:
        base = min(1.0, base + 0.1)
    return base, notes


def _customer_impact(change: DetectedChange) -> tuple[float, list[str]]:
    """How directly a customer would notice this."""
    notes: list[str] = []
    base = _CATEGORY_CUSTOMER_WEIGHT.get(change.category, 0.15)
    if change.signals.get("has_price_token") and change.signals.get("price_direction"):
        direction = change.signals["price_direction"]
        notes.append(
            "Customers face a higher price"
            if direction > 0
            else "Customers gain a lower price"
        )
        base = min(1.0, base + 0.1)
    if change.signals.get("feature_quantities"):
        base = min(1.0, base + 0.1)
        notes.append("Plan limits or quantities changed")
    if change.location in {"navigation", "footer", "cookie_banner"}:
        base *= 0.5
    return base, notes


def _strategic_significance(change: DetectedChange) -> tuple[float, list[str]]:
    """How much this reveals about where the competitor is heading."""
    notes: list[str] = []
    base = _CATEGORY_STRATEGIC_WEIGHT.get(change.category, 0.2)
    if change.signals.get("ai_mention"):
        base = min(1.0, base + 0.15)
        notes.append("Signals investment in AI/ML capability")
    if change.signals.get("ml_role_count", 0) > 0:
        base = min(1.0, base + 0.12)
    if change.signals.get("positioning_language") or change.signals.get("headline_change"):
        base = min(1.0, base + 0.08)
        notes.append("Market positioning language shifted")
    if change.signals.get("launch_phrase_count", 0) >= 2:
        base = min(1.0, base + 0.08)
    return base, notes


def score_change(change: DetectedChange) -> RelevanceBreakdown:
    """Compute a 0-100 relevance score with a full component breakdown."""
    business, business_notes = _business_impact(change)
    customer, customer_notes = _customer_impact(change)
    strategic, strategic_notes = _strategic_significance(change)

    magnitude = max(0.0, min(1.0, change.magnitude))
    confidence = max(0.0, min(1.0, change.classifier_confidence))

    weighted = (
        WEIGHTS["business_impact"] * business
        + WEIGHTS["customer_impact"] * customer
        + WEIGHTS["strategic_significance"] * strategic
        + WEIGHTS["change_magnitude"] * magnitude
        + WEIGHTS["confidence"] * confidence
    )

    multiplier = _LOCATION_MULTIPLIER.get(change.location, 1.0)
    # A location boost lifts the score through a fraction of its remaining
    # headroom rather than multiplying it.  Plain multiplication drove every
    # pricing change into the 100 ceiling, which erased the ranking between a
    # 5% price nudge and a tripling.  This keeps boosts strictly monotonic.
    base = max(0.0, min(1.0, weighted)) * 100.0
    if multiplier > 1.0:
        score = base + (100.0 - base) * min(multiplier - 1.0, 1.0)
    else:
        score = base * multiplier
    score = max(0.0, min(100.0, score))

    # Changes the noise filter already rejected can never outrank real ones.
    if change.is_noise:
        score = min(score, 29.0)

    breakdown = RelevanceBreakdown(
        business_impact=business,
        customer_impact=customer,
        strategic_significance=strategic,
        change_magnitude=magnitude,
        confidence=confidence,
        location_multiplier=multiplier,
        score=round(score, 2),
        severity=Severity.from_score(score).value,
        notes=[*business_notes, *customer_notes, *strategic_notes],
    )
    return breakdown


def score_changes(changes: list[DetectedChange]) -> list[DetectedChange]:
    """Score a list of changes in place and return it."""
    for change in changes:
        breakdown = score_change(change)
        change.relevance_score = breakdown.score
        change.severity = breakdown.severity
        change.signals["relevance_business_impact"] = breakdown.business_impact
        change.signals["relevance_customer_impact"] = breakdown.customer_impact
        change.signals["relevance_strategic"] = breakdown.strategic_significance
        change.evidence.extend(breakdown.notes)
    return changes


def blend_with_llm_score(
    deterministic: float, llm_score: float | None, *, max_shift: float = 12.0
) -> float:
    """Let the LLM adjust the deterministic score, but only within a band.

    The LLM sees language the rules cannot ("we are sunsetting this product"),
    so its opinion is worth something — but it never gets to move a score by
    more than ``max_shift`` points in either direction.
    """
    if llm_score is None:
        return round(deterministic, 2)
    llm_score = max(0.0, min(100.0, float(llm_score)))
    delta = max(-max_shift, min(max_shift, llm_score - deterministic))
    return round(max(0.0, min(100.0, deterministic + delta)), 2)


def is_high_impact(score: float) -> bool:
    """High impact is the HIGH (70-84) and CRITICAL (85-100) bands."""
    return score >= 70.0
