"""LLM provider abstraction.

Every provider implements :class:`LLMProvider`.  The rest of the application
only ever sees this interface, so adding Anthropic, Gemini or a local model is
a new file plus one line in the factory — no changes to the pipeline.
"""

from __future__ import annotations

import abc
import json
import re
from dataclasses import dataclass

from app.config.logging import get_logger

logger = get_logger(__name__)


class LLMError(RuntimeError):
    """Raised when a provider cannot produce usable output.

    ``status_code`` carries the HTTP status when there was one, so callers can
    record a failure as type + status without keeping the message text.
    """

    def __init__(self, message: str = "", *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class LLMResponse:
    """A provider response plus the metadata needed for auditing."""

    text: str
    provider: str
    model: str
    tokens_used: int = 0

    def as_json(self) -> dict:
        """Parse the response body as JSON, tolerating common model quirks."""
        return extract_json(self.text)


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response.

    Handles the three failure modes that show up constantly in practice:
    fenced code blocks, leading prose before the object, and trailing commas.
    """
    if not text or not text.strip():
        raise LLMError("empty response")

    candidate = text.strip()

    # 1. Strip markdown fences.
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()

    # 2. Direct parse.
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]
    except json.JSONDecodeError:
        pass

    # 3. Find the outermost balanced object and retry.
    start = candidate.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(candidate)):
            char = candidate[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    blob = candidate[start : index + 1]
                    blob = re.sub(r",\s*([}\]])", r"\1", blob)  # trailing commas
                    try:
                        parsed = json.loads(blob)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break

    # 4. Repair a truncated object.
    #
    # Free models routinely hit their token ceiling mid-JSON, leaving an
    # unterminated string and unclosed braces. The fields already emitted are
    # perfectly good, so close the structure and keep them rather than
    # discarding a usable answer.
    if start >= 0:
        repaired = _repair_truncated_json(candidate[start:])
        if repaired is not None:
            logger.info("Recovered a truncated JSON response from the model")
            return repaired

    raise LLMError(f"no valid JSON object in response: {text[:200]!r}")


def _repair_truncated_json(blob: str) -> dict | None:
    """Best-effort repair of JSON cut off mid-object.

    Closes an unterminated string, drops a trailing incomplete key/value, and
    balances open braces/brackets. Returns ``None`` when the result still does
    not parse — this never invents field *values*, it only closes structure
    the model had already started.
    """
    in_string = False
    escaped = False
    stack: list[str] = []

    for char in blob:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            stack.append(char)
        elif char in "}]" and stack:
            stack.pop()

    candidate = blob
    if in_string:
        # Cut back to the last complete field rather than inventing content.
        last_comma = candidate.rfind(",")
        candidate = candidate[:last_comma] if last_comma > 0 else candidate + '"'

    # Drop a dangling "key": or trailing comma left by the truncation.
    candidate = re.sub(r",\s*\"[^\"]*\"\s*:\s*$", "", candidate.rstrip())
    candidate = re.sub(r",\s*$", "", candidate.rstrip())

    for opener in reversed(stack):
        candidate += "}" if opener == "{" else "]"

    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class LLMProvider(abc.ABC):
    """Base class for all LLM providers."""

    name: str = "base"
    model: str = "unknown"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """True when this provider can actually serve requests right now."""

    @abc.abstractmethod
    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 900,
        context: dict | None = None,
    ) -> LLMResponse:
        """Return a completion for the given system/user prompt pair.

        ``context`` carries the structured facts that were also rendered into
        ``user``.  Network-backed providers ignore it (the prompt already has
        everything); the offline heuristic provider reads it directly instead
        of re-parsing prose.
        """

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 900,
        context: dict | None = None,
    ) -> dict:
        """Return a completion parsed as a JSON object."""
        response = self.complete(
            system=system, user=user, max_tokens=max_tokens, context=context
        )
        return response.as_json()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name} model={self.model}>"
