"""Deterministic change classification.

The classifier runs *before* any LLM call.  It is cheap, explainable and
produces both a category and a confidence, plus a bag of numeric ``signals``
that the relevance scorer consumes.  Only changes that survive this stage are
worth spending tokens on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.diff.types import DetectedChange
from app.models.entities import ChangeCategory, ChangeType

# --- Currency / pricing -----------------------------------------------------

_CURRENCY_SYMBOLS = "$€£¥₹"
_CURRENCY_WORDS = r"usd|eur|gbp|inr|rs\.?|rupees?|dollars?|euros?|pounds?"
# Matches a symbol prefix ($9.99, ₹1,499), a word prefix (Rs 999, INR 1499)
# and a word suffix (999 USD, 1499 rupees).
_PRICE_RE = re.compile(
    rf"(?:[{_CURRENCY_SYMBOLS}]\s?(\d[\d,]*(?:\.\d{{1,2}})?)"
    rf"|\b(?:{_CURRENCY_WORDS})\s?(\d[\d,]*(?:\.\d{{1,2}})?)"
    rf"|\b(\d[\d,]*(?:\.\d{{1,2}})?)\s?(?:{_CURRENCY_WORDS})\b)",
    re.IGNORECASE,
)
_BILLING_PERIOD_RE = re.compile(
    r"\b(?:per\s+month|per\s+year|per\s+user|per\s+seat|/\s*mo(?:nth)?\b|/\s*yr\b|/\s*year\b|"
    r"monthly|annually|annual|billed\s+\w+)\b",
    re.IGNORECASE,
)
_PLAN_NAME_RE = re.compile(
    r"\b(?:free|starter|basic|standard|pro|professional|team|business|growth|scale|"
    r"premium|enterprise|plus|ultimate)\b(?:\s+(?:plan|tier))?",
    re.IGNORECASE,
)
_FREE_TO_PAID_RE = re.compile(r"\bfree\b", re.IGNORECASE)

# --- Features / launches ----------------------------------------------------

_FEATURE_RE = re.compile(
    r"\b(?:new feature|introducing|announcing|now supports?|now available|available now|"
    r"launch(?:ed|ing)?|we(?:'| a)?re launching|general availability|\bGA\b|beta|"
    r"early access|coming soon|redesigned|revamped|improved|faster|powered by ai|"
    r"ai-powered|ai powered|machine learning|automation|copilot|assistant)\b",
    re.IGNORECASE,
)
_FEATURE_LIST_RE = re.compile(
    r"\b(?:unlimited|includes?|up to \d+|\d+\s+(?:projects?|seats?|users?|workspaces?|"
    r"integrations?|credits?|requests?|gb\b|tb\b))\b",
    re.IGNORECASE,
)
# Quantified plan entitlements, captured so we can tell whether they moved.
_PLAN_LIMIT_RE = re.compile(
    r"\b(unlimited|\d[\d,]*)\s*(projects?|seats?|users?|members?|workspaces?|"
    r"integrations?|credits?|requests?|api calls?|environments?|repos?|repositories|"
    r"gb|tb|mb)\b",
    re.IGNORECASE,
)

# --- Hiring -----------------------------------------------------------------

_HIRING_CONTEXT_RE = re.compile(
    r"\b(?:career|careers|jobs?|hiring|open (?:role|position)s?|job opening|"
    r"we(?:'| a)?re hiring|apply now|join (?:our|the) team|vacanc(?:y|ies)|"
    r"full[- ]time|part[- ]time|remote)\b",
    re.IGNORECASE,
)
_ML_ROLE_RE = re.compile(
    r"\b(?:machine learning|ml)\s+(?:engineer|scientist|researcher)\b"
    r"|\bai\s+(?:engineer|scientist|researcher|architect)\b"
    r"|\bresearch scientist\b|\bdata scientist\b|\bmlops\b|\bapplied scientist\b"
    r"|\bdeep learning\b|\bnlp engineer\b|\bllm\b",
    re.IGNORECASE,
)
_GENERIC_ROLE_RE = re.compile(
    r"\b(?:software|backend|back-end|frontend|front-end|full[- ]stack|platform|"
    r"infrastructure|devops|security|mobile|ios|android|qa|sre)\s+engineer\b"
    r"|\b(?:product|engineering|sales|marketing)\s+manager\b"
    r"|\b(?:designer|recruiter|analyst|account executive)\b",
    re.IGNORECASE,
)

# --- Product / integrations -------------------------------------------------

_PRODUCT_RE = re.compile(
    r"\b(?:new product|product launch|platform|suite|our (?:new )?product|"
    r"dashboard|workspace|studio|console|editor|app\b)\b",
    re.IGNORECASE,
)
_INTEGRATION_RE = re.compile(
    r"\b(?:integrat(?:e|es|ion|ions)|connector|connects? (?:to|with)|works with|"
    r"webhook|api\b|sdk\b|marketplace|plugin|extension|partnership|partner with|"
    r"native support for)\b",
    re.IGNORECASE,
)
_INTEGRATION_PARTNER_RE = re.compile(
    r"\b(?:slack|salesforce|hubspot|zapier|snowflake|databricks|stripe|shopify|"
    r"github|gitlab|jira|notion|figma|aws|azure|gcp|google cloud|kubernetes|segment|"
    r"okta|tableau|power bi|zendesk|intercom)\b",
    re.IGNORECASE,
)

# --- Messaging / positioning ------------------------------------------------

_POSITIONING_RE = re.compile(
    r"\b(?:the (?:leading|best|#1|number one)|built for|designed for|trusted by|"
    r"for (?:enterprise|teams|developers|startups)|platform for|all-in-one|"
    r"end-to-end|mission|vision)\b",
    re.IGNORECASE,
)

_HEADING_TAGS = frozenset({"h1", "h2", "h3"})


@dataclass(slots=True)
class Classification:
    """Result of deterministic classification."""

    category: str
    change_type: str
    confidence: float
    signals: dict[str, float]
    evidence: list[str]


def _parse_prices(text: str) -> list[float]:
    """Extract numeric price values from a string."""
    values: list[float] = []
    for match in _PRICE_RE.finditer(text or ""):
        # Exactly one of the three alternation groups captures the amount.
        raw = next((group for group in match.groups() if group), "")
        try:
            values.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return values


def _count(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text or ""))


def _price_signals(change: DetectedChange) -> tuple[float, list[str], dict[str, float]]:
    """Score how strongly this looks like a pricing change."""
    before, after = change.before or "", change.after or ""
    blob = f"{before} {after}"
    evidence: list[str] = []
    signals: dict[str, float] = {}
    score = 0.0

    before_prices = _parse_prices(before)
    after_prices = _parse_prices(after)

    if before_prices or after_prices:
        score += 0.35
        signals["has_price_token"] = 1.0

    if before_prices and after_prices:
        old, new = before_prices[0], after_prices[0]
        if abs(old - new) > 1e-9:
            score += 0.45
            delta_ratio = abs(new - old) / max(old, 1e-9)
            signals["price_delta_ratio"] = round(min(delta_ratio, 5.0), 4)
            signals["price_direction"] = 1.0 if new > old else -1.0
            direction = "increased" if new > old else "decreased"
            evidence.append(f"Price {direction} from {old:g} to {new:g}")
    elif before_prices and not after_prices:
        score += 0.2
        evidence.append("Price removed from page")
    elif after_prices and not before_prices:
        score += 0.25
        evidence.append("Price added to page")

    if _BILLING_PERIOD_RE.search(blob):
        score += 0.12
        signals["has_billing_period"] = 1.0
    if _PLAN_NAME_RE.search(blob):
        score += 0.1
        signals["has_plan_name"] = 1.0
        plan = _PLAN_NAME_RE.search(blob)
        if plan:
            evidence.append(f"Plan mentioned: {plan.group(0).strip()}")

    # free -> paid (or the reverse) is a major pricing-model move.
    free_before = bool(_FREE_TO_PAID_RE.search(before))
    free_after = bool(_FREE_TO_PAID_RE.search(after))
    if free_before != free_after and (before_prices or after_prices):
        score += 0.3
        signals["free_tier_shift"] = 1.0
        evidence.append("Free-tier positioning changed")

    if change.location == "pricing":
        score += 0.15
        signals["on_pricing_page"] = 1.0

    return min(score, 1.0), evidence, signals


def _hiring_signals(change: DetectedChange) -> tuple[float, list[str], dict[str, float]]:
    """Score how strongly this looks like a hiring signal."""
    blob = f"{change.before} {change.after}"
    evidence: list[str] = []
    signals: dict[str, float] = {}
    score = 0.0

    in_careers = change.location == "careers"
    if in_careers:
        score += 0.3
        signals["on_careers_page"] = 1.0
    if _HIRING_CONTEXT_RE.search(blob):
        score += 0.25
        signals["hiring_context"] = 1.0

    ml_roles = _count(_ML_ROLE_RE, change.after)
    if ml_roles:
        score += 0.4
        signals["ml_role_count"] = float(ml_roles)
        evidence.append(f"{ml_roles} AI/ML role mention(s) detected")
    generic_roles = _count(_GENERIC_ROLE_RE, change.after)
    if generic_roles:
        score += 0.2
        signals["generic_role_count"] = float(generic_roles)
        evidence.append(f"{generic_roles} engineering role mention(s) detected")

    # A role list only counts as hiring when there is hiring context somewhere.
    if (ml_roles or generic_roles) and not (in_careers or _HIRING_CONTEXT_RE.search(blob)):
        score -= 0.2

    return max(0.0, min(score, 1.0)), evidence, signals


def _feature_signals(change: DetectedChange) -> tuple[float, list[str], dict[str, float]]:
    """Score how strongly this looks like a feature launch."""
    blob = f"{change.before} {change.after}"
    evidence: list[str] = []
    signals: dict[str, float] = {}
    score = 0.0

    launches = _count(_FEATURE_RE, change.after)
    if launches:
        # One unambiguous launch phrase ("now available", "introducing") is
        # already enough to call this a feature change; extra phrases add less.
        score += min(0.38 + 0.10 * (launches - 1), 0.60)
        signals["launch_phrase_count"] = float(launches)
        match = _FEATURE_RE.search(change.after)
        if match:
            evidence.append(f"Launch language: '{match.group(0)}'")
    if _FEATURE_LIST_RE.search(blob):
        score += 0.15
        signals["feature_quantities"] = 1.0

    # A quantified entitlement that actually moved ("5 projects" -> "10 projects")
    # is a concrete packaging change, not marketing copy.
    limits_before = {
        (unit.lower(), value.lower())
        for value, unit in _PLAN_LIMIT_RE.findall(change.before or "")
    }
    limits_after = {
        (unit.lower(), value.lower())
        for value, unit in _PLAN_LIMIT_RE.findall(change.after or "")
    }
    moved = {unit for unit, _ in limits_after} & {unit for unit, _ in limits_before}
    if moved and limits_before != limits_after:
        score += 0.40
        signals["plan_limit_changed"] = 1.0
        for unit in sorted(moved):
            old = next((v for u, v in limits_before if u == unit), "?")
            new = next((v for u, v in limits_after if u == unit), "?")
            if old != new:
                evidence.append(f"Plan limit changed: {old} -> {new} {unit}")

    if change.change_type == ChangeType.ADDED.value and launches:
        score += 0.12
    if re.search(r"\bai\b|artificial intelligence|machine learning", blob, re.IGNORECASE):
        score += 0.15
        signals["ai_mention"] = 1.0
        evidence.append("AI/ML capability mentioned")

    return min(score, 1.0), evidence, signals


def _product_signals(change: DetectedChange) -> tuple[float, list[str], dict[str, float]]:
    """Score how strongly this looks like a product-level change."""
    blob = f"{change.before} {change.after}"
    signals: dict[str, float] = {}
    evidence: list[str] = []
    score = 0.0

    if _PRODUCT_RE.search(blob):
        score += 0.3
        signals["product_language"] = 1.0
    if change.location in {"product", "main", "header"}:
        score += 0.15
    if change.change_type in {ChangeType.ADDED.value, ChangeType.HEADLINE_CHANGE.value}:
        score += 0.1
    if re.search(r"\bnew product|product launch\b", blob, re.IGNORECASE):
        score += 0.25
        evidence.append("Explicit product-launch language")
    return min(score, 1.0), evidence, signals


def _integration_signals(change: DetectedChange) -> tuple[float, list[str], dict[str, float]]:
    """Score how strongly this looks like an integration/partnership change."""
    blob = f"{change.before} {change.after}"
    signals: dict[str, float] = {}
    evidence: list[str] = []
    score = 0.0

    if _INTEGRATION_RE.search(blob):
        score += 0.35
        signals["integration_language"] = 1.0
    partners = {m.group(0).lower() for m in _INTEGRATION_PARTNER_RE.finditer(change.after or "")}
    old_partners = {
        m.group(0).lower() for m in _INTEGRATION_PARTNER_RE.finditer(change.before or "")
    }
    new_partners = partners - old_partners
    if new_partners:
        score += 0.35
        signals["new_partner_count"] = float(len(new_partners))
        evidence.append("New integration partner(s): " + ", ".join(sorted(new_partners)))
    if change.location == "integrations":
        score += 0.2
        signals["on_integrations_page"] = 1.0
    return min(score, 1.0), evidence, signals


def _messaging_signals(change: DetectedChange) -> tuple[float, list[str], dict[str, float]]:
    """Score how strongly this looks like repositioning/messaging."""
    blob = f"{change.before} {change.after}"
    signals: dict[str, float] = {}
    evidence: list[str] = []
    score = 0.0

    if _POSITIONING_RE.search(blob):
        score += 0.35
        signals["positioning_language"] = 1.0
        evidence.append("Positioning language changed")
    if change.change_type == ChangeType.HEADLINE_CHANGE.value:
        score += 0.3
        signals["headline_change"] = 1.0
        evidence.append("Headline copy rewritten")
    if change.location in {"header", "main"} and change.magnitude > 0.5:
        score += 0.2
    return min(score, 1.0), evidence, signals


_CATEGORY_TO_TYPE: dict[str, str] = {
    ChangeCategory.PRICING.value: ChangeType.PRICE_CHANGE.value,
    ChangeCategory.FEATURES.value: ChangeType.FEATURE_CHANGE.value,
    ChangeCategory.PRODUCT.value: ChangeType.PRODUCT_CHANGE.value,
    ChangeCategory.HIRING.value: ChangeType.HIRING_SIGNAL.value,
    ChangeCategory.INTEGRATIONS.value: ChangeType.INTEGRATION_CHANGE.value,
    ChangeCategory.MESSAGING.value: ChangeType.HEADLINE_CHANGE.value,
}

# Minimum detector score before we assign a specific category.
_CATEGORY_THRESHOLD = 0.35


def classify(change: DetectedChange) -> Classification:
    """Classify a change deterministically.

    Runs every detector, takes the strongest, and falls back to ``other`` when
    nothing is confident enough.  Confidence is the winning score, tempered by
    how far ahead of the runner-up it was.
    """
    detectors: list[tuple[str, float, list[str], dict[str, float]]] = []
    for category, detector in (
        (ChangeCategory.PRICING.value, _price_signals),
        (ChangeCategory.HIRING.value, _hiring_signals),
        (ChangeCategory.FEATURES.value, _feature_signals),
        (ChangeCategory.INTEGRATIONS.value, _integration_signals),
        (ChangeCategory.PRODUCT.value, _product_signals),
        (ChangeCategory.MESSAGING.value, _messaging_signals),
    ):
        score, evidence, signals = detector(change)
        detectors.append((category, score, evidence, signals))

    detectors.sort(key=lambda item: item[1], reverse=True)
    best_category, best_score, evidence, signals = detectors[0]
    runner_up = detectors[1][1] if len(detectors) > 1 else 0.0

    merged_signals = dict(signals)
    merged_signals["detector_score"] = round(best_score, 4)
    merged_signals["detector_margin"] = round(best_score - runner_up, 4)

    if best_score < _CATEGORY_THRESHOLD:
        return Classification(
            category=ChangeCategory.OTHER.value,
            change_type=change.change_type,
            # Low but non-zero: we are confident it is *not* a known category.
            confidence=round(0.3 + best_score * 0.4, 3),
            signals=merged_signals,
            evidence=evidence,
        )

    # A clear winner is more trustworthy than a near-tie.
    margin_bonus = min(0.15, (best_score - runner_up) * 0.3)
    confidence = round(min(0.97, 0.45 + best_score * 0.45 + margin_bonus), 3)

    return Classification(
        category=best_category,
        change_type=_CATEGORY_TO_TYPE.get(best_category, change.change_type),
        confidence=confidence,
        signals=merged_signals,
        evidence=evidence,
    )


def classify_changes(changes: list[DetectedChange]) -> list[DetectedChange]:
    """Classify a list of changes in place and return it."""
    for change in changes:
        result = classify(change)
        change.category = result.category
        change.change_type = result.change_type
        change.classifier_confidence = result.confidence
        change.signals.update(result.signals)
        change.evidence.extend(result.evidence)
    return changes
