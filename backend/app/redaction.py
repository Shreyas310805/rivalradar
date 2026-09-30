"""Keeping credentials out of everything the app stores, returns or logs.

Exception messages are not safe to show. httpx, for one, quotes the offending
header when it rejects a request, so a key with a stray newline produced
``Illegal header value b'Bearer <the key>\\n'`` — and that string, stored as
an analysis error, was served by the public API. Two rules follow:

  * never store or return a raw exception message from an LLM call; store
    :func:`summarise_error` instead (type and status code only);
  * pass any other free text that reaches storage, a response or a log line
    through :func:`redact_secrets` first.
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"

# Order matters: a whole Authorization header is consumed before the bare
# Bearer rule sees it, and both run before the bare key rule.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization / API-key headers or assignments: everything after the separator.
    (
        re.compile(
            r"(?i)\b(authorization|proxy-authorization|x-api-key|api[-_]?key)"
            r"(['\"]?\s*[:=]\s*['\"]?)[^\r\n'\",}]+"
        ),
        r"\1\2" + REDACTED,
    ),
    # Bearer tokens anywhere, including inside a bytes repr such as b'Bearer x\n'.
    (re.compile(r"(?i)\bbearer\s+[^\s'\",}]+"), "Bearer " + REDACTED),
    # OpenRouter and OpenAI style keys: "sk-" followed by the key body.
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), REDACTED),
    # Credentials embedded in a URL: scheme://user:password@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s@/]+@"), r"\1:" + REDACTED + "@"),
)


def _configured_secrets() -> list[str]:
    """The literal secret values this process knows about.

    A key that matches none of the patterns above (a custom provider, a
    rotated format) is still caught by exact match. Imported lazily so this
    module has no import-time dependency on settings.
    """
    try:
        from app.config.settings import settings
    except Exception:  # noqa: BLE001 - redaction must never fail; patterns still apply
        return []

    values = (settings.openrouter_api_key, settings.openai_api_key)
    return [value for value in values if value and len(value) >= 8]


def redact_secrets(text: str | None) -> str | None:
    """Return ``text`` with anything credential-shaped replaced."""
    if not text:
        return text
    for secret in _configured_secrets():
        text = text.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def summarise_error(exc: BaseException) -> str:
    """A short, safe description of an error: its type and HTTP status.

    Deliberately excludes the exception message, which is where library code
    puts request details. The underlying cause's type is kept because it is
    what makes a failure diagnosable — ``OpenRouterUnavailable (cause:
    LocalProtocolError)`` points straight at a malformed header.
    """
    parts = [type(exc).__name__]
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        parts.append(f"HTTP {status}")
    cause = exc.__cause__ or exc.__context__
    if cause is not None and type(cause) is not type(exc):
        parts.append(f"cause: {type(cause).__name__}")
    return parts[0] if len(parts) == 1 else f"{parts[0]} ({', '.join(parts[1:])})"
