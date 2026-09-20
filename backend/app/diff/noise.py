"""Noise filtering.

This is the component that turns "147 HTML changes detected" into a handful of
changes a founder should actually read.  Every rule is deterministic, ordered
and explains itself via ``noise_reason`` so the funnel is auditable rather than
a black box.

Rules are evaluated cheapest-first and short-circuit on the first match.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from app.config.logging import get_logger
from app.diff.types import DetectedChange
from app.scrapers.normalizer import canonicalise, collapse_whitespace

logger = get_logger(__name__)

# A change smaller than this is cosmetic unless it carries a strong signal.
MIN_MAGNITUDE = 0.12
# Blocks shorter than this rarely carry standalone meaning.
MIN_MEANINGFUL_CHARS = 12

_BOILERPLATE_LOCATIONS = frozenset(
    {"navigation", "footer", "cookie_banner", "advertisement", "sidebar"}
)

# Copy that appears on every site and never signals strategy.
_CHROME_PHRASES = (
    "cookie", "consent", "privacy policy", "terms of service", "terms and conditions",
    "all rights reserved", "sign in", "log in", "sign up", "subscribe to our newsletter",
    "follow us", "back to top", "skip to content", "accept all", "manage preferences",
    "we use cookies", "gdpr", "©", "copyright",
)

# Platform names alone are NOT noise — "integrates with GitHub" is a real
# signal.  Only an explicit sharing/follow verb next to one makes it a widget.
_SOCIAL_PLATFORMS = ("twitter", "facebook", "linkedin", "instagram", "youtube", "tiktok", "x.com")
_SOCIAL_VERBS = ("share this", "share on", "follow us", "connect with us", "find us on", "tweet")

# Strong signals that override several noise rules (see _has_strong_signal).
_CURRENCY_WORDS = r"usd|eur|gbp|inr|rs\.?|rupees?|dollars?|euros?|pounds?"
_PRICE_TOKEN_RE = re.compile(
    rf"(?:[$€£¥₹]\s?\d[\d,.]*"
    rf"|\b(?:{_CURRENCY_WORDS})\s?\d[\d,.]*"
    rf"|\b\d[\d,.]*\s?(?:{_CURRENCY_WORDS})\b)",
    re.IGNORECASE,
)
# Plan limits ("5 projects" -> "10 projects") are short but commercially real.
_PLAN_LIMIT_RE = re.compile(
    r"\b(?:unlimited|\d[\d,]*)\s*(?:projects?|seats?|users?|members?|workspaces?|"
    r"integrations?|credits?|requests?|api calls?|environments?|repos?|repositories|"
    r"gb\b|tb\b|mb\b)",
    re.IGNORECASE,
)
_PRICING_WORDS_RE = re.compile(
    r"\b(?:free|freemium|per month|per year|/mo\b|/yr\b|monthly|annually|annual|billed|"
    r"pricing|price|plan|tier|seat|per user|trial|enterprise|starter|pro\b|premium)\b",
    re.IGNORECASE,
)
_LAUNCH_WORDS_RE = re.compile(
    r"\b(?:introducing|announcing|now available|new feature|launch(?:ed|ing)?|"
    r"now supports|general availability|beta|early access|we are excited to)\b",
    re.IGNORECASE,
)
_HIRING_WORDS_RE = re.compile(
    r"\b(?:we are hiring|now hiring|open roles?|job opening|apply now|"
    r"machine learning engineer|ml engineer|ai engineer|research scientist|"
    r"software engineer|data scientist|full[- ]stack|backend engineer|frontend engineer)\b",
    re.IGNORECASE,
)
_INTEGRATION_WORDS_RE = re.compile(
    r"\b(?:integration|integrates? with|connector|api\b|sdk\b|webhook|marketplace|"
    r"partnership|now works with)\b",
    re.IGNORECASE,
)

# Purely numeric churn: counters, review totals, stock levels.
_NUMBER_ONLY_RE = re.compile(r"^[\s\d,.%+\-–—:/()]*$")
_COUNTER_PHRASE_RE = re.compile(
    r"\b\d[\d,.]*\+?\s*(?:customers?|users?|companies|teams?|downloads?|stars?|reviews?|"
    r"visitors?|members?|developers?|businesses)\b",
    re.IGNORECASE,
)


def _has_strong_signal(change: DetectedChange) -> bool:
    """True when the change contains business-relevant vocabulary.

    Used to rescue changes that would otherwise be dropped by a generic rule —
    a price inside a footer is still a price.
    """
    blob = f"{change.before} {change.after}"
    if (
        _PRICE_TOKEN_RE.search(blob)
        or _LAUNCH_WORDS_RE.search(blob)
        or _HIRING_WORDS_RE.search(blob)
        or (_PRICING_WORDS_RE.search(blob) and _PRICE_TOKEN_RE.search(blob))
    ):
        return True
    # A new integration partner is a real competitive signal.
    if _INTEGRATION_WORDS_RE.search(blob) and canonicalise(change.before) != canonicalise(
        change.after
    ):
        return True
    # A plan limit that actually moved ("5 projects" -> "10 projects").
    return bool(
        _PLAN_LIMIT_RE.search(change.before or "")
        and _PLAN_LIMIT_RE.search(change.after or "")
        and canonicalise(change.before) != canonicalise(change.after)
    )


def _prices_differ(change: DetectedChange) -> bool:
    """True when the monetary amounts genuinely changed."""
    before_prices = _PRICE_TOKEN_RE.findall(change.before or "")
    after_prices = _PRICE_TOKEN_RE.findall(change.after or "")
    norm = lambda values: {re.sub(r"[\s,]", "", v).casefold() for v in values}  # noqa: E731
    return norm(before_prices) != norm(after_prices)


# --- Individual rules -------------------------------------------------------
# Each returns a reason string when the change is noise, otherwise None.

def _rule_identical(change: DetectedChange) -> str | None:
    """Canonically identical content: whitespace, casing or dynamic tokens only."""
    if canonicalise(change.before) == canonicalise(change.after):
        return "canonically identical (whitespace/dynamic tokens only)"
    return None


def _rule_empty(change: DetectedChange) -> str | None:
    """Nothing of substance on either side."""
    before = collapse_whitespace(change.before)
    after = collapse_whitespace(change.after)
    if not before and not after:
        return "empty change"
    longest = max(len(before), len(after))
    if longest < MIN_MEANINGFUL_CHARS and not _has_strong_signal(change):
        return f"content too short to be meaningful (<{MIN_MEANINGFUL_CHARS} chars)"
    return None


def _rule_boilerplate_location(change: DetectedChange) -> str | None:
    """Navigation, footer, cookie banner and ad slots."""
    if change.location in _BOILERPLATE_LOCATIONS and not _has_strong_signal(change):
        return f"boilerplate page region ({change.location})"
    return None


def _rule_chrome_copy(change: DetectedChange) -> str | None:
    """Universal site furniture (consent text, legal links, social buttons)."""
    blob = f"{change.before} {change.after}".casefold()
    if _has_strong_signal(change):
        return None
    if any(phrase in blob for phrase in _CHROME_PHRASES):
        return "generic site chrome / legal copy"
    if any(verb in blob for verb in _SOCIAL_VERBS) or (
        any(platform in blob for platform in _SOCIAL_PLATFORMS) and len(blob) < 60
    ):
        return "social/sharing widget"
    return None


def _rule_counter_churn(change: DetectedChange) -> str | None:
    """Live counters and review totals that tick on their own."""
    if _COUNTER_PHRASE_RE.search(change.before or "") and _COUNTER_PHRASE_RE.search(
        change.after or ""
    ):
        stripped_before = _COUNTER_PHRASE_RE.sub("<COUNT>", change.before or "")
        stripped_after = _COUNTER_PHRASE_RE.sub("<COUNT>", change.after or "")
        if canonicalise(stripped_before) == canonicalise(stripped_after):
            return "live counter / social-proof number churn"
    return None


def _rule_numeric_only(change: DetectedChange) -> str | None:
    """Both sides are bare numbers with no surrounding meaning."""
    before = collapse_whitespace(change.before)
    after = collapse_whitespace(change.after)
    if not before or not after:
        return None
    if (
        _NUMBER_ONLY_RE.match(before)
        and _NUMBER_ONLY_RE.match(after)
        and not _PRICE_TOKEN_RE.search(f"{before} {after}")
    ):
        return "numeric-only churn with no surrounding context"
    return None


def _rule_low_magnitude(change: DetectedChange) -> str | None:
    """Tiny edits: punctuation, a swapped adjective, a reordered clause."""
    if change.magnitude < MIN_MAGNITUDE and not _has_strong_signal(change):
        return f"magnitude below threshold ({change.magnitude:.2f} < {MIN_MAGNITUDE})"
    return None


def _rule_price_unchanged(change: DetectedChange) -> str | None:
    """A pricing block that got re-worded without the amounts moving."""
    blob = f"{change.before} {change.after}"
    if not _PRICE_TOKEN_RE.search(blob):
        return None
    if not _prices_differ(change) and change.magnitude < 0.45:
        return "pricing block reworded but amounts unchanged"
    return None


def _rule_url_only(change: DetectedChange) -> str | None:
    """Only a link target moved (tracking parameters, locale prefixes)."""
    before = canonicalise(change.before)
    after = canonicalise(change.after)
    if before and after and before == after:
        return "link target changed without visible copy change"
    return None


_RULES: tuple[tuple[str, Callable[[DetectedChange], str | None]], ...] = (
    ("identical", _rule_identical),
    ("empty", _rule_empty),
    ("url_only", _rule_url_only),
    ("counter_churn", _rule_counter_churn),
    ("numeric_only", _rule_numeric_only),
    ("boilerplate_location", _rule_boilerplate_location),
    ("chrome_copy", _rule_chrome_copy),
    ("price_unchanged", _rule_price_unchanged),
    ("low_magnitude", _rule_low_magnitude),
)


def evaluate_noise(change: DetectedChange) -> str | None:
    """Return a noise reason for a change, or ``None`` if it looks meaningful."""
    for name, rule in _RULES:
        try:
            reason = rule(change)
        except Exception:  # pragma: no cover - a rule must never break a scan
            logger.warning("Noise rule %s raised; treating as non-noise", name, exc_info=True)
            continue
        if reason:
            return reason
    return None


def filter_noise(changes: Iterable[DetectedChange]) -> list[DetectedChange]:
    """Annotate every change in place with ``is_noise``/``noise_reason``.

    Returns the same list (annotated), *not* only the survivors — the discarded
    ones are what make the noise-reduction metric computable and auditable.
    """
    annotated: list[DetectedChange] = []
    for change in changes:
        reason = evaluate_noise(change)
        change.is_noise = reason is not None
        change.noise_reason = reason
        annotated.append(change)

    dropped = sum(1 for c in annotated if c.is_noise)
    if annotated:
        logger.debug(
            "Noise filter: %d/%d discarded (%.1f%%)",
            dropped,
            len(annotated),
            dropped / len(annotated) * 100,
        )
    return annotated


def meaningful_only(changes: Iterable[DetectedChange]) -> list[DetectedChange]:
    """Return only the changes that survived noise filtering."""
    return [change for change in changes if not change.is_noise]


def noise_breakdown(changes: Iterable[DetectedChange]) -> dict[str, int]:
    """Count how many changes each noise reason accounted for."""
    breakdown: dict[str, int] = {}
    for change in changes:
        if change.is_noise and change.noise_reason:
            breakdown[change.noise_reason] = breakdown.get(change.noise_reason, 0) + 1
    return dict(sorted(breakdown.items(), key=lambda item: item[1], reverse=True))
