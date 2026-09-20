"""robots.txt awareness.

RivalRadar is a polite crawler: it fetches one page at a time, identifies
itself, and honours ``Disallow`` and ``Crawl-delay`` for its own user agent.
Results are cached per origin so a scan does not re-fetch robots.txt per URL.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config.logging import get_logger
from app.config.settings import settings

logger = get_logger(__name__)

# Origins are re-checked after this many seconds.
_CACHE_TTL_SECONDS = 3600.0


@dataclass(slots=True)
class RobotsDecision:
    """Outcome of a robots.txt check."""

    allowed: bool
    crawl_delay: float | None = None
    reason: str = ""


@dataclass(slots=True)
class _CacheEntry:
    parser: RobotFileParser | None
    fetched_at: float
    reachable: bool = True


_cache: dict[str, _CacheEntry] = {}


def _origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_robots(origin: str, *, timeout: float) -> _CacheEntry:
    """Fetch and parse robots.txt for an origin, tolerating every failure."""
    robots_url = urljoin(origin + "/", "robots.txt")
    try:
        response = httpx.get(
            robots_url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.scan_user_agent},
        )
    except Exception as exc:  # noqa: BLE001 - network failure must not block a scan
        logger.debug("robots.txt unreachable for %s: %s", origin, exc)
        return _CacheEntry(parser=None, fetched_at=time.time(), reachable=False)

    # 4xx means "no restrictions published"; 5xx means we simply do not know.
    if response.status_code >= 400:
        return _CacheEntry(
            parser=None, fetched_at=time.time(), reachable=response.status_code < 500
        )

    parser = RobotFileParser()
    try:
        parser.parse(response.text.splitlines())
    except Exception:  # noqa: BLE001 - malformed robots.txt is common
        logger.debug("Malformed robots.txt at %s", robots_url)
        return _CacheEntry(parser=None, fetched_at=time.time(), reachable=True)

    return _CacheEntry(parser=parser, fetched_at=time.time(), reachable=True)


def check(url: str, *, user_agent: str | None = None, timeout: float = 10.0) -> RobotsDecision:
    """Decide whether ``url`` may be fetched.

    Fails open: if robots.txt cannot be retrieved or parsed, the fetch is
    allowed.  It only ever blocks on an explicit ``Disallow``.
    """
    if not settings.respect_robots_txt:
        return RobotsDecision(allowed=True, reason="robots.txt checking disabled")

    agent = user_agent or settings.scan_user_agent
    origin = _origin_of(url)

    entry = _cache.get(origin)
    if entry is None or (time.time() - entry.fetched_at) > _CACHE_TTL_SECONDS:
        entry = _load_robots(origin, timeout=timeout)
        _cache[origin] = entry

    if entry.parser is None:
        return RobotsDecision(allowed=True, reason="no usable robots.txt (failing open)")

    try:
        allowed = entry.parser.can_fetch(agent, url)
        delay = entry.parser.crawl_delay(agent)
    except Exception:  # noqa: BLE001 - defensive
        return RobotsDecision(allowed=True, reason="robots.txt evaluation failed (failing open)")

    return RobotsDecision(
        allowed=bool(allowed),
        crawl_delay=float(delay) if delay else None,
        reason="" if allowed else f"disallowed by robots.txt for {agent}",
    )


def clear_cache() -> None:
    """Drop the robots.txt cache (used by tests)."""
    _cache.clear()
