"""End-to-end tests for the LangGraph pipeline, LLM layer and scan service."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.agents.graph import build_graph, run_pipeline
from app.agents.state import new_state
from app.llm.base import LLMError, LLMProvider, LLMResponse, extract_json
from app.llm.factory import build_provider, reset_provider
from app.llm.heuristic_provider import HeuristicProvider
from app.models.entities import ChangeCategory, Severity
from app.schemas.llm import ChangeAnalysis, DigestNarrative
from app.scrapers.fetcher import fetch_html_string


def _snapshot(html: str, content_hash: str, url: str = "https://x.com/pricing") -> dict:
    return {
        "url": url,
        "raw_html": html,
        "normalized_text": "",
        "content_hash": content_hash,
    }


class TestGraphTopology:
    def test_graph_compiles(self):
        assert build_graph() is not None

    def test_state_defaults(self):
        state = new_state({"id": 1, "name": "X"}, {"id": 1, "url": "https://x.com"})
        assert state["raw_changes"] == []
        assert state["skipped"] is False


class TestPipelineExecution:
    def test_full_run_produces_intelligence(self, pricing_page_v1, pricing_page_v2):
        state = run_pipeline(
            {"id": 1, "name": "NovaStack"},
            {"id": 1, "url": "https://x.com/pricing"},
            _snapshot(pricing_page_v2, "b"),
            _snapshot(pricing_page_v1, "a"),
        )
        assert not state.get("errors")
        assert state["stats"]["raw_changes"] > 0
        assert state["stats"]["meaningful_changes"] > 0
        assert state["intelligence"]

    def test_funnel_is_internally_consistent(self, pricing_page_v1, pricing_page_v2):
        stats = run_pipeline(
            {"id": 1, "name": "NovaStack"},
            {"id": 1, "url": "https://x.com/pricing"},
            _snapshot(pricing_page_v2, "b"),
            _snapshot(pricing_page_v1, "a"),
        )["stats"]
        assert stats["raw_changes"] == stats["noise_changes"] + stats["meaningful_changes"]
        assert stats["high_impact_changes"] <= stats["meaningful_changes"]
        assert stats["noise_reduction"] == pytest.approx(
            stats["noise_changes"] / stats["raw_changes"] * 100, abs=0.01
        )

    def test_detects_the_price_rise(self, pricing_page_v1, pricing_page_v2):
        state = run_pipeline(
            {"id": 1, "name": "NovaStack"},
            {"id": 1, "url": "https://x.com/pricing"},
            _snapshot(pricing_page_v2, "b"),
            _snapshot(pricing_page_v1, "a"),
        )
        pricing = [
            item
            for item in state["intelligence"]
            if item["category"] == ChangeCategory.PRICING.value
        ]
        assert pricing, "expected the price change to be surfaced"
        assert pricing[0]["relevance_score"] >= 70
        assert "1499" in (pricing[0]["after"] or "")

    def test_identical_hash_short_circuits(self, pricing_page_v1):
        """An unchanged page must cost zero LLM calls."""
        state = run_pipeline(
            {"id": 1, "name": "NovaStack"},
            {"id": 1, "url": "https://x.com/pricing"},
            _snapshot(pricing_page_v1, "same"),
            _snapshot(pricing_page_v1, "same"),
        )
        assert state["skipped"] is True
        assert "No meaningful page change" in state["skip_reason"]
        assert state["intelligence"] == []

    def test_first_scan_records_a_baseline(self, pricing_page_v1):
        state = run_pipeline(
            {"id": 1, "name": "NovaStack"},
            {"id": 1, "url": "https://x.com/pricing"},
            _snapshot(pricing_page_v1, "a"),
            None,
        )
        assert state["skipped"] is True
        assert "baseline" in state["skip_reason"].lower()

    def test_missing_snapshot_is_handled(self):
        state = run_pipeline({"id": 1, "name": "X"}, {"id": 1, "url": "https://x.com"}, {}, None)
        assert state["skipped"] is True

    def test_llm_can_be_disabled(self, pricing_page_v1, pricing_page_v2):
        state = run_pipeline(
            {"id": 1, "name": "NovaStack"},
            {"id": 1, "url": "https://x.com/pricing"},
            _snapshot(pricing_page_v2, "b"),
            _snapshot(pricing_page_v1, "a"),
            llm_enabled=False,
        )
        assert state["analyses"] == []
        # The deterministic funnel is still measured.
        assert state["stats"]["raw_changes"] > 0


class TestJSONExtraction:
    def test_plain_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_with_leading_prose(self):
        assert extract_json('Sure! Here it is:\n{"a": 1}') == {"a": 1}

    def test_trailing_commas(self):
        assert extract_json('Here: {"a": 1, "b": 2,}') == {"a": 1, "b": 2}

    def test_nested_braces(self):
        assert extract_json('{"a": {"b": {"c": 1}}}')["a"]["b"]["c"] == 1

    def test_braces_inside_strings(self):
        assert extract_json('{"a": "not } a brace"}')["a"] == "not } a brace"

    def test_list_response_takes_first_object(self):
        assert extract_json('[{"a": 1}, {"a": 2}]') == {"a": 1}

    def test_recovers_json_truncated_mid_string(self):
        """Free models hit their token ceiling mid-JSON; keep what they emitted.

        Observed live with a free OpenRouter model. The completed fields are
        good; only the truncated one is dropped.
        """
        truncated = (
            '{"is_meaningful": false, "title": "Homepage copy shifted", '
            '"category": "messaging", "summary": "The main page element chang'
        )
        payload = extract_json(truncated)
        assert payload["title"] == "Homepage copy shifted"
        assert payload["category"] == "messaging"
        assert payload["is_meaningful"] is False
        assert "summary" not in payload, "the truncated field must be dropped, not guessed"

    def test_recovers_json_truncated_between_fields(self):
        payload = extract_json('{"title": "Acme raised prices", "category": "pricing", "relevance_sc')
        assert payload["title"] == "Acme raised prices"
        assert payload["category"] == "pricing"

    def test_repair_closes_nested_structures(self):
        payload = extract_json('{"title": "x", "meta": {"a": 1, "b": [1, 2')
        assert payload["title"] == "x"
        assert payload["meta"]["a"] == 1

    def test_repair_never_invents_a_whole_object(self):
        """Repair closes structure the model started; it does not fabricate."""
        for bad in ["", "   ", "no json here at all", "completely unrelated prose"]:
            with pytest.raises(LLMError):
                extract_json(bad)

    @pytest.mark.parametrize("bad", ["", "   ", "no json here at all", "{unclosed"])
    def test_invalid_payloads_raise(self, bad):
        with pytest.raises(LLMError):
            extract_json(bad)


class TestStructuredValidation:
    def test_rejects_out_of_range_score(self):
        assert ChangeAnalysis(title="Test title", relevance_score=150).relevance_score == 100.0

    def test_coerces_zero_to_one_scale(self):
        """Models routinely answer 0-1 when asked for 0-100."""
        assert ChangeAnalysis(title="Test title", relevance_score=0.9).relevance_score == 90.0

    def test_coerces_percentage_strings(self):
        assert ChangeAnalysis(title="Test title", relevance_score="91%").relevance_score == 91.0

    def test_coerces_word_scores(self):
        assert ChangeAnalysis(title="Test title", relevance_score="high").relevance_score == 78.0

    def test_coerces_confidence_percentage(self):
        assert ChangeAnalysis(title="Test title", confidence=96).confidence == 0.96

    def test_maps_unknown_category_to_other(self):
        assert ChangeAnalysis(title="Test title", category="banana").category == "other"

    def test_maps_category_aliases(self):
        assert ChangeAnalysis(title="Test title", category="Price").category == "pricing"
        assert ChangeAnalysis(title="Test title", category="partnership").category == "integrations"

    def test_flattens_list_fields(self):
        analysis = ChangeAnalysis(title="Test title", summary=["one", "two"])
        assert analysis.summary == "one two"

    def test_rejects_missing_title(self):
        with pytest.raises(ValidationError):
            ChangeAnalysis()

    def test_digest_narrative_tolerates_bad_highlights(self):
        narrative = DigestNarrative(headline="x", highlights="not a list")
        assert narrative.highlights == []


class TestHeuristicProvider:
    def test_is_always_available(self):
        assert HeuristicProvider().is_available()

    def test_produces_valid_analysis(self):
        payload = HeuristicProvider().complete_json(
            system="",
            user="",
            context={
                "competitor_name": "NovaStack",
                "category": "pricing",
                "before": "Rs 999/month",
                "after": "Rs 1499/month",
                "location": "pricing",
                "signals": {"price_direction": 1.0},
                "deterministic_score": 91.0,
                "classifier_confidence": 0.95,
                "evidence": ["Price increased from 999 to 1499"],
            },
        )
        analysis = ChangeAnalysis.model_validate(payload)
        assert "increased pricing" in analysis.title
        assert analysis.category == "pricing"
        assert analysis.relevance_score == 91.0

    def test_only_uses_supplied_facts(self):
        """The offline provider must never invent numbers."""
        payload = HeuristicProvider().complete_json(
            system="", user="", context={"competitor_name": "X", "category": "other",
                                          "before": "alpha", "after": "beta", "location": "body"}
        )
        blob = json.dumps(payload)
        assert "alpha" in blob and "beta" in blob
        assert "999" not in blob

    def test_digest_narrative(self):
        payload = HeuristicProvider().complete_json(
            system="",
            user="",
            context={
                "task": "digest",
                "items": [{"competitor": "A", "category": "pricing", "title": "t", "summary": "s"}],
                "stats": {"raw_changes": 100, "noise_changes": 80, "meaningful_changes": 20,
                          "high_impact_changes": 5, "noise_reduction": 80.0},
            },
        )
        narrative = DigestNarrative.model_validate(payload)
        assert narrative.highlights
        assert "80" in narrative.outlook


class TestProviderFallback:
    def teardown_method(self):
        reset_provider()

    def test_auto_falls_back_without_api_key(self, monkeypatch):
        from app.llm import factory

        monkeypatch.setattr(factory.settings, "openrouter_api_key", None)
        monkeypatch.setattr(factory.settings, "openai_api_key", None)
        monkeypatch.setattr(factory.settings, "llm_provider", "auto")
        assert build_provider().name == "deterministic"

    def test_openrouter_without_key_falls_back(self, monkeypatch):
        """Configuring OpenRouter without a key must not fake an LLM."""
        from app.llm import factory

        monkeypatch.setattr(factory.settings, "openrouter_api_key", None)
        monkeypatch.setattr(factory.settings, "llm_provider", "openrouter")
        assert build_provider().name == "deterministic"

    def test_openrouter_selected_when_key_present(self, monkeypatch):
        from app.llm import factory

        monkeypatch.setattr(factory.settings, "openrouter_api_key", "test-key-not-real")
        monkeypatch.setattr(factory.settings, "llm_provider", "openrouter")
        provider = build_provider()
        assert provider.name == "openrouter"

    def test_unknown_provider_falls_back(self):
        assert build_provider("nonsense-provider").name == "deterministic"

    def test_analyzer_recovers_from_a_broken_provider(self):
        """A provider returning garbage must not fail the scan."""
        from app.diff.types import DetectedChange
        from app.intelligence.analyzer import analyse_change

        class BrokenProvider(LLMProvider):
            name = "broken"
            model = "broken"

            def is_available(self) -> bool:
                return True

            def complete(self, *, system, user, max_tokens=900, context=None) -> LLMResponse:
                return LLMResponse(text="this is not json", provider="broken", model="broken")

        change = DetectedChange(
            before="Rs 999/month", after="Rs 1499/month", category="pricing",
            relevance_score=91.0, classifier_confidence=0.9, magnitude=0.5,
        )
        result = analyse_change(change, "NovaStack", provider=BrokenProvider())
        assert isinstance(result.analysis, ChangeAnalysis)
        # Malformed JSON must be recorded as a failure, not silently passed off
        # as an AI result.
        assert result.llm_status == "failed"
        assert result.analysed_by == "deterministic"
        assert not result.used_llm

    def test_analyzer_recovers_from_a_raising_provider(self):
        from app.diff.types import DetectedChange
        from app.intelligence.analyzer import analyse_change

        class ExplodingProvider(LLMProvider):
            name = "exploding"
            model = "exploding"

            def is_available(self) -> bool:
                return True

            def complete(self, *, system, user, max_tokens=900, context=None) -> LLMResponse:
                raise RuntimeError("API is on fire")

        change = DetectedChange(before="a", after="b", category="other", relevance_score=40.0)
        result = analyse_change(change, "X", provider=ExplodingProvider())
        assert isinstance(result.analysis, ChangeAnalysis)
        assert result.llm_status == "failed"
        assert result.llm_error

    def test_llm_cannot_override_the_deterministic_score(self):
        """The model may nudge the score, never dictate it."""
        from app.diff.types import DetectedChange
        from app.intelligence.analyzer import analyse_change

        class InflatingProvider(LLMProvider):
            name = "inflating"
            model = "inflating"

            def is_available(self) -> bool:
                return True

            def complete(self, *, system, user, max_tokens=900, context=None) -> LLMResponse:
                return LLMResponse(
                    text=json.dumps(
                        {"title": "Everything is critical", "relevance_score": 100, "confidence": 1.0}
                    ),
                    provider="inflating",
                    model="inflating",
                )

        change = DetectedChange(before="a", after="b", category="other", relevance_score=20.0)
        result = analyse_change(change, "X", provider=InflatingProvider())
        assert result.llm_status == "ok"
        assert result.analysis.relevance_score <= 32.0


class TestScanService:
    def test_scan_stores_snapshots_changes_and_intelligence(
        self, session, competitor, pricing_page_v1, pricing_page_v2
    ):
        from app.models.entities import Change, Intelligence, Snapshot
        from app.services.scan import scan_tracked_url

        tracked = competitor.tracked_urls[0]

        baseline = scan_tracked_url(
            session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v1)
        )
        assert baseline.status == "baseline"

        updated = scan_tracked_url(
            session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v2)
        )
        assert updated.status == "changed"
        assert updated.stats.raw_changes > 0

        assert session.query(Snapshot).count() == 2
        assert session.query(Change).count() == updated.stats.raw_changes
        assert session.query(Intelligence).count() > 0

    def test_noise_rows_are_persisted_for_auditability(
        self, session, competitor, pricing_page_v1, pricing_page_v2
    ):
        from app.models.entities import Change
        from app.services.scan import scan_tracked_url

        tracked = competitor.tracked_urls[0]
        scan_tracked_url(session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v1))
        scan_tracked_url(session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v2))

        noise = session.query(Change).filter(Change.is_noise.is_(True)).all()
        assert noise, "discarded changes must be stored as evidence"
        assert all(row.noise_reason for row in noise)

    def test_identical_content_is_not_duplicated(self, session, competitor, pricing_page_v1):
        from app.models.entities import Snapshot
        from app.services.scan import scan_tracked_url

        tracked = competitor.tracked_urls[0]
        scan_tracked_url(session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v1))
        second = scan_tracked_url(
            session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v1)
        )
        assert second.status == "unchanged"
        assert session.query(Snapshot).count() == 1

    def test_failed_fetch_is_recorded_not_raised(self, session, competitor):
        from app.scrapers.fetcher import FetchResult
        from app.services.scan import scan_tracked_url

        tracked = competitor.tracked_urls[0]
        failure = FetchResult(url=tracked.url, ok=False, error="HTTP 500", error_kind="http_error")
        outcome = scan_tracked_url(session, competitor, tracked, fetch_result=failure)

        assert outcome.status == "failed"
        session.refresh(tracked)
        assert tracked.last_status == "http_error"
        assert "HTTP 500" in tracked.last_error

    def test_severity_matches_score(self, session, competitor, pricing_page_v1, pricing_page_v2):
        from app.models.entities import Change
        from app.services.scan import scan_tracked_url

        tracked = competitor.tracked_urls[0]
        scan_tracked_url(session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v1))
        scan_tracked_url(session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v2))

        for change in session.query(Change).all():
            assert change.severity == Severity.from_score(change.relevance_score).value
