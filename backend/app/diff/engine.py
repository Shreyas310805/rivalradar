"""Structural page-diff engine.

The engine never compares raw HTML strings.  It works on ordered
:class:`~app.scrapers.normalizer.ContentBlock` sequences and uses
``difflib.SequenceMatcher`` over *canonicalised* block keys so that reordering
and cosmetic markup churn do not masquerade as content changes.

Pipeline position::

    HTML A ─┐
            ├─ extract_blocks ─ align ─ opcodes ─ pair up ─ DetectedChange[]
    HTML B ─┘
"""

from __future__ import annotations

import difflib
import re

from app.config.logging import get_logger
from app.diff.types import DetectedChange
from app.models.entities import ChangeType
from app.scrapers.normalizer import ContentBlock, canonicalise, extract_blocks

logger = get_logger(__name__)

# Blocks longer than this are truncated in the stored before/after payload.
MAX_SNIPPET_CHARS = 1200

# Two modified blocks are treated as the *same* block being edited (rather than
# an unrelated delete + insert) when they are at least this similar.
_PAIRING_THRESHOLD = 0.40


def _similarity(a: str, b: str) -> float:
    """Ratio in [0, 1] between two canonicalised strings."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _magnitude(before: str, after: str) -> float:
    """How large a change is, in [0, 1].

    1.0 means completely different content; 0.0 means identical.  Pure
    additions and removals are scaled by length so a one-word footer tweak does
    not outrank a rewritten pricing table.
    """
    before_c = canonicalise(before)
    after_c = canonicalise(after)
    if before_c == after_c:
        return 0.0
    if not before_c or not after_c:
        # Insertion or deletion: longer content means bigger change, capped.
        length = len(after_c or before_c)
        return round(min(1.0, 0.35 + length / 600.0), 4)
    return round(1.0 - _similarity(before_c, after_c), 4)


def _truncate(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    """Trim long snippets so the database stays readable."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _merge_location(before: ContentBlock | None, after: ContentBlock | None) -> str:
    """Pick the most informative location label of a block pair."""
    candidates = [b.location for b in (after, before) if b is not None]
    for candidate in candidates:
        if candidate not in {"body", "main"}:
            return candidate
    return candidates[0] if candidates else "body"


def _heading_tags() -> frozenset[str]:
    return frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def _initial_change_type(
    before: ContentBlock | None, after: ContentBlock | None
) -> str:
    """Cheap structural typing before the classifier refines it."""
    if before is None and after is not None:
        return ChangeType.ADDED.value
    if after is None and before is not None:
        return ChangeType.REMOVED.value
    if before is not None and after is not None:
        if before.tag in _heading_tags() or after.tag in _heading_tags():
            return ChangeType.HEADLINE_CHANGE.value
        return ChangeType.TEXT_CHANGE.value
    return ChangeType.MODIFIED.value


def _pair_replacements(
    before_blocks: list[ContentBlock], after_blocks: list[ContentBlock]
) -> list[tuple[ContentBlock | None, ContentBlock | None]]:
    """Greedily match removed blocks to added blocks within a replace opcode.

    Without this, editing one line in a paragraph block would emit an unrelated
    "removed" plus "added" pair, which reads terribly in a before/after UI.
    """
    pairs: list[tuple[ContentBlock | None, ContentBlock | None]] = []
    remaining_after = list(after_blocks)

    for old in before_blocks:
        best_index = -1
        best_score = _PAIRING_THRESHOLD
        old_key = canonicalise(old.text)
        for index, candidate in enumerate(remaining_after):
            score = _similarity(old_key, canonicalise(candidate.text))
            # Same location and tag is a strong hint the blocks correspond.
            if candidate.location == old.location:
                score += 0.08
            if candidate.tag == old.tag:
                score += 0.04
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0:
            pairs.append((old, remaining_after.pop(best_index)))
        else:
            pairs.append((old, None))

    pairs.extend((None, leftover) for leftover in remaining_after)
    return pairs


def _dedupe_repeated(changes: list[DetectedChange]) -> list[DetectedChange]:
    """Collapse identical changes repeated across a page.

    Repeated components (card grids, nav rendered twice for mobile/desktop)
    otherwise inflate the raw count with literal duplicates.
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[DetectedChange] = []
    for change in changes:
        key = (
            change.location,
            canonicalise(change.before)[:200],
            canonicalise(change.after)[:200],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(change)
    return unique


def diff_blocks(
    before_blocks: list[ContentBlock],
    after_blocks: list[ContentBlock],
    *,
    source_url: str = "",
) -> list[DetectedChange]:
    """Diff two block sequences into raw :class:`DetectedChange` objects.

    No noise filtering happens here — every structural difference is reported
    so the funnel can honestly measure how much of it turns out to be noise.
    """
    before_keys = [canonicalise(b.text) for b in before_blocks]
    after_keys = [canonicalise(b.text) for b in after_blocks]

    matcher = difflib.SequenceMatcher(None, before_keys, after_keys, autojunk=False)
    changes: list[DetectedChange] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            # Blocks aligned on their canonical key, but the *visible* text may
            # still differ (a copyright year, a session id, a rotating
            # timestamp).  A naive differ would flag every one of these, so we
            # emit them as raw changes and let the noise filter reject them.
            # Counting them here is what makes the noise-reduction metric real.
            for before_block, after_block in zip(
                before_blocks[i1:i2], after_blocks[j1:j2], strict=False
            ):
                if before_block.text == after_block.text:
                    continue
                changes.append(
                    DetectedChange(
                        change_type=ChangeType.MODIFIED.value,
                        location=_merge_location(before_block, after_block),
                        before=_truncate(before_block.text),
                        after=_truncate(after_block.text),
                        magnitude=_magnitude(before_block.text, after_block.text),
                        source_url=source_url,
                    )
                )
            continue

        if tag == "replace":
            pairs = _pair_replacements(before_blocks[i1:i2], after_blocks[j1:j2])
        elif tag == "delete":
            pairs = [(block, None) for block in before_blocks[i1:i2]]
        else:  # insert
            pairs = [(None, block) for block in after_blocks[j1:j2]]

        for old, new in pairs:
            before_text = old.text if old else ""
            after_text = new.text if new else ""
            if before_text == after_text:
                continue
            changes.append(
                DetectedChange(
                    change_type=_initial_change_type(old, new),
                    location=_merge_location(old, new),
                    before=_truncate(before_text),
                    after=_truncate(after_text),
                    magnitude=_magnitude(before_text, after_text),
                    source_url=source_url,
                )
            )

    return _dedupe_repeated(changes)


def diff_html(
    before_html: str,
    after_html: str,
    *,
    source_url: str = "",
) -> list[DetectedChange]:
    """Diff two HTML documents into raw detected changes."""
    before_blocks = extract_blocks(before_html)
    after_blocks = extract_blocks(after_html)
    logger.debug(
        "Diffing %d before-blocks against %d after-blocks for %s",
        len(before_blocks),
        len(after_blocks),
        source_url or "<unknown>",
    )
    return diff_blocks(before_blocks, after_blocks, source_url=source_url)


def diff_text(before_text: str, after_text: str, *, source_url: str = "") -> list[DetectedChange]:
    """Diff two already-extracted plain-text documents (line oriented)."""

    def to_blocks(text: str) -> list[ContentBlock]:
        return [
            ContentBlock(text=line.strip(), location="body", tag="p")
            for line in (text or "").splitlines()
            if line.strip()
        ]

    return diff_blocks(to_blocks(before_text), to_blocks(after_text), source_url=source_url)


def inline_word_diff(before: str, after: str) -> list[dict[str, str]]:
    """Produce word-level segments for the before/after comparison UI.

    Returns a list of ``{"op": "equal"|"delete"|"insert", "before", "after"}``
    segments so the frontend can highlight exactly what changed.
    """
    before_words = re.findall(r"\S+\s*", before or "")
    after_words = re.findall(r"\S+\s*", after or "")
    matcher = difflib.SequenceMatcher(None, before_words, after_words, autojunk=False)

    segments: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = "".join(before_words[i1:i2])
        new_chunk = "".join(after_words[j1:j2])
        if tag == "equal":
            segments.append({"op": "equal", "before": old_chunk, "after": new_chunk})
        elif tag == "replace":
            segments.append({"op": "delete", "before": old_chunk, "after": ""})
            segments.append({"op": "insert", "before": "", "after": new_chunk})
        elif tag == "delete":
            segments.append({"op": "delete", "before": old_chunk, "after": ""})
        else:
            segments.append({"op": "insert", "before": "", "after": new_chunk})
    return segments
