"""OpenAI-backed LLM provider."""

from __future__ import annotations

import time
from typing import Any

from app.config.logging import get_logger
from app.config.settings import settings
from app.llm.base import LLMError, LLMProvider, LLMResponse

logger = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    """Calls the OpenAI Chat Completions API with JSON-mode output.

    Retries on transient failures with exponential backoff.  Any unrecoverable
    error raises :class:`LLMError` so the caller can fall back rather than
    letting a scan fail outright.
    """

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        base_url: str | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self.base_url = base_url or settings.openai_base_url
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.timeout = settings.llm_timeout_seconds if timeout is None else timeout
        self.max_retries = settings.llm_max_retries if max_retries is None else max_retries
        self._client = None

    def _get_client(self) -> Any:
        """Lazily construct the SDK client so import never requires a key.

        Returns ``Any`` because the OpenAI client type is imported lazily —
        annotating it eagerly would make the module require the SDK at import.
        """
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise LLMError("openai package is not installed") from exc

        kwargs: dict[str, object] = {"api_key": self.api_key, "timeout": self.timeout}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def is_available(self) -> bool:
        """True when an API key is present (the call itself may still fail)."""
        return bool(self.api_key)

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 900,
        context: dict | None = None,
    ) -> LLMResponse:
        """Request a JSON-mode completion, retrying transient errors.

        ``context`` is unused here: the facts it holds are already rendered
        into ``user`` by the analyzer.
        """
        del context
        client = self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=self.temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                choice = completion.choices[0].message.content or ""
                usage = getattr(completion, "usage", None)
                return LLMResponse(
                    text=choice,
                    provider=self.name,
                    model=self.model,
                    tokens_used=getattr(usage, "total_tokens", 0) or 0,
                )
            except Exception as exc:  # noqa: BLE001 - provider errors vary widely
                last_error = exc
                if attempt >= self.max_retries:
                    break
                backoff = 1.5 * (2**attempt)
                logger.warning(
                    "OpenAI call failed (attempt %d/%d): %s; retrying in %.1fs",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                    backoff,
                )
                time.sleep(backoff)

        raise LLMError(f"OpenAI request failed after {self.max_retries + 1} attempts: {last_error}")
