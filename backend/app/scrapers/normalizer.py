"""HTML normalisation and content-block extraction.

This module converts messy real-world HTML into a stable list of
:class:`ContentBlock` objects that the diff engine can compare.  Two levels of
normalisation are used deliberately:

``extract_blocks``
    Light normalisation.  Scripts/styles are dropped but navigation, footers,
    cookie banners and timestamps are *kept*.  This is what the raw diff runs
    against, so the noise-reduction metric reflects the noise a naive differ
    would really have to cope with.

``canonicalise``
    Aggressive normalisation.  Dynamic tokens (UUIDs, timestamps, nonces,
    tracking parameters, cache-busting hashes) are replaced with placeholders.
    Two strings that differ only in such tokens canonicalise identically, which
    is how the noise filter proves a change is not meaningful.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, Tag

from app.config.logging import get_logger

logger = get_logger(__name__)

# Tags that never carry competitor-visible copy.
_INVISIBLE_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "path",
        "canvas",
        "iframe",
        "link",
        "meta",
        "head",
        "object",
        "embed",
    }
)

# Block-level tags whose text forms one comparable unit.
_BLOCK_TAGS = frozenset(
    {
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "li", "td", "th", "dt", "dd",
        "blockquote", "figcaption", "caption",
        "button", "a", "label", "legend", "summary",
        "span", "div", "strong", "em", "code", "pre",
    }
)

# Landmarks that tell us *where* on the page a block lives.
_LOCATION_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pricing", ("pricing", "price", "plans", "plan-", "tier", "billing", "subscribe")),
    ("careers", ("career", "jobs", "job-", "hiring", "openings", "vacanc", "greenhouse", "lever")),
    ("navigation", ("nav", "menu", "navbar", "topbar", "breadcrumb")),
    ("footer", ("footer", "colophon", "site-info", "legal", "copyright")),
    ("cookie_banner", ("cookie", "consent", "gdpr", "privacy-banner", "onetrust")),
    ("advertisement", ("ad-", "-ad", "ads", "advert", "sponsor", "promo-banner")),
    ("blog", ("blog", "news", "press", "article", "changelog", "release-notes", "announcement")),
    ("integrations", ("integration", "partners", "marketplace", "connectors", "apps")),
    ("product", ("product", "feature", "platform", "solutions", "capabilit")),
    ("header", ("header", "masthead", "hero", "banner")),
)

# Elements that are structurally chrome regardless of their class names.
_TAG_LOCATIONS: dict[str, str] = {
    "nav": "navigation",
    "footer": "footer",
    "header": "header",
    "aside": "sidebar",
    "form": "form",
}

_WHITESPACE_RE = re.compile(r"\s+")
_ZERO_WIDTH_RE = re.compile(r"[​-‏‪-‮﻿]")

# --- Dynamic-token patterns (order matters: most specific first) ------------
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
_LONG_HEX_RE = re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE)
_ISO_DATETIME_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
)
_CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b", re.IGNORECASE)
_LONG_DATE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)
_RELATIVE_TIME_RE = re.compile(
    r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b", re.IGNORECASE
)
_EPOCH_RE = re.compile(r"\b1[6-9]\d{8}(?:\d{3})?\b")
_TRACKING_PARAM_RE = re.compile(
    r"[?&](?:utm_[a-z]+|gclid|fbclid|msclkid|mc_cid|mc_eid|ref|referrer|_ga|sessionid|"
    r"session_id|csrf|csrf_token|nonce|cache|cb|v|ver|version|t|ts|hash)=[^\s&\"'<>]*",
    re.IGNORECASE,
)
_CACHE_BUST_RE = re.compile(
    r"\.[0-9a-f]{6,12}\.(?:js|css|png|jpg|jpeg|svg|webp|woff2?)\b", re.IGNORECASE
)
_VISITOR_COUNT_RE = re.compile(
    r"\b\d[\d,.]*\+?\s*(?:visitors?|views?|readers?|online|active now|people)\b", re.IGNORECASE
)
_COPYRIGHT_YEAR_RE = re.compile(r"(?:©|\(c\)|copyright)\s*\d{4}(?:\s*[-–]\s*\d{4})?", re.IGNORECASE)

_DYNAMIC_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_UUID_RE, "<UUID>"),
    (_ISO_DATETIME_RE, "<DATE>"),
    (_LONG_DATE_RE, "<DATE>"),
    (_EPOCH_RE, "<EPOCH>"),
    (_RELATIVE_TIME_RE, "<RELTIME>"),
    (_CLOCK_RE, "<TIME>"),
    (_COPYRIGHT_YEAR_RE, "<COPYRIGHT>"),
    (_TRACKING_PARAM_RE, "?<TRACKING>"),
    (_CACHE_BUST_RE, ".<HASH>."),
    (_VISITOR_COUNT_RE, "<COUNTER>"),
    (_LONG_HEX_RE, "<HEX>"),
)


@dataclass(slots=True)
class ContentBlock:
    """One comparable unit of visible page content."""

    text: str
    location: str = "body"
    tag: str = "p"
    depth: int = 0
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def canonical(self) -> str:
        """Aggressively normalised form used for noise detection."""
        return canonicalise(self.text)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self.text)


def collapse_whitespace(text: str) -> str:
    """Collapse all runs of whitespace to a single space and trim."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def strip_dynamic_tokens(text: str) -> str:
    """Replace values that change on every page load with stable placeholders."""
    for pattern, placeholder in _DYNAMIC_PATTERNS:
        text = pattern.sub(placeholder, text)
    return text


def canonicalise(text: str) -> str:
    """Fully normalise a string for equality comparison.

    Lower-cased, whitespace-collapsed, punctuation-trimmed and with every known
    dynamic token masked.  Used to decide whether two visibly different strings
    are actually the same content.
    """
    text = collapse_whitespace(text)
    text = strip_dynamic_tokens(text)
    text = text.casefold()
    # Normalise punctuation/quote variants that CMSs flip-flop between.
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[\s ]+", " ", text)
    return text.strip(" .,;:!•|-")


def content_hash(text: str) -> str:
    """Stable SHA-256 of canonicalised content."""
    return hashlib.sha256(canonicalise(text).encode("utf-8")).hexdigest()


def _classify_location(node: Tag) -> str:
    """Walk up the DOM to find the most specific location label for a node."""
    current: Tag | None = node
    depth = 0
    while current is not None and depth < 25:
        name = (current.name or "").lower()
        if name in _TAG_LOCATIONS:
            return _TAG_LOCATIONS[name]
        if name == "main" or (current.get("role") == "main"):
            return "main"

        identifier = " ".join(
            filter(
                None,
                [
                    str(current.get("id") or ""),
                    " ".join(current.get("class") or []),
                    str(current.get("data-section") or ""),
                    str(current.get("aria-label") or ""),
                    str(current.get("role") or ""),
                ],
            )
        ).lower()

        if identifier:
            for label, needles in _LOCATION_HINTS:
                if any(needle in identifier for needle in needles):
                    return label

        current = current.parent if isinstance(current.parent, Tag) else None
        depth += 1
    return "body"


def _looks_like_container(node: Tag) -> bool:
    """True when a node exists only to wrap other block elements."""
    for child in node.children:
        # A wrapper whose child blocks carry the text themselves.
        if (
            isinstance(child, Tag)
            and child.name in _BLOCK_TAGS
            and collapse_whitespace(child.get_text(" ", strip=True))
        ):
            return True
    return False


def parse_html(html: str) -> BeautifulSoup:
    """Parse HTML with lxml, falling back to the stdlib parser."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - only when lxml is unavailable
        logger.debug("lxml unavailable, falling back to html.parser")
        return BeautifulSoup(html, "html.parser")


def extract_blocks(html: str, *, drop_invisible: bool = True) -> list[ContentBlock]:
    """Extract ordered, visible content blocks from an HTML document.

    Navigation, footers and cookie banners are intentionally preserved and
    labelled so the noise filter (not the parser) gets to reject them.
    """
    if not html or not html.strip():
        return []

    soup = parse_html(html)

    if drop_invisible:
        for tag_name in _INVISIBLE_TAGS:
            for node in soup.find_all(tag_name):
                node.decompose()
        for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()
        # Explicitly hidden content is not competitor-visible.
        hidden_selector = (
            '[hidden], [aria-hidden="true"], '
            '[style*="display:none"], [style*="display: none"]'
        )
        for node in soup.select(hidden_selector):
            if isinstance(node, Tag):
                node.decompose()

    blocks: list[ContentBlock] = []
    seen_spans: set[int] = set()

    body = soup.body or soup
    for node in body.find_all(True):
        if not isinstance(node, Tag):
            continue
        if node.name not in _BLOCK_TAGS:
            continue
        if id(node) in seen_spans:
            continue
        if _looks_like_container(node):
            continue

        text = collapse_whitespace(node.get_text(" ", strip=True))
        if not text:
            continue
        # Skip single characters and pure punctuation/bullets.
        if len(text) < 2 or not any(ch.isalnum() for ch in text):
            continue

        seen_spans.add(id(node))
        blocks.append(
            ContentBlock(
                text=text,
                location=_classify_location(node),
                tag=node.name,
                depth=len(list(node.parents)),
                attrs={
                    "class": " ".join(node.get("class") or []),
                    "id": str(node.get("id") or ""),
                    "href": str(node.get("href") or ""),
                },
            )
        )

    # Documents with no recognised block tags (e.g. plain text) still need content.
    if not blocks:
        fallback = collapse_whitespace(soup.get_text(" ", strip=True))
        if fallback:
            blocks = [
                ContentBlock(text=line.strip(), location="body", tag="p")
                for line in re.split(r"(?<=[.!?])\s+", fallback)
                if line.strip()
            ]
    return blocks


def extract_title(html: str) -> str | None:
    """Return the document title, if any."""
    try:
        soup = parse_html(html)
        if soup.title and soup.title.string:
            return collapse_whitespace(str(soup.title.string))[:500]
        h1 = soup.find("h1")
        if h1:
            return collapse_whitespace(h1.get_text(" ", strip=True))[:500] or None
    except Exception:  # pragma: no cover - defensive
        logger.debug("Failed to extract title", exc_info=True)
    return None


def normalize_html(html: str) -> str:
    """Return the readable text of a page as newline-separated blocks."""
    blocks = extract_blocks(html)
    return "\n".join(block.text for block in blocks)


def normalize_text(text: str) -> str:
    """Normalise already-extracted plain text (whitespace only)."""
    lines = [collapse_whitespace(line) for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def word_count(text: str) -> int:
    """Count words in normalised text."""
    return len([w for w in re.split(r"\s+", text or "") if w])


def blocks_to_text(blocks: list[ContentBlock]) -> str:
    """Serialise blocks back to newline-separated text."""
    return "\n".join(block.text for block in blocks)


def is_boilerplate_location(location: str) -> bool:
    """True for page regions that are chrome rather than messaging."""
    return location in {"navigation", "footer", "cookie_banner", "advertisement", "sidebar"}
