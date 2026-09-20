"""LLM provider selection.

``LLM_PROVIDER`` accepts:

``openrouter`` (default)
    OpenRouter's OpenAI-compatible API. Free-tier friendly. Requires
    ``OPENROUTER_API_KEY``; without it the pipeline still runs, but analysis
    is produced deterministically and is labelled as such.
``deterministic``
    No network at all. Rule-based analysis derived from the signals the
    classifier already extracted.
``openai``
    Optional, paid. Not required by anything.
``auto``
    OpenRouter when a key is present, otherwise deterministic.

Adding a provider means writing one class and adding one entry to
``_REGISTRY`` — nothing else in the codebase changes.
"""

from __future__ import annotations

from collections.abc import Callable

from app.config.logging import get_logger
from app.config.settings import settings
from app.llm.base import LLMProvider
from app.llm.heuristic_provider import HeuristicProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.openrouter_provider import OpenRouterLLMService

logger = get_logger(__name__)

_REGISTRY: dict[str, Callable[[], LLMProvider]] = {
    "openrouter": OpenRouterLLMService,
    "deterministic": HeuristicProvider,
    "openai": OpenAIProvider,
    # Backwards-compatible alias for the old name.
    "heuristic": HeuristicProvider,
}

_cached_provider: LLMProvider | None = None


def build_provider(name: str | None = None) -> LLMProvider:
    """Construct a provider by name, honouring ``auto`` resolution.

    Never raises: an unusable configuration degrades to the deterministic
    provider so a scan can always complete.
    """
    requested = (name or settings.llm_provider or "openrouter").strip().casefold()

    if requested == "auto":
        requested = "openrouter" if settings.openrouter_api_key else "deterministic"

    factory = _REGISTRY.get(requested)
    if factory is None:
        logger.warning(
            "Unknown LLM_PROVIDER %r; falling back to deterministic analysis", requested
        )
        return HeuristicProvider()

    provider = factory()

    if not provider.is_available():
        if requested == "openrouter":
            logger.warning(
                "LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is not set. "
                "Running deterministic analysis; results will be labelled "
                "'deterministic', not AI-generated."
            )
        else:
            logger.warning(
                "Provider %r is configured but unavailable; using deterministic analysis",
                requested,
            )
        return HeuristicProvider()

    logger.info("LLM provider: %s (model=%s)", provider.name, provider.model)
    return provider


def get_provider(refresh: bool = False) -> LLMProvider:
    """Return the process-wide provider singleton."""
    global _cached_provider
    if _cached_provider is None or refresh:
        _cached_provider = build_provider()
    return _cached_provider


def reset_provider() -> None:
    """Drop the cached provider (used by tests and after config changes)."""
    global _cached_provider
    _cached_provider = None


def describe_analyst() -> dict[str, str | bool]:
    """Describe the active analyst for the UI.

    Reports what will *actually* be used, so the dashboard never claims an LLM
    analysed something when no key is configured.
    """
    provider = get_provider()
    is_llm = provider.name not in {"deterministic", "heuristic"}
    return {
        "provider": provider.name,
        "model": provider.model,
        "is_llm": is_llm,
        "label": "OpenRouter" if provider.name == "openrouter" else provider.name.title(),
        "configured_provider": settings.llm_provider,
    }
