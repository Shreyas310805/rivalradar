"""Credentials must never reach storage, an API response or a log line.

Regression tests for a real incident: an OpenRouter key with a trailing
newline made httpx reject the request with ``Illegal header value b'Bearer
<key>\\n'``, and that message was stored as the analysis error and served by
the public API.

Fake keys are assembled at runtime so no key-shaped literal is committed.
"""

from __future__ import annotations

import logging
import sys

import pytest

from app.config.logging import RedactingFormatter
from app.redaction import REDACTED, redact_secrets, summarise_error

FAKE_KEY = "sk-" + "or-v1-" + "0123456789abcdef" * 4


def _leaky_message(key: str = FAKE_KEY) -> str:
    """What httpx/h11 actually said when the key ended in a newline."""
    return f"Illegal header value b'Bearer {key}\\n'"


class TestRedactSecrets:
    def test_the_incident_message(self):
        cleaned = redact_secrets(_leaky_message())
        assert FAKE_KEY not in cleaned
        assert "sk-or" not in cleaned
        assert "Illegal header value" in cleaned, "the diagnosis must survive"

    def test_bare_key(self):
        assert redact_secrets(f"key was {FAKE_KEY}.") == f"key was {REDACTED}."

    @pytest.mark.parametrize(
        "text",
        [
            "Authorization: Bearer abc.def-ghi",
            "{'Authorization': 'Bearer abc.def-ghi'}",
            '{"authorization": "Bearer abc.def-ghi"}',
            "headers={'X-API-Key': 'abc.def-ghi'}",
            "api_key=abc.def-ghi",
        ],
    )
    def test_header_values_and_assignments(self, text):
        cleaned = redact_secrets(text)
        assert "abc.def-ghi" not in cleaned
        assert REDACTED in cleaned

    def test_bearer_token_that_is_not_an_sk_key(self):
        cleaned = redact_secrets("sent Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert "eyJhbGci" not in cleaned

    def test_url_credentials(self):
        cleaned = redact_secrets("could not connect to postgresql://user:hunter2@db.invalid/x")
        assert "hunter2" not in cleaned
        assert "db.invalid" in cleaned

    def test_configured_key_is_caught_even_without_a_known_shape(self, monkeypatch):
        from app.config.settings import settings

        custom = "custom" + "-provider-secret-" + "9" * 12
        monkeypatch.setattr(settings, "openrouter_api_key", custom)
        assert custom not in redact_secrets(f"failed with {custom} in the header")

    @pytest.mark.parametrize(
        "text",
        [
            "OpenRouter unavailable (HTTP 503)",
            "network error: [Errno 11001] getaddrinfo failed",
            "content too short (<12 chars)",
        ],
    )
    def test_ordinary_text_is_untouched(self, text):
        assert redact_secrets(text) == text

    @pytest.mark.parametrize("value", [None, ""])
    def test_empty_values_pass_through(self, value):
        assert redact_secrets(value) == value


class TestSummariseError:
    def test_drops_the_message(self):
        summary = summarise_error(ValueError(_leaky_message()))
        assert summary == "ValueError"

    def test_keeps_status_and_cause_type(self):
        from app.llm.base import LLMError

        try:
            try:
                raise ConnectionError(_leaky_message())
            except ConnectionError as inner:
                raise LLMError(_leaky_message(), status_code=502) from inner
        except LLMError as exc:
            summary = summarise_error(exc)

        assert summary == "LLMError (HTTP 502, cause: ConnectionError)"
        assert "sk-or" not in summary


class TestRedactingFormatter:
    def _record(self, msg: str, *args: object, exc_info=None) -> logging.LogRecord:
        return logging.LogRecord("t", logging.ERROR, __file__, 1, msg, args, exc_info)

    def test_message_and_arguments(self):
        formatter = RedactingFormatter(logging.Formatter("%(message)s"))
        output = formatter.format(self._record("request failed: %s", _leaky_message()))
        assert "sk-or" not in output
        assert "request failed" in output

    def test_traceback(self):
        """A logged traceback repeats the exception message on its last line."""
        formatter = RedactingFormatter(logging.Formatter("%(message)s"))
        try:
            raise RuntimeError(_leaky_message())
        except RuntimeError:
            record = self._record("scan failed", exc_info=sys.exc_info())
        output = formatter.format(record)
        assert "Traceback" in output
        assert "sk-or" not in output
