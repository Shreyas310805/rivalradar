"""OpenRouter LLM provider.

OpenRouter exposes an OpenAI-compatible Chat Completions API at
``https://openrouter.ai/api/v1``, which lets RivalRadar use free-tier models
without any paid account.

Free models are rate limited and occasionally unavailable, so this provider is
built defensively:

* 429 responses honour ``Retry-After`` and back off exponentially,
* 5xx and transport errors retry a bounded number of times,
* a 404/400 naming an unknown model raises immediately (retrying will not
  help) with a message pointing at the model setting,
* every failure raises :class:`LLMError`, which the analyzer turns into a
  recorded ``llm_status='failed'`` rather than a crashed scan.

The API key is read from the environment only. It is never logged, never
returned in an API response, and never reaches the frontend.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.config.logging import get_logger
from app.config.settings import settings
from app.llm.base import LLMError, LLMProvider, LLMResponse

logger = get_logger(__name__)

# Status codes worth retrying: throttling and transient upstream problems.
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class OpenRouterRateLimited(LLMError):
    """Raised when OpenRouter throttles us and retries are exhausted."""


class OpenRouterUnavailable(LLMError):
    """Raised when OpenRouter or the selected model cannot serve the request."""


class OpenRouterEmptyCompletion(OpenRouterUnavailable):
    """The model answered but produced no usable content.

    This is common on the free tier, especially with the ``openrouter/free``
    router, which picks a different model per request and can land on one that
    is unsuitable for the task (a content-safety classifier, say) or that
    exhausts its token budget inside a reasoning block.

    It is *retryable*: a retry re-routes and usually lands somewhere usable.
    """


class OpenRouterLLMService(LLMProvider):
    """Structured-output client for OpenRouter's free models."""

    name = "openrouter"

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
        self.api_key = api_key if api_key is not None else settings.openrouter_api_key
        self.model = model or settings.openrouter_model
        self.base_url = (base_url or settings.openrouter_base_url).rstrip("/")
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.timeout = settings.llm_timeout_seconds if timeout is None else timeout
        self.max_retries = settings.llm_max_retries if max_retries is None else max_retries

    # --- Availability ------------------------------------------------------

    def is_available(self) -> bool:
        """True when an API key is configured.

        This does not prove the key is valid or that the model is reachable —
        only a real request can. Callers must still handle :class:`LLMError`.
        """
        return bool(self.api_key and self.api_key.strip())

    def describe(self) -> dict[str, str]:
        """Non-secret description for the UI's analyst label."""
        return {"provider": self.name, "model": self.model}

    # --- Request plumbing --------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers (both optional).
            "X-Title": settings.openrouter_app_name,
        }
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        return headers

    def _payload(self, system: str, user: str, max_tokens: int) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            # Ask for JSON. Not every free model honours this, which is why the
            # response still goes through tolerant extraction + Pydantic.
            "response_format": {"type": "json_object"},
        }

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        """Seconds to wait before retrying, honouring Retry-After when sent."""
        raw = response.headers.get("retry-after")
        if raw:
            try:
                return max(1.0, min(60.0, float(raw)))
            except ValueError:
                pass
        return min(30.0, 2.0 * (2**attempt))

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 900,
        context: dict | None = None,
    ) -> LLMResponse:
        """Call OpenRouter and return the raw completion text.

        ``context`` carries the same structured facts rendered into ``user``;
        it is unused here and consumed only by the deterministic provider.
        """
        del context

        if not self.is_available():
            raise LLMError(
                "OPENROUTER_API_KEY is not set. Add it to backend/.env to enable AI analysis."
            )

        url = f"{self.base_url}/chat/completions"
        payload = self._payload(system, user, max_tokens)
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, headers=self._headers(), json=payload)
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise OpenRouterUnavailable(
                        f"OpenRouter timed out after {self.max_retries + 1} attempts"
                    ) from exc
                wait = min(30.0, 2.0 * (2**attempt))
                logger.warning("OpenRouter timeout; retrying in %.0fs", wait)
                time.sleep(wait)
                continue
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise OpenRouterUnavailable(f"OpenRouter unreachable: {exc}") from exc
                wait = min(30.0, 2.0 * (2**attempt))
                logger.warning("OpenRouter transport error (%s); retrying in %.0fs", exc, wait)
                time.sleep(wait)
                continue

            # --- Non-retryable client errors --------------------------------
            if response.status_code in (401, 403):
                raise LLMError(
                    "OpenRouter rejected the API key (HTTP "
                    f"{response.status_code}). Check OPENROUTER_API_KEY in backend/.env."
                )
            if response.status_code in (400, 404):
                detail = self._error_detail(response)
                raise OpenRouterUnavailable(
                    f"OpenRouter rejected the request (HTTP {response.status_code}): {detail}. "
                    f"If this names the model, set OPENROUTER_MODEL to a model your account "
                    f"can use (current: {self.model!r})."
                )

            # --- Retryable ---------------------------------------------------
            if response.status_code in _RETRYABLE_STATUS:
                if attempt >= self.max_retries:
                    detail = self._error_detail(response)
                    if response.status_code == 429:
                        raise OpenRouterRateLimited(
                            "OpenRouter rate limit reached on the free tier "
                            f"(HTTP 429): {detail}"
                        )
                    raise OpenRouterUnavailable(
                        f"OpenRouter unavailable (HTTP {response.status_code}): {detail}"
                    )
                wait = self._retry_after(response, attempt)
                logger.warning(
                    "OpenRouter HTTP %d; retrying in %.0fs (attempt %d/%d)",
                    response.status_code,
                    wait,
                    attempt + 1,
                    self.max_retries + 1,
                )
                time.sleep(wait)
                continue

            if response.status_code >= 400:
                raise OpenRouterUnavailable(
                    f"OpenRouter returned HTTP {response.status_code}: "
                    f"{self._error_detail(response)}"
                )

            try:
                return self._to_response(response, payload)
            except OpenRouterEmptyCompletion as exc:
                # Retrying is worthwhile here: with a routing model like
                # ``openrouter/free`` the next attempt lands on a different
                # backend, which is usually a usable one.
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                logger.warning("%s; retrying (a retry re-routes the request)", exc)
                time.sleep(1.5 * (attempt + 1))
                continue

        raise OpenRouterUnavailable(f"OpenRouter request failed: {last_error}")

    # --- Response parsing --------------------------------------------------

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Extract a readable error message without leaking the request body."""
        try:
            body = response.json()
        except ValueError:
            return (response.text or "")[:200] or "no response body"
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            return str(error.get("message") or error)[:300]
        return str(error or body)[:300]

    def _to_response(self, response: httpx.Response, body: dict | None = None) -> LLMResponse:
        """Turn a 200 OK into an :class:`LLMResponse`.

        ``body`` is the request payload, used only to name the model in
        error messages when the response is unusable."""
        body = body or {}
        try:
            parsed = response.json()
        except ValueError as exc:
            raise OpenRouterUnavailable("OpenRouter returned a non-JSON body") from exc

        # OpenRouter can return 200 with an error payload when a provider fails.
        if isinstance(parsed, dict) and parsed.get("error") and not parsed.get("choices"):
            raise OpenRouterUnavailable(
                f"OpenRouter error: {self._error_detail(response)}"
            )

        choices = (parsed or {}).get("choices") or []
        if not choices:
            raise OpenRouterUnavailable("OpenRouter returned no choices")

        choice = choices[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        if isinstance(text, list):
            # Some providers return content parts rather than a plain string.
            text = "".join(
                part.get("text", "") for part in text if isinstance(part, dict)
            )

        # Reasoning models sometimes leave `content` empty and put everything —
        # including the JSON we asked for — in `reasoning`. Salvage it rather
        # than throwing away a usable answer.
        if not str(text).strip():
            reasoning = message.get("reasoning") or ""
            if isinstance(reasoning, str) and "{" in reasoning:
                logger.info("Recovering JSON from the model's reasoning field")
                text = reasoning

        if not str(text).strip():
            model_name = body.get("model") or self.model
            finish = choice.get("finish_reason")
            hint = (
                " - the token budget was spent on hidden reasoning before any"
                " content was produced; raise LLM_MAX_TOKENS"
                if finish == "length"
                else ""
            )
            raise OpenRouterEmptyCompletion(
                f"model {model_name!r} returned no content "
                f"(finish_reason={finish!r}){hint}"
            )

        usage = parsed.get("usage") or {}
        model_used = parsed.get("model") or self.model
        logger.info(
            "OpenRouter completion: model=%s tokens=%s",
            model_used,
            usage.get("total_tokens", "?"),
        )
        return LLMResponse(
            text=str(text),
            provider=self.name,
            model=str(model_used),
            tokens_used=int(usage.get("total_tokens") or 0),
        )

    def ping(self) -> dict[str, Any]:
        """Make one tiny real request to prove the key and model work.

        Used by ``rivalradar llm-check``. Returns a dict describing the
        outcome; never raises.
        """
        if not self.is_available():
            return {"ok": False, "reason": "OPENROUTER_API_KEY is not set"}
        try:
            result = self.complete(
                system='Reply with only this JSON: {"ok": true}',
                user="ping",
                max_tokens=32,
            )
        except LLMError as exc:
            return {"ok": False, "reason": str(exc), "model": self.model}
        try:
            parsed = json.loads(result.text.strip().strip("`"))
        except ValueError:
            parsed = {"raw": result.text[:120]}
        return {
            "ok": True,
            "model": result.model,
            "tokens_used": result.tokens_used,
            "response": parsed,
        }
