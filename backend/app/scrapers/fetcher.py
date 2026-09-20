"""Polite, defensive HTTP fetching.

Guarantees made to the rest of the application:

* a fetch never raises — it returns a :class:`FetchResult` with ``ok=False``,
* every URL (including each redirect hop) is SSRF-validated,
* responses are size-capped and content-type checked,
* transient failures are retried with exponential backoff,
* a configurable delay is applied between requests to the same origin.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.config.logging import get_logger
from app.config.settings import settings
from app.scrapers import robots
from app.scrapers.normalizer import content_hash, extract_title, normalize_html, word_count
from app.scrapers.url_guard import UnresolvableHostError, UnsafeURLError, validate_url

logger = get_logger(__name__)

# Status codes worth retrying (transient server/proxy problems and throttling).
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_ACCEPTABLE_CONTENT_TYPES = ("text/html", "application/xhtml", "text/plain", "application/xml")

# Last request time per origin, for polite spacing.
_last_request_at: dict[str, float] = {}


@dataclass(slots=True)
class FetchResult:
    """Outcome of fetching a single URL."""

    url: str
    ok: bool = False
    status_code: int | None = None
    raw_html: str = ""
    normalized_text: str = ""
    title: str | None = None
    content_hash: str = ""
    word_count: int = 0
    duration_ms: int = 0
    error: str | None = None
    error_kind: str | None = None
    final_url: str | None = None
    renderer: str = "httpx"
    headers: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "ok": self.ok,
            "status_code": self.status_code,
            "normalized_text": self.normalized_text,
            "title": self.title,
            "content_hash": self.content_hash,
            "word_count": self.word_count,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "error_kind": self.error_kind,
            "final_url": self.final_url,
            "renderer": self.renderer,
        }


def _respect_delay(url: str, extra_delay: float | None = None) -> None:
    """Sleep so requests to one origin stay spaced out."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    delay = max(settings.request_delay_seconds, extra_delay or 0.0)
    previous = _last_request_at.get(origin)
    if previous is not None:
        elapsed = time.monotonic() - previous
        if elapsed < delay:
            time.sleep(delay - elapsed)
    _last_request_at[origin] = time.monotonic()


def _default_headers() -> dict[str, str]:
    """Headers that identify the crawler clearly."""
    return {
        "User-Agent": settings.scan_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }


def _build_result(url: str, *, error: str, kind: str, status: int | None = None) -> FetchResult:
    """Shorthand for a failed fetch."""
    return FetchResult(url=url, ok=False, error=error, error_kind=kind, status_code=status)


def fetch_url(
    url: str,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    check_robots: bool = True,
    render_js: bool = False,
    client: httpx.Client | None = None,
) -> FetchResult:
    """Fetch a single URL and return normalised content.

    Never raises.  Inspect ``result.ok`` and ``result.error_kind``.
    """
    timeout = settings.request_timeout_seconds if timeout is None else timeout
    max_retries = settings.request_max_retries if max_retries is None else max_retries

    # 1. Validate before anything leaves the process.
    try:
        safe_url = validate_url(url)
    except UnresolvableHostError as exc:
        logger.info("Host does not resolve for %r: %s", url, exc)
        return _build_result(url, error=str(exc), kind="dns_error")
    except UnsafeURLError as exc:
        logger.warning("Refusing to fetch unsafe URL %r: %s", url, exc)
        return _build_result(url, error=str(exc), kind="unsafe_url")

    # 2. Ask robots.txt.
    crawl_delay: float | None = None
    if check_robots:
        decision = robots.check(safe_url)
        if not decision.allowed:
            logger.info("robots.txt disallows %s", safe_url)
            return _build_result(safe_url, error=decision.reason, kind="robots_disallowed")
        crawl_delay = decision.crawl_delay

    # 3. Optional JavaScript rendering.
    if render_js and settings.playwright_enabled:
        from app.scrapers.playwright_fetcher import fetch_with_playwright

        rendered = fetch_with_playwright(safe_url, timeout=timeout)
        if rendered.ok:
            return rendered
        logger.warning(
            "Playwright render failed for %s (%s); falling back to plain HTTP",
            safe_url,
            rendered.error,
        )

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,  # validated manually, hop by hop
            headers=_default_headers(),
        )

    started = time.monotonic()
    try:
        response = _request_with_retries(
            client,
            safe_url,
            max_retries=max_retries,
            crawl_delay=crawl_delay,
        )
    except UnsafeURLError as exc:
        return _build_result(safe_url, error=str(exc), kind="unsafe_redirect")
    except httpx.TimeoutException as exc:
        return _build_result(safe_url, error=f"request timed out: {exc}", kind="timeout")
    except httpx.TooManyRedirects as exc:
        return _build_result(safe_url, error=str(exc), kind="too_many_redirects")
    except httpx.HTTPError as exc:
        return _build_result(safe_url, error=f"network error: {exc}", kind="network_error")
    except Exception as exc:  # noqa: BLE001 - a scan must survive anything
        logger.error("Unexpected fetch failure for %s", safe_url, exc_info=True)
        return _build_result(safe_url, error=str(exc), kind="unexpected")
    finally:
        if owns_client:
            client.close()

    duration_ms = int((time.monotonic() - started) * 1000)

    if response.status_code >= 400:
        return FetchResult(
            url=safe_url,
            ok=False,
            status_code=response.status_code,
            error=f"HTTP {response.status_code}",
            error_kind="http_error",
            duration_ms=duration_ms,
            final_url=str(response.url),
        )

    content_type = response.headers.get("content-type", "").casefold()
    if content_type and not any(kind in content_type for kind in _ACCEPTABLE_CONTENT_TYPES):
        return FetchResult(
            url=safe_url,
            ok=False,
            status_code=response.status_code,
            error=f"unsupported content-type {content_type!r}",
            error_kind="unsupported_content_type",
            duration_ms=duration_ms,
            final_url=str(response.url),
        )

    html = response.text or ""
    if len(html.encode("utf-8", errors="ignore")) > settings.max_response_bytes:
        logger.warning("Truncating oversized response from %s", safe_url)
        html = html[: settings.max_response_bytes]

    return _to_result(
        url=safe_url,
        html=html,
        status_code=response.status_code,
        duration_ms=duration_ms,
        final_url=str(response.url),
        headers={k.lower(): v for k, v in response.headers.items()},
    )


def _to_result(
    *,
    url: str,
    html: str,
    status_code: int | None,
    duration_ms: int,
    final_url: str | None = None,
    renderer: str = "httpx",
    headers: dict[str, str] | None = None,
) -> FetchResult:
    """Normalise raw HTML into a populated :class:`FetchResult`."""
    normalized = normalize_html(html)
    return FetchResult(
        url=url,
        ok=True,
        status_code=status_code,
        raw_html=html,
        normalized_text=normalized,
        title=extract_title(html),
        content_hash=content_hash(normalized),
        word_count=word_count(normalized),
        duration_ms=duration_ms,
        final_url=final_url or url,
        renderer=renderer,
        headers=headers or {},
    )


def _request_with_retries(
    client: httpx.Client,
    url: str,
    *,
    max_retries: int,
    crawl_delay: float | None,
    max_redirects: int = 5,
) -> httpx.Response:
    """Issue the request, following and re-validating redirects manually."""
    current_url = url
    redirects = 0

    while True:
        response: httpx.Response | None = None
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            _respect_delay(current_url, crawl_delay)
            try:
                response = client.get(current_url)
                if response.status_code in _RETRYABLE_STATUS and attempt < max_retries:
                    wait = _retry_after(response) or 1.5 * (2**attempt)
                    logger.info(
                        "HTTP %d from %s; retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        current_url,
                        wait,
                        attempt + 1,
                        max_retries + 1,
                    )
                    time.sleep(wait)
                    continue
                break
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= max_retries:
                    raise
                wait = 1.5 * (2**attempt)
                logger.info(
                    "Fetch error for %s (%s); retrying in %.1fs", current_url, exc, wait
                )
                time.sleep(wait)

        if response is None:
            if last_error:
                raise last_error
            raise httpx.HTTPError(f"no response for {current_url}")

        if response.status_code not in (301, 302, 303, 307, 308):
            return response

        location = response.headers.get("location")
        if not location:
            return response

        redirects += 1
        if redirects > max_redirects:
            raise httpx.TooManyRedirects(f"exceeded {max_redirects} redirects from {url}")

        next_url = str(response.url.join(location))
        # Every hop is re-validated: a redirect is an SSRF vector.
        current_url = validate_url(next_url)
        logger.debug("Following redirect %d: %s", redirects, current_url)


def _retry_after(response: httpx.Response) -> float | None:
    """Parse a ``Retry-After`` header expressed in seconds."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, min(60.0, float(raw)))
    except ValueError:
        return None


def fetch_html_string(html: str, url: str = "local://snapshot") -> FetchResult:
    """Wrap an in-memory HTML string as a FetchResult.

    Used by the demo seeder and the Wayback evaluator, which already have the
    document and must not perform a network request.
    """
    return _to_result(
        url=url, html=html, status_code=200, duration_ms=0, final_url=url, renderer="memory"
    )
