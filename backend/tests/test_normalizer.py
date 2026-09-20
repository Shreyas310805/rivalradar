"""Tests for HTML normalisation and content extraction."""

from __future__ import annotations

import pytest

from app.scrapers.normalizer import (
    ContentBlock,
    canonicalise,
    collapse_whitespace,
    content_hash,
    extract_blocks,
    extract_title,
    is_boilerplate_location,
    normalize_html,
    strip_dynamic_tokens,
    word_count,
)


class TestWhitespace:
    def test_collapses_runs_of_whitespace(self):
        assert collapse_whitespace("  hello \n\t  world  ") == "hello world"

    def test_handles_empty_and_none_like(self):
        assert collapse_whitespace("") == ""
        assert collapse_whitespace("   \n\t ") == ""

    def test_strips_zero_width_characters(self):
        assert collapse_whitespace("pri​ce") == "price"

    def test_whitespace_only_difference_canonicalises_equal(self):
        assert canonicalise("Pro   Plan\n") == canonicalise("Pro Plan")


class TestDynamicTokens:
    def test_masks_uuid(self):
        masked = strip_dynamic_tokens("id 8f14e45f-ceea-467a-9a1e-4b2d3c9f0011 here")
        assert "<UUID>" in masked
        assert "8f14e45f" not in masked

    def test_masks_iso_timestamp(self):
        assert "<DATE>" in strip_dynamic_tokens("Generated 2025-04-01T10:22:31Z")

    def test_masks_long_date(self):
        assert "<DATE>" in strip_dynamic_tokens("Posted on January 14, 2026 by us")

    def test_masks_relative_time(self):
        assert "<RELTIME>" in strip_dynamic_tokens("updated 3 hours ago")

    def test_masks_copyright_year(self):
        a = canonicalise("Copyright 2025 NovaStack. All rights reserved.")
        b = canonicalise("Copyright 2026 NovaStack. All rights reserved.")
        assert a == b

    def test_masks_tracking_parameters(self):
        a = canonicalise("Visit /home?utm_source=twitter")
        b = canonicalise("Visit /home?utm_source=facebook")
        assert a == b

    def test_masks_cache_busting_hashes(self):
        a = canonicalise("app.a1b2c3d4e5f6.js")
        b = canonicalise("app.9f8e7d6c5b4a.js")
        assert a == b

    def test_preserves_real_content(self):
        masked = strip_dynamic_tokens("Pro Plan costs Rs 1499 per month")
        assert "1499" in masked
        assert "Pro Plan" in masked


class TestCanonicalise:
    def test_is_case_insensitive(self):
        assert canonicalise("AI Analytics") == canonicalise("ai analytics")

    def test_normalises_smart_quotes_and_dashes(self):
        assert canonicalise("we’re — here") == canonicalise("we're - here")

    def test_different_content_stays_different(self):
        assert canonicalise("Rs 999/month") != canonicalise("Rs 1499/month")


class TestContentHash:
    def test_is_stable_for_equivalent_content(self):
        assert content_hash("Pro  Plan") == content_hash("Pro Plan")

    def test_differs_for_different_content(self):
        assert content_hash("Rs 999") != content_hash("Rs 1499")

    def test_returns_sha256_hex(self):
        assert len(content_hash("anything")) == 64


class TestExtractBlocks:
    def test_extracts_visible_text(self, pricing_page_v1):
        blocks = extract_blocks(pricing_page_v1)
        texts = [block.text for block in blocks]
        assert any("Rs 999/month" in text for text in texts)
        assert any("Simple pricing" in text for text in texts)

    def test_drops_script_and_style(self):
        html = "<html><body><p>Real</p><script>var x=1;</script><style>p{color:red}</style></body></html>"
        texts = [block.text for block in extract_blocks(html)]
        assert "Real" in texts
        assert not any("var x" in text for text in texts)
        assert not any("color:red" in text for text in texts)

    def test_drops_hidden_elements(self):
        html = '<html><body><p>Shown</p><p hidden>Hidden</p><p aria-hidden="true">Also hidden</p></body></html>'
        texts = [block.text for block in extract_blocks(html)]
        assert "Shown" in texts
        assert "Hidden" not in texts

    def test_labels_navigation_and_footer(self, pricing_page_v1):
        blocks = extract_blocks(pricing_page_v1)
        locations = {block.location for block in blocks}
        assert "navigation" in locations
        assert "footer" in locations

    def test_labels_pricing_section(self, pricing_page_v1):
        blocks = extract_blocks(pricing_page_v1)
        pricing = [b for b in blocks if b.location == "pricing"]
        assert pricing, "expected at least one block labelled as pricing"

    def test_labels_cookie_banner(self, pricing_page_v1):
        locations = {block.location for block in extract_blocks(pricing_page_v1)}
        assert "cookie_banner" in locations

    def test_handles_empty_input(self):
        assert extract_blocks("") == []
        assert extract_blocks("   ") == []

    def test_handles_malformed_html(self):
        blocks = extract_blocks("<html><body><p>Unclosed <div>tags")
        assert isinstance(blocks, list)

    def test_skips_pure_punctuation(self):
        texts = [b.text for b in extract_blocks("<body><p>...</p><p>Real content here</p></body>")]
        assert "..." not in texts


class TestTitleAndCounts:
    def test_extracts_title_tag(self, pricing_page_v1):
        assert extract_title(pricing_page_v1) == "NovaStack Pricing"

    def test_falls_back_to_h1(self):
        assert extract_title("<html><body><h1>Fallback</h1></body></html>") == "Fallback"

    def test_returns_none_without_title(self):
        assert extract_title("<html><body><p>no title</p></body></html>") is None

    def test_survives_garbage_input(self):
        assert extract_title("not html at all") is None

    def test_word_count(self):
        assert word_count("one two three") == 3
        assert word_count("") == 0

    def test_normalize_html_returns_lines(self, pricing_page_v1):
        text = normalize_html(pricing_page_v1)
        assert "Rs 999/month" in text
        assert "\n" in text


class TestLocationHelpers:
    @pytest.mark.parametrize(
        "location", ["navigation", "footer", "cookie_banner", "advertisement", "sidebar"]
    )
    def test_boilerplate_locations(self, location):
        assert is_boilerplate_location(location)

    @pytest.mark.parametrize("location", ["pricing", "main", "careers", "product"])
    def test_content_locations(self, location):
        assert not is_boilerplate_location(location)


class TestContentBlock:
    def test_canonical_property(self):
        block = ContentBlock(text="Copyright 2025 Acme")
        assert "<copyright>" in block.canonical or "copyright" in block.canonical

    def test_len(self):
        assert len(ContentBlock(text="abcd")) == 4
