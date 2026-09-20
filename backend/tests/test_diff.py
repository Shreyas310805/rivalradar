"""Tests for the diff engine and the noise filter."""

from __future__ import annotations

from app.diff.engine import diff_html, diff_text, inline_word_diff
from app.diff.noise import evaluate_noise, filter_noise, meaningful_only, noise_breakdown
from app.diff.types import DetectedChange, DiffStats
from app.models.entities import ChangeType


def _change(before: str, after: str, **kwargs) -> DetectedChange:
    """Build a change with a sensible default magnitude."""
    kwargs.setdefault("magnitude", 0.5)
    return DetectedChange(before=before, after=after, **kwargs)


class TestUnchangedPages:
    def test_identical_html_yields_no_changes(self, pricing_page_v1):
        assert diff_html(pricing_page_v1, pricing_page_v1) == []

    def test_whitespace_only_difference_is_filtered(self):
        before = "<body><main><p>Pro Plan costs money</p></main></body>"
        after = "<body><main><p>Pro    Plan   costs money</p></main></body>"
        changes = filter_noise(diff_html(before, after))
        assert meaningful_only(changes) == []

    def test_empty_documents(self):
        assert diff_html("", "") == []


class TestTextChanges:
    def test_detects_text_addition(self):
        before = "<body><main><p>First paragraph here</p></main></body>"
        after = "<body><main><p>First paragraph here</p><p>Second paragraph here</p></main></body>"
        changes = diff_html(before, after)
        assert any("Second paragraph" in (c.after or "") for c in changes)
        assert any(c.change_type == ChangeType.ADDED.value for c in changes)

    def test_detects_text_removal(self):
        before = "<body><main><p>Keep this line</p><p>Remove this line</p></main></body>"
        after = "<body><main><p>Keep this line</p></main></body>"
        changes = diff_html(before, after)
        assert any("Remove this line" in (c.before or "") for c in changes)
        assert any(c.change_type == ChangeType.REMOVED.value for c in changes)

    def test_detects_modification_as_a_pair(self):
        before = "<body><main><p>Our basic analytics dashboard</p></main></body>"
        after = "<body><main><p>Our AI-powered analytics dashboard</p></main></body>"
        changes = diff_html(before, after)
        assert len(changes) == 1
        assert "basic" in changes[0].before
        assert "AI-powered" in changes[0].after

    def test_headline_change_is_typed(self):
        before = "<body><main><h1>Built for teams</h1></main></body>"
        after = "<body><main><h1>Built for enterprises</h1></main></body>"
        changes = diff_html(before, after)
        assert changes[0].change_type == ChangeType.HEADLINE_CHANGE.value

    def test_diff_text_works_without_html(self):
        changes = diff_text("line one here\nline two here", "line one here\nline two changed")
        assert len(changes) == 1


class TestMagnitude:
    def test_larger_edits_score_higher(self):
        small = diff_html(
            "<body><main><p>The quick brown fox jumps over it</p></main></body>",
            "<body><main><p>The quick brown fox jumps over them</p></main></body>",
        )
        large = diff_html(
            "<body><main><p>The quick brown fox jumps over it</p></main></body>",
            "<body><main><p>Completely different sentence entirely</p></main></body>",
        )
        assert large[0].magnitude > small[0].magnitude

    def test_magnitude_is_bounded(self):
        for change in diff_html(
            "<body><main><p>alpha beta gamma</p></main></body>",
            "<body><main><p>delta epsilon zeta</p></main></body>",
        ):
            assert 0.0 <= change.magnitude <= 1.0


class TestRawChangeAccounting:
    def test_dynamic_token_churn_counts_as_raw_change(self, pricing_page_v1, pricing_page_v2):
        """Noise must be *counted* then *rejected*, not silently hidden.

        This is what makes the noise-reduction metric meaningful.
        """
        changes = diff_html(pricing_page_v1, pricing_page_v2)
        footer = [c for c in changes if c.location == "footer"]
        assert footer, "footer churn should appear in the raw change list"

        filter_noise(changes)
        assert all(c.is_noise for c in footer)

    def test_funnel_adds_up(self, pricing_page_v1, pricing_page_v2):
        changes = filter_noise(diff_html(pricing_page_v1, pricing_page_v2))
        stats = DiffStats.from_changes(changes)
        assert stats.raw_changes == stats.noise_changes + stats.meaningful_changes
        assert stats.raw_changes == len(changes)


class TestNoiseRules:
    def test_rejects_canonically_identical(self):
        change = _change(
            "Copyright 2025 Acme. All rights reserved.",
            "Copyright 2026 Acme. All rights reserved.",
            magnitude=0.02,
        )
        assert evaluate_noise(change) is not None

    def test_rejects_navigation(self):
        assert evaluate_noise(_change("Home Pricing", "Home Pricing Blog", location="navigation"))

    def test_rejects_cookie_banner(self):
        change = _change(
            "We use cookies to improve your experience",
            "We use cookies to enhance your experience",
            location="cookie_banner",
        )
        assert evaluate_noise(change) is not None

    def test_rejects_live_counters(self):
        change = _change("Trusted by 4,200 developers", "Trusted by 5,100 developers")
        assert evaluate_noise(change) is not None

    def test_rejects_tiny_magnitude(self):
        change = _change("A fairly long sentence about nothing", "A fairly long sentence about noting", magnitude=0.02)
        assert evaluate_noise(change) is not None

    def test_rejects_reworded_pricing_with_same_amounts(self):
        change = _change("Pro plan: Rs 999 per month", "Pro plan - Rs 999 / month", magnitude=0.25)
        assert evaluate_noise(change) is not None

    def test_keeps_real_price_change(self):
        assert evaluate_noise(_change("Rs 999/month", "Rs 1499/month", location="pricing")) is None

    def test_keeps_price_change_even_in_footer(self):
        """A strong signal survives a boilerplate location."""
        change = _change("Starting at $19/month", "Starting at $39/month", location="footer")
        assert evaluate_noise(change) is None

    def test_keeps_plan_limit_change(self):
        assert evaluate_noise(_change("5 projects", "10 projects", location="pricing")) is None

    def test_keeps_integration_addition(self):
        change = _change(
            "Integrates with Slack and GitHub",
            "Integrates with Slack, GitHub and Salesforce",
            location="integrations",
        )
        assert evaluate_noise(change) is None

    def test_keeps_feature_launch(self):
        change = _change("", "Introducing AI-powered analytics for every plan", location="product")
        assert evaluate_noise(change) is None

    def test_rejects_too_short_without_signal(self):
        assert evaluate_noise(_change("Blog", "News")) is not None


class TestFilterNoise:
    def test_annotates_every_change(self, pricing_page_v1, pricing_page_v2):
        changes = filter_noise(diff_html(pricing_page_v1, pricing_page_v2))
        assert all(isinstance(c.is_noise, bool) for c in changes)
        assert all(c.noise_reason for c in changes if c.is_noise)

    def test_returns_all_changes_not_only_survivors(self, pricing_page_v1, pricing_page_v2):
        raw = diff_html(pricing_page_v1, pricing_page_v2)
        assert len(filter_noise(raw)) == len(raw)

    def test_reduces_noise_on_a_realistic_page(self, pricing_page_v1, pricing_page_v2):
        changes = filter_noise(diff_html(pricing_page_v1, pricing_page_v2))
        stats = DiffStats.from_changes(changes)
        assert stats.raw_changes > 0
        assert stats.noise_changes > 0
        assert stats.meaningful_changes > 0
        assert 0 < stats.noise_reduction < 100

    def test_keeps_the_price_change(self, pricing_page_v1, pricing_page_v2):
        survivors = meaningful_only(filter_noise(diff_html(pricing_page_v1, pricing_page_v2)))
        assert any("1499" in (c.after or "") for c in survivors)

    def test_breakdown_counts_reasons(self, pricing_page_v1, pricing_page_v2):
        changes = filter_noise(diff_html(pricing_page_v1, pricing_page_v2))
        breakdown = noise_breakdown(changes)
        assert sum(breakdown.values()) == sum(1 for c in changes if c.is_noise)

    def test_a_broken_rule_cannot_crash_the_filter(self, monkeypatch):
        """A rule raising must degrade to 'not noise', never propagate."""
        import app.diff.noise as noise_module

        def exploding_rule(_change):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            noise_module, "_RULES", (("exploding", exploding_rule),), raising=True
        )
        assert evaluate_noise(_change("a", "b")) is None


class TestDiffStats:
    def test_noise_reduction_maths(self):
        stats = DiffStats(raw_changes=100, noise_changes=83, meaningful_changes=17)
        assert stats.noise_reduction == 83.0

    def test_zero_raw_changes_is_safe(self):
        assert DiffStats().noise_reduction == 0.0

    def test_merge(self):
        merged = DiffStats(10, 6, 4, 2).merge(DiffStats(20, 15, 5, 3))
        assert merged.raw_changes == 30
        assert merged.noise_changes == 21
        assert merged.high_impact_changes == 5

    def test_from_changes_counts_high_impact(self):
        changes = [
            DetectedChange(relevance_score=90.0),
            DetectedChange(relevance_score=50.0),
            DetectedChange(relevance_score=10.0, is_noise=True),
        ]
        stats = DiffStats.from_changes(changes)
        assert stats.raw_changes == 3
        assert stats.noise_changes == 1
        assert stats.meaningful_changes == 2
        assert stats.high_impact_changes == 1


class TestInlineWordDiff:
    def test_marks_insertions_and_deletions(self):
        segments = inline_word_diff("Rs 999 per month", "Rs 1499 per month")
        ops = {segment["op"] for segment in segments}
        assert "delete" in ops
        assert "insert" in ops
        assert "equal" in ops

    def test_identical_strings_are_all_equal(self):
        assert all(s["op"] == "equal" for s in inline_word_diff("same text", "same text"))

    def test_handles_empty_sides(self):
        assert all(s["op"] == "insert" for s in inline_word_diff("", "brand new"))
