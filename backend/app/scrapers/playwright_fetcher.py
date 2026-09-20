"""Optional JavaScript rendering via Playwright.

Playwright is an optional dependency: installing it pulls a browser binary that
most portfolio reviewers will not want.  Everything here degrades to a clear
error when it is missing, and the plain HTTP fetcher takes over.

Enable with::

    pip install -r requirements-playwright.txt
    playwright install chromium
    PLAYWRIGHT_ENABLED=true
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.config.logging import get_logger
from app.config.settings import settings

if TYPE_CHECKING:  # pragma: no cover - import cycle avoided at runtime
    from app.scrapers.fetcher import FetchResult

logger = get_logger(__name__)


def is_available() -> bool:
    """True when the Playwright package is importable."""
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def fetch_with_playwright(
    url: str,
    *,
    timeout: float | None = None,
    wait_until: str = "networkidle",
) -> FetchResult:
    """Render a page in Chromium and return a ``FetchResult``.

    Imported lazily from the fetcher to avoid a circular import.
    """
    from app.scrapers.fetcher import FetchResult, _to_result

    timeout = settings.request_timeout_seconds if timeout is None else timeout

    if not is_available():
        return FetchResult(
            url=url,
            ok=False,
            error="playwright is not installed (pip install -r requirements-playwright.txt)",
            error_kind="playwright_missing",
            renderer="playwright",
        )

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    started = time.monotonic()
    try:
        with sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            try:
                context = browser.new_context(
                    user_agent=settings.scan_user_agent,
                    viewport={"width": 1440, "height": 900},
                    java_script_enabled=True,
                )
                page = context.new_page()
                # Images and fonts are irrelevant to a text diff.
                page.route(
                    "**/*",
                    lambda route: (
                        route.abort()
                        if route.request.resource_type in {"image", "media", "font"}
                        else route.continue_()
                    ),
                )
                response = page.goto(url, timeout=timeout * 1000, wait_until=wait_until)
                page.wait_for_timeout(500)  # let late hydration settle
                html = page.content()
                status = response.status if response else None
            finally:
                browser.close()
    except PlaywrightTimeout as exc:
        return FetchResult(
            url=url,
            ok=False,
            error=f"playwright timeout: {exc}",
            error_kind="timeout",
            renderer="playwright",
        )
    except PlaywrightError as exc:
        return FetchResult(
            url=url,
            ok=False,
            error=f"playwright error: {exc}",
            error_kind="render_error",
            renderer="playwright",
        )
    except Exception as exc:  # noqa: BLE001 - never break a scan
        logger.error("Unexpected Playwright failure for %s", url, exc_info=True)
        return FetchResult(
            url=url, ok=False, error=str(exc), error_kind="unexpected", renderer="playwright"
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    return _to_result(
        url=url,
        html=html,
        status_code=status,
        duration_ms=duration_ms,
        final_url=url,
        renderer="playwright",
    )
