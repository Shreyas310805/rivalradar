"""Tests for deterministic change classification."""

from __future__ import annotations

import pytest

from app.diff.engine import diff_html
from app.diff.noise import filter_noise, meaningful_only
from app.diff.types import DetectedChange
from app.intelligence.classifier import classify, classify_changes
from app.models.entities import ChangeCategory, ChangeType


def _change(before: str, after: str, **kwargs) -> DetectedChange:
    kwargs.setdefault("magnitude", 0.5)
    return DetectedChange(before=before, after=after, **kwargs)


class TestPricingClassification:
    @pytest.mark.parametrize(
        ("before", "after"),
        [
            ("Rs 999/month", "Rs 1499/month"),
            ("$19 per month", "$29 per month"),
            ("₹999 per month", "₹1,499 per month"),
            ("EUR 49 monthly", "EUR 79 monthly"),
            ("999 USD annually", "1499 USD annually"),
        ],
    )
    def test_detects_currency_formats(self, before, after):
        result = classify(_change(before, after, location="pricing"))
        assert result.category == ChangeCategory.PRICING.value
        assert result.change_type == ChangeType.PRICE_CHANGE.value

    def test_captures_price_direction_and_delta(self):
        result = classify(_change("Rs 999/month", "Rs 1499/month", location="pricing"))
        assert result.signals["price_direction"] == 1.0
        assert result.signals["price_delta_ratio"] == pytest.approx(0.5, abs=0.01)

    def test_detects_price_decrease(self):
        result = classify(_change("$99/month", "$49/month", location="pricing"))
        assert result.signals["price_direction"] == -1.0

    def test_detects_free_to_paid_shift(self):
        result = classify(_change("Free forever plan", "$19 per month plan", location="pricing"))
        assert result.category == ChangeCategory.PRICING.value
        assert result.signals.get("free_tier_shift") == 1.0

    def test_produces_evidence(self):
        result = classify(_change("Rs 999/month", "Rs 1499/month", location="pricing"))
        assert any("999" in item and "1499" in item for item in result.evidence)

    def test_confidence_is_high_for_clear_price_move(self):
        result = classify(_change("Rs 999/month", "Rs 1499/month", location="pricing"))
        assert result.confidence > 0.8


class TestHiringClassification:
    def test_detects_ml_roles(self):
        result = classify(
            _change("", "Machine Learning Engineer - Remote - Full-time", location="careers")
        )
        assert result.category == ChangeCategory.HIRING.value
        assert result.change_type == ChangeType.HIRING_SIGNAL.value
        assert result.signals["ml_role_count"] >= 1

    def test_counts_multiple_ml_roles(self, careers_page_v1, careers_page_v2):
        changes = meaningful_only(filter_noise(diff_html(careers_page_v1, careers_page_v2)))
        classify_changes(changes)
        hiring = [c for c in changes if c.category == ChangeCategory.HIRING.value]
        assert hiring, "expected hiring changes to be detected"
        assert sum(c.signals.get("ml_role_count", 0) for c in hiring) >= 2

    def test_detects_generic_engineering_roles(self):
        result = classify(_change("", "Senior Backend Engineer - Remote", location="careers"))
        assert result.category == ChangeCategory.HIRING.value

    def test_role_words_without_hiring_context_are_not_hiring(self):
        """A blog post mentioning ML engineers is not a hiring signal."""
        result = classify(
            _change(
                "",
                "Our machine learning engineer wrote about model drift in production systems",
                location="blog",
            )
        )
        assert result.category != ChangeCategory.HIRING.value


class TestFeatureClassification:
    @pytest.mark.parametrize(
        "text",
        [
            "Introducing AI-powered analytics for all plans",
            "Now available: automated release notes",
            "We are launching a redesigned dashboard experience",
            "Now supports real-time collaborative editing",
        ],
    )
    def test_detects_launch_language(self, text):
        result = classify(_change("", text, location="product"))
        assert result.category in {
            ChangeCategory.FEATURES.value,
            ChangeCategory.PRODUCT.value,
        }

    def test_detects_ai_mentions(self):
        result = classify(_change("Basic analytics", "AI-powered analytics"))
        assert result.signals.get("ai_mention") == 1.0

    def test_detects_plan_limit_change(self):
        result = classify(_change("5 projects", "10 projects", location="pricing"))
        assert result.signals.get("plan_limit_changed") == 1.0
        assert result.category == ChangeCategory.FEATURES.value

    def test_plan_limit_evidence_names_the_numbers(self):
        result = classify(_change("10 GB storage", "25 GB storage", location="pricing"))
        assert any("10" in item and "25" in item for item in result.evidence)


class TestProductAndIntegrations:
    def test_detects_product_launch(self):
        result = classify(
            _change("", "Launching DataForge Lineage, our new product for data lineage")
        )
        assert result.category in {
            ChangeCategory.PRODUCT.value,
            ChangeCategory.FEATURES.value,
        }

    def test_detects_new_integration_partners(self):
        result = classify(
            _change(
                "Integrates with Slack",
                "Integrates with Slack, Salesforce and Snowflake",
                location="integrations",
            )
        )
        assert result.category == ChangeCategory.INTEGRATIONS.value
        assert result.signals["new_partner_count"] >= 2

    def test_integration_evidence_names_partners(self):
        result = classify(
            _change("Works with Slack", "Works with Slack and Databricks", location="integrations")
        )
        assert any("databricks" in item.lower() for item in result.evidence)


class TestMessagingAndFallback:
    def test_detects_positioning_change(self):
        result = classify(
            _change(
                "Ship infrastructure without the yak shaving",
                "The enterprise deployment platform for regulated teams",
                change_type=ChangeType.HEADLINE_CHANGE.value,
                location="header",
                magnitude=0.8,
            )
        )
        assert result.category == ChangeCategory.MESSAGING.value

    def test_unremarkable_text_falls_back_to_other(self):
        result = classify(
            _change("Our office is in Berlin", "Our office is in Hamburg", location="body")
        )
        assert result.category == ChangeCategory.OTHER.value

    def test_fallback_still_carries_confidence(self):
        result = classify(_change("some text here", "other text here"))
        assert 0.0 < result.confidence < 1.0

    def test_classify_changes_mutates_in_place(self):
        changes = [_change("Rs 999/month", "Rs 1499/month", location="pricing")]
        classify_changes(changes)
        assert changes[0].category == ChangeCategory.PRICING.value
        assert changes[0].classifier_confidence > 0
        assert changes[0].signals
