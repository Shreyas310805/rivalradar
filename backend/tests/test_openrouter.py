"""Tests for the OpenRouter provider and LLM cost control.

No test here makes a real network request; every OpenRouter response is mocked.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.diff.types import DetectedChange
from app.intelligence.analyzer import (
    STATUS_BUDGET,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_RATE_LIMITED,
    STATUS_SKIPPED,
    analyse_change,
    analyse_changes,
)
from app.llm.base import LLMError
from app.llm.factory import build_provider, describe_analyst, reset_provider
from app.llm.openrouter_provider import (
    OpenRouterEmptyCompletion,
    OpenRouterLLMService,
    OpenRouterRateLimited,
    OpenRouterUnavailable,
)


def _completion(payload: dict, *, model: str = "openrouter/free") -> dict:
    """Shape of a successful OpenRouter chat completion."""
    return {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}],
        "usage": {"total_tokens": 123},
    }


ANALYSIS = {
    "is_meaningful": True,
    "title": "Pro pricing increased",
    "category": "pricing",
    "summary": "Pro went from Rs 999 to Rs 1499 per month.",
    "before": "Rs 999/month",
    "after": "Rs 1499/month",
    "business_impact": "Signals a move upmarket.",
    "relevance_score": 87,
    "confidence": 0.91,
}


class _MockPost:
    """Callable that returns queued responses in order."""

    def __init__(self, *responses: httpx.Response) -> None:
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        if not self._responses:
            raise AssertionError("unexpected extra request")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _patch_post(monkeypatch, *responses):
    """Patch httpx.Client.post with a queue of responses."""
    mock = _MockPost(*responses)
    monkeypatch.setattr(httpx.Client, "post", lambda self, *a, **k: mock(*a, **k))
    return mock


def _response(status: int, json_body: dict | None = None, headers: dict | None = None):
    return httpx.Response(
        status,
        json=json_body if json_body is not None else {},
        headers=headers or {},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )


class TestConfiguration:
    def test_defaults_to_free_model(self):
        service = OpenRouterLLMService(api_key="k")
        assert service.model == "openrouter/free"
        assert service.base_url == "https://openrouter.ai/api/v1"

    def test_unavailable_without_key(self):
        assert not OpenRouterLLMService(api_key=None).is_available()

    def test_available_with_key(self):
        assert OpenRouterLLMService(api_key="test-key").is_available()

    def test_blank_key_is_not_available(self):
        assert not OpenRouterLLMService(api_key="   ").is_available()

    def test_calling_without_key_raises_rather_than_faking(self):
        with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
            OpenRouterLLMService(api_key=None).complete(system="s", user="u")

    def test_headers_carry_auth_and_attribution(self):
        headers = OpenRouterLLMService(api_key="secret-key")._headers()
        assert headers["Authorization"] == "Bearer secret-key"
        assert headers["X-Title"] == "RivalRadar"


class TestSuccessfulCompletion:
    def test_parses_a_completion(self, monkeypatch):
        _patch_post(monkeypatch, _response(200, _completion(ANALYSIS)))
        result = OpenRouterLLMService(api_key="k").complete(system="s", user="u")
        assert result.provider == "openrouter"
        assert result.tokens_used == 123
        assert json.loads(result.text)["category"] == "pricing"

    def test_complete_json_validates(self, monkeypatch):
        _patch_post(monkeypatch, _response(200, _completion(ANALYSIS)))
        payload = OpenRouterLLMService(api_key="k").complete_json(system="s", user="u")
        assert payload["relevance_score"] == 87

    def test_handles_content_parts(self, monkeypatch):
        """Some providers return a list of content parts rather than a string."""
        body = {
            "model": "openrouter/free",
            "choices": [
                {"message": {"content": [{"type": "text", "text": json.dumps(ANALYSIS)}]}}
            ],
            "usage": {},
        }
        _patch_post(monkeypatch, _response(200, body))
        result = OpenRouterLLMService(api_key="k").complete(system="s", user="u")
        assert "pricing" in result.text


class TestFailureHandling:
    def test_rate_limit_retries_then_raises(self, monkeypatch):
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        mock = _patch_post(
            monkeypatch,
            _response(429, {"error": {"message": "rate limited"}}, {"retry-after": "1"}),
            _response(429, {"error": {"message": "rate limited"}}, {"retry-after": "1"}),
            _response(429, {"error": {"message": "rate limited"}}, {"retry-after": "1"}),
        )
        with pytest.raises(OpenRouterRateLimited):
            OpenRouterLLMService(api_key="k", max_retries=2).complete(system="s", user="u")
        assert mock.calls == 3

    def test_rate_limit_recovers_on_retry(self, monkeypatch):
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        _patch_post(
            monkeypatch,
            _response(429, {"error": {"message": "slow down"}}, {"retry-after": "1"}),
            _response(200, _completion(ANALYSIS)),
        )
        result = OpenRouterLLMService(api_key="k", max_retries=2).complete(system="s", user="u")
        assert json.loads(result.text)["title"] == "Pro pricing increased"

    @pytest.mark.parametrize("status", [401, 403])
    def test_bad_key_fails_immediately(self, monkeypatch, status):
        mock = _patch_post(monkeypatch, _response(status, {"error": {"message": "no"}}))
        with pytest.raises(LLMError, match="API key"):
            OpenRouterLLMService(api_key="bad", max_retries=2).complete(system="s", user="u")
        assert mock.calls == 1, "auth failures must not be retried"

    def test_unknown_model_names_the_setting(self, monkeypatch):
        _patch_post(
            monkeypatch,
            _response(404, {"error": {"message": "No endpoints found for model"}}),
        )
        with pytest.raises(OpenRouterUnavailable, match="OPENROUTER_MODEL"):
            OpenRouterLLMService(api_key="k").complete(system="s", user="u")

    def test_timeout_is_wrapped(self, monkeypatch):
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        _patch_post(
            monkeypatch,
            httpx.ConnectTimeout("too slow"),
            httpx.ConnectTimeout("too slow"),
        )
        with pytest.raises(OpenRouterUnavailable, match="timed out"):
            OpenRouterLLMService(api_key="k", max_retries=1).complete(system="s", user="u")

    def test_200_with_error_body_is_an_error(self, monkeypatch):
        """OpenRouter can return 200 with an error payload when a provider fails."""
        _patch_post(monkeypatch, _response(200, {"error": {"message": "upstream died"}}))
        with pytest.raises(OpenRouterUnavailable, match="upstream died"):
            OpenRouterLLMService(api_key="k").complete(system="s", user="u")

    def test_empty_completion_is_an_error(self, monkeypatch):
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        _patch_post(
            monkeypatch,
            _response(200, {"choices": [{"message": {"content": "  "}}], "usage": {}}),
        )
        with pytest.raises(OpenRouterEmptyCompletion, match="no content"):
            OpenRouterLLMService(api_key="k", max_retries=0).complete(system="s", user="u")

    def test_empty_completion_is_retried(self, monkeypatch):
        """With a routing model, a retry lands on a different backend."""
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        mock = _patch_post(
            monkeypatch,
            # First attempt routes to a model that returns nothing usable.
            _response(
                200,
                {
                    "model": "nvidia/nemotron-3.5-content-safety:free",
                    "choices": [{"message": {"content": None}, "finish_reason": "length"}],
                    "usage": {},
                },
            ),
            # Retry re-routes to a capable model.
            _response(200, _completion(ANALYSIS)),
        )
        result = OpenRouterLLMService(api_key="k", max_retries=2).complete(
            system="s", user="u"
        )
        assert mock.calls == 2
        assert json.loads(result.text)["category"] == "pricing"

    def test_json_is_salvaged_from_the_reasoning_field(self, monkeypatch):
        """Reasoning models sometimes leave `content` empty and answer in `reasoning`."""
        body = {
            "model": "some/reasoning-model:free",
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning": f"Let me think... the answer is {json.dumps(ANALYSIS)}",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 40},
        }
        _patch_post(monkeypatch, _response(200, body))
        payload = OpenRouterLLMService(api_key="k").complete_json(system="s", user="u")
        assert payload["category"] == "pricing"
        assert payload["relevance_score"] == 87

    def test_length_truncation_points_at_the_token_budget(self, monkeypatch):
        """A model that spends its budget on reasoning must say so actionably.

        Observed live: a free model emitted a long hidden reasoning block,
        hit max_tokens, and returned empty content. The message has to name
        the setting an operator can actually change.
        """
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        _patch_post(
            monkeypatch,
            _response(
                200,
                {
                    "model": "deepseek/deepseek-v4-flash-0731:free",
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {},
                },
            ),
        )
        with pytest.raises(OpenRouterEmptyCompletion) as exc:
            OpenRouterLLMService(api_key="k", max_retries=0).complete(system="s", user="u")
        assert "LLM_MAX_TOKENS" in str(exc.value)

    def test_analyzer_requests_the_configured_token_budget(self, monkeypatch):
        """The analyzer must use LLM_MAX_TOKENS, not the base default."""
        from app.config.settings import settings

        captured: dict = {}

        class RecordingProvider(OpenRouterLLMService):
            def complete(self, *, system, user, max_tokens=900, context=None):
                captured["max_tokens"] = max_tokens
                return LLMResponseStub(json.dumps(ANALYSIS))

        class LLMResponseStub:
            def __init__(self, text):
                self.text = text
                self.provider = "openrouter"
                self.model = "test"
                self.tokens_used = 0

            def as_json(self):
                return json.loads(self.text)

        change = DetectedChange(
            before="Rs 999/month", after="Rs 1499/month", category="pricing",
            relevance_score=90.0, classifier_confidence=0.9, magnitude=0.5,
        )
        analyse_change(change, "Acme", provider=RecordingProvider(api_key="k"))
        assert captured["max_tokens"] == settings.llm_max_tokens
        assert captured["max_tokens"] >= 2000, "reasoning models need headroom"

    def test_error_message_names_the_model(self, monkeypatch):
        """An operator must be able to tell which backend misbehaved."""
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        _patch_post(
            monkeypatch,
            _response(
                200,
                {
                    "model": "nvidia/nemotron-3.5-content-safety:free",
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {},
                },
            ),
        )
        with pytest.raises(OpenRouterEmptyCompletion) as exc:
            OpenRouterLLMService(
                api_key="k", model="openrouter/free", max_retries=0
            ).complete(system="s", user="u")
        assert "openrouter/free" in str(exc.value)


class TestAnalyzerStatus:
    """A scan must survive every LLM failure and record what happened."""

    def _change(self, score: float = 90.0) -> DetectedChange:
        return DetectedChange(
            before="Rs 999/month",
            after="Rs 1499/month",
            category="pricing",
            relevance_score=score,
            classifier_confidence=0.9,
            magnitude=0.5,
        )

    def test_success_is_recorded_as_ok(self, monkeypatch):
        _patch_post(monkeypatch, _response(200, _completion(ANALYSIS)))
        result = analyse_change(
            self._change(), "Acme", provider=OpenRouterLLMService(api_key="k")
        )
        assert result.llm_status == STATUS_OK
        assert result.used_llm
        assert result.analysed_by == "openrouter"

    def test_rate_limit_degrades_without_crashing(self, monkeypatch):
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        _patch_post(
            monkeypatch,
            _response(429, {"error": {"message": "limit"}}),
            _response(429, {"error": {"message": "limit"}}),
            _response(429, {"error": {"message": "limit"}}),
        )
        result = analyse_change(
            self._change(), "Acme", provider=OpenRouterLLMService(api_key="k", max_retries=2)
        )
        assert result.llm_status == STATUS_RATE_LIMITED
        assert not result.used_llm
        # The detection survives even though the writing is deterministic.
        assert result.analysis.title
        assert result.analysis.relevance_score > 0

    def test_deterministic_provider_is_marked_skipped_not_ok(self):
        """Never claim an LLM ran when none is configured."""
        from app.llm.heuristic_provider import HeuristicProvider

        result = analyse_change(self._change(), "Acme", provider=HeuristicProvider())
        assert result.llm_status == STATUS_SKIPPED
        assert not result.used_llm
        assert result.analysed_by == "deterministic"


class TestCostControl:
    """Free models are rate limited; the pipeline must be frugal."""

    def _changes(self, count: int, score: float) -> list[DetectedChange]:
        return [
            DetectedChange(
                before=f"before {i}",
                after=f"after {i}",
                category="pricing",
                relevance_score=score,
                classifier_confidence=0.8,
                magnitude=0.5,
            )
            for i in range(count)
        ]

    def test_no_changes_makes_no_calls(self, monkeypatch):
        mock = _patch_post(monkeypatch)
        assert analyse_changes([], "Acme", provider=OpenRouterLLMService(api_key="k")) == []
        assert mock.calls == 0

    def test_low_relevance_never_reaches_the_model(self, monkeypatch):
        mock = _patch_post(monkeypatch)
        results = analyse_changes(
            self._changes(5, score=10.0),
            "Acme",
            provider=OpenRouterLLMService(api_key="k"),
            min_relevance=40.0,
        )
        assert mock.calls == 0, "sub-threshold changes must not cost a request"
        assert all(r.llm_status == STATUS_SKIPPED for r in results)

    def test_call_budget_is_enforced(self, monkeypatch):
        _patch_post(monkeypatch, *[_response(200, _completion(ANALYSIS)) for _ in range(10)])
        results = analyse_changes(
            self._changes(6, score=90.0),
            "Acme",
            provider=OpenRouterLLMService(api_key="k"),
            limit=2,
            min_relevance=40.0,
        )
        assert sum(1 for r in results if r.used_llm) == 2
        assert sum(1 for r in results if r.llm_status == STATUS_BUDGET) == 4
        # Every change is still returned; only the writing differs.
        assert len(results) == 6

    def test_stops_calling_after_a_failure(self, monkeypatch):
        """One hard failure must not become six."""
        monkeypatch.setattr("app.llm.openrouter_provider.time.sleep", lambda _s: None)
        mock = _patch_post(
            monkeypatch,
            _response(500, {"error": {"message": "boom"}}),
            _response(500, {"error": {"message": "boom"}}),
            _response(500, {"error": {"message": "boom"}}),
        )
        results = analyse_changes(
            self._changes(5, score=90.0),
            "Acme",
            provider=OpenRouterLLMService(api_key="k", max_retries=2),
            limit=8,
            min_relevance=40.0,
        )
        assert mock.calls == 3, "should give up after the first change fails"
        assert results[0].llm_status == STATUS_FAILED
        assert all(r.llm_status == STATUS_SKIPPED for r in results[1:])


class TestAnalystLabel:
    def teardown_method(self):
        reset_provider()

    def test_reports_deterministic_without_a_key(self, monkeypatch):
        from app.llm import factory

        monkeypatch.setattr(factory.settings, "openrouter_api_key", None)
        monkeypatch.setattr(factory.settings, "openai_api_key", None)
        monkeypatch.setattr(factory.settings, "llm_provider", "openrouter")
        reset_provider()
        analyst = describe_analyst()
        assert analyst["is_llm"] is False
        assert analyst["provider"] == "deterministic"

    def test_reports_openrouter_with_a_key(self, monkeypatch):
        from app.llm import factory

        monkeypatch.setattr(factory.settings, "openrouter_api_key", "test-key")
        monkeypatch.setattr(factory.settings, "llm_provider", "openrouter")
        reset_provider()
        analyst = describe_analyst()
        assert analyst["is_llm"] is True
        assert analyst["label"] == "OpenRouter"

    def test_provider_registry_knows_openrouter(self, monkeypatch):
        from app.llm import factory

        monkeypatch.setattr(factory.settings, "openrouter_api_key", "test-key")
        assert build_provider("openrouter").name == "openrouter"
