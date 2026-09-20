"""Tests for relevance scoring and severity banding."""

from __future__ import annotations

import pytest

from app.diff.types import DetectedChange
from app.intelligence.classifier import classify_changes
from app.intelligence.relevance import (
    WEIGHTS,
    blend_with_llm_score,
    is_high_impact,
    score_change,
    score_changes,
)
from app.models.entities import ChangeCategory, Severity


def _scored(before: str, after: str, **kwargs) -> DetectedChange:
    """Build, classify and score a change the way the pipeline does."""
    kwargs.setdefault("magnitude", 0.5)
    change = DetectedChange(before=before, after=after, **kwargs)
    classify_changes([change])
    score_changes([change])
    return change


class TestScoreRange:
    def test_scores_are_bounded(self):
        for change in (
            _scored("Rs 999/month", "Rs 1499/month", location="pricing"),
            _scored("a", "b", location="footer", magnitude=0.01),
            _scored("", "Introducing AI analytics", location="product", magnitude=1.0),
        ):
            assert 0.0 <= change.relevance_score <= 100.0

    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_breakdown_components_are_bounded(self):
        breakdown = score_change(_scored("Rs 999/month", "Rs 1499/month", location="pricing"))
        for key in ("business_impact", "customer_impact", "strategic_significance"):
            assert 0.0 <= getattr(breakdown, key) <= 1.0


class TestSeverityBands:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0, Severity.NOISE),
            (29.9, Severity.NOISE),
            (30, Severity.LOW),
            (49.9, Severity.LOW),
            (50, Severity.MEDIUM),
            (69.9, Severity.MEDIUM),
            (70, Severity.HIGH),
            (84.9, Severity.HIGH),
            (85, Severity.CRITICAL),
            (100, Severity.CRITICAL),
        ],
    )
    def test_band_boundaries(self, score, expected):
        assert Severity.from_score(score) is expected

    def test_high_impact_threshold(self):
        assert is_high_impact(70.0)
        assert is_high_impact(95.0)
        assert not is_high_impact(69.9)


class TestRankingBehaviour:
    def test_price_change_outranks_generic_copy(self):
        price = _scored("Rs 999/month", "Rs 1499/month", location="pricing")
        generic = _scored(
            "Our office is in Berlin now", "Our office is in Hamburg now", location="body"
        )
        assert price.relevance_score > generic.relevance_score

    def test_price_change_is_high_impact(self):
        change = _scored("Rs 999/month", "Rs 1499/month", location="pricing")
        assert change.relevance_score >= 70.0
        assert change.severity in {Severity.HIGH.value, Severity.CRITICAL.value}

    def test_ml_hiring_signal_is_meaningful(self):
        change = _scored(
            "",
            "Machine Learning Engineer - Remote. Senior Machine Learning Engineer - Remote.",
            location="careers",
        )
        assert change.category == ChangeCategory.HIRING.value
        assert change.relevance_score >= 50.0

    def test_footer_change_is_downweighted(self):
        footer = _scored(
            "Our address is 10 Main Street", "Our address is 12 Main Street", location="footer"
        )
        body = _scored(
            "Our address is 10 Main Street", "Our address is 12 Main Street", location="main"
        )
        assert footer.relevance_score < body.relevance_score

    def test_noise_is_capped_below_the_low_band(self):
        change = DetectedChange(
            before="Copyright 2025", after="Copyright 2026", is_noise=True, magnitude=0.9
        )
        classify_changes([change])
        breakdown = score_change(change)
        assert breakdown.score <= 29.0
        assert breakdown.severity == Severity.NOISE.value

    def test_bigger_price_move_scores_higher(self):
        small = _scored("$100/month", "$105/month", location="pricing")
        large = _scored("$100/month", "$300/month", location="pricing")
        assert large.relevance_score > small.relevance_score


class TestExplainability:
    def test_breakdown_is_serialisable(self):
        payload = score_change(_scored("Rs 999/month", "Rs 1499/month", location="pricing")).to_dict()
        for key in (
            "business_impact",
            "customer_impact",
            "strategic_significance",
            "change_magnitude",
            "confidence",
            "weights",
            "score",
            "severity",
        ):
            assert key in payload

    def test_notes_explain_the_score(self):
        breakdown = score_change(_scored("Rs 999/month", "Rs 1499/month", location="pricing"))
        assert breakdown.notes


class TestLLMBlending:
    def test_no_llm_score_keeps_the_deterministic_value(self):
        assert blend_with_llm_score(72.0, None) == 72.0

    def test_llm_can_nudge_within_the_band(self):
        assert blend_with_llm_score(70.0, 76.0) == 76.0

    def test_llm_cannot_move_the_score_beyond_the_cap(self):
        """An LLM claiming 100 on a 50-score change moves it by at most 12."""
        assert blend_with_llm_score(50.0, 100.0) == 62.0
        assert blend_with_llm_score(50.0, 0.0) == 38.0

    def test_result_stays_in_range(self):
        assert 0.0 <= blend_with_llm_score(5.0, 0.0) <= 100.0
        assert 0.0 <= blend_with_llm_score(98.0, 100.0) <= 100.0
