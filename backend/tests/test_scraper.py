"""Tests for fetching, URL validation and robots.txt handling."""

from __future__ import annotations

import httpx
import pytest

from app.scrapers import robots
from app.scrapers.fetcher import FetchResult, fetch_html_string, fetch_url
from app.scrapers.url_guard import (
    UnsafeURLError,
    guess_page_type,
    is_safe_url,
    normalize_url,
    same_origin,
    validate_url,
)


def _client(handler) -> httpx.Client:
    """An httpx client backed by a mock transport."""
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


class TestURLValidation:
    @pytest.mark.parametrize(
        "url", ["https://example.com", "http://example.com/pricing", "example.com"]
    )
    def test_accepts_public_urls(self, url):
        assert validate_url(url).startswith("http")

    def test_adds_https_when_scheme_missing(self):
        assert normalize_url("example.com").startswith("https://")

    def test_strips_fragment(self):
        assert "#" not in normalize_url("https://example.com/page#section")

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/file",
            "gopher://example.com",
            "javascript:alert(1)",
        ],
    )
    def test_rejects_non_http_schemes(self, url):
        with pytest.raises(UnsafeURLError):
            validate_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://localhost:8000",
            "http://10.0.0.1/internal",
            "http://192.168.1.1",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://[::1]/",
            "http://0.0.0.0/",
        ],
    )
    def test_rejects_private_and_loopback(self, url):
        """SSRF protection: internal addresses must never be fetched."""
        with pytest.raises(UnsafeURLError):
            validate_url(url)

    def test_rejects_embedded_credentials(self):
        with pytest.raises(UnsafeURLError):
            validate_url("https://user:password@example.com")

    def test_rejects_empty(self):
        with pytest.raises(UnsafeURLError):
            validate_url("")

    def test_allows_private_when_explicitly_permitted(self):
        assert validate_url("http://127.0.0.1:8000", allow_private=True)

    def test_is_safe_url_helper(self):
        assert is_safe_url("https://example.com")
        assert not is_safe_url("http://127.0.0.1")

    def test_same_origin(self):
        assert same_origin("https://a.com/x", "https://a.com/y")
        assert not same_origin("https://a.com", "https://b.com")

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://x.com/pricing", "pricing"),
            ("https://x.com/plans/team", "pricing"),
            ("https://x.com/careers", "careers"),
            ("https://x.com/jobs/ml-engineer", "careers"),
            ("https://x.com/blog/post", "blog"),
            ("https://x.com/integrations", "integrations"),
            ("https://x.com/product", "product"),
            ("https://x.com/about", "generic"),
        ],
    )
    def test_guess_page_type(self, url, expected):
        assert guess_page_type(url) == expected


class TestSuccessfulFetch:
    def test_returns_normalised_content(self):
        html = "<html><head><title>Hi</title></head><body><main><p>Hello world here</p></main></body></html>"

        def handler(_request):
            return httpx.Response(200, html=html)

        result = fetch_url("https://example.com", check_robots=False, client=_client(handler))
        assert result.ok
        assert result.status_code == 200
        assert "Hello world here" in result.normalized_text
        assert result.title == "Hi"
        assert len(result.content_hash) == 64
        assert result.word_count > 0

    def test_follows_redirects(self):
        def handler(request):
            if request.url.path == "/old":
                return httpx.Response(301, headers={"location": "https://example.com/new"})
            return httpx.Response(200, html="<body><main><p>Final destination page</p></main></body>")

        result = fetch_url("https://example.com/old", check_robots=False, client=_client(handler))
        assert result.ok
        assert "Final destination" in result.normalized_text

    def test_rejects_redirect_to_private_address(self):
        """A redirect is an SSRF vector, so every hop is re-validated."""

        def handler(request):
            if "example.com" in str(request.url):
                return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
            return httpx.Response(200, html="<body><p>secret</p></body>")

        result = fetch_url("https://example.com", check_robots=False, client=_client(handler))
        assert not result.ok
        assert result.error_kind == "unsafe_redirect"


class TestFailedFetch:
    @pytest.mark.parametrize("status", [404, 403, 410])
    def test_http_errors_are_reported_not_raised(self, status):
        result = fetch_url(
            "https://example.com",
            check_robots=False,
            client=_client(lambda _r: httpx.Response(status)),
        )
        assert not result.ok
        assert result.error_kind == "http_error"
        assert result.status_code == status

    def test_timeout_is_handled(self):
        def handler(_request):
            raise httpx.ConnectTimeout("too slow")

        result = fetch_url(
            "https://example.com", check_robots=False, max_retries=0, client=_client(handler)
        )
        assert not result.ok
        assert result.error_kind == "timeout"

    def test_network_error_is_handled(self):
        def handler(_request):
            raise httpx.ConnectError("no route to host")

        result = fetch_url(
            "https://example.com", check_robots=False, max_retries=0, client=_client(handler)
        )
        assert not result.ok
        assert result.error_kind == "network_error"

    def test_retries_then_succeeds(self):
        attempts = {"count": 0}

        def handler(_request):
            attempts["count"] += 1
            if attempts["count"] < 3:
                return httpx.Response(503)
            return httpx.Response(200, html="<body><main><p>Recovered at last</p></main></body>")

        result = fetch_url(
            "https://example.com", check_robots=False, max_retries=3, client=_client(handler)
        )
        assert result.ok
        assert attempts["count"] == 3

    def test_gives_up_after_max_retries(self):
        result = fetch_url(
            "https://example.com",
            check_robots=False,
            max_retries=1,
            client=_client(lambda _r: httpx.Response(503)),
        )
        assert not result.ok
        assert result.status_code == 503

    def test_unsafe_url_never_hits_the_network(self):
        def handler(_request):  # pragma: no cover - must not run
            raise AssertionError("request should never be made")

        result = fetch_url("http://127.0.0.1/admin", check_robots=False, client=_client(handler))
        assert not result.ok
        assert result.error_kind == "unsafe_url"

    def test_dns_failure_is_reported_as_dns_error(self):
        """An unresolvable host is 'not found', not 'unsafe'."""

        def handler(_request):  # pragma: no cover - must not run
            raise AssertionError("request should never be made")

        result = fetch_url(
            "https://this-domain-definitely-does-not-exist-rivalradar.invalid",
            check_robots=False,
            client=_client(handler),
        )
        assert not result.ok
        assert result.error_kind == "dns_error"

    def test_rejects_non_html_content_type(self):
        def handler(_request):
            return httpx.Response(200, json={"not": "html"})

        result = fetch_url("https://example.com", check_robots=False, client=_client(handler))
        assert not result.ok
        assert result.error_kind == "unsupported_content_type"

    def test_too_many_redirects(self):
        def handler(_request):
            return httpx.Response(302, headers={"location": "https://example.com/loop"})

        result = fetch_url(
            "https://example.com/loop", check_robots=False, client=_client(handler)
        )
        assert not result.ok
        assert result.error_kind == "too_many_redirects"


class TestRobots:
    @pytest.fixture(autouse=True)
    def _enable_robots(self, monkeypatch):
        """The suite disables robots globally; these tests need it on."""
        monkeypatch.setattr(robots.settings, "respect_robots_txt", True)
        robots.clear_cache()
        yield
        robots.clear_cache()

    def test_disallow_is_respected(self, monkeypatch):
        monkeypatch.setattr(
            robots, "_load_robots", lambda origin, timeout: _parsed("User-agent: *\nDisallow: /")
        )
        decision = robots.check("https://example.com/page")
        assert not decision.allowed

    def test_allow_is_respected(self, monkeypatch):
        monkeypatch.setattr(
            robots,
            "_load_robots",
            lambda origin, timeout: _parsed("User-agent: *\nDisallow: /private"),
        )
        assert robots.check("https://example.com/public").allowed

    def test_fails_open_when_unreachable(self, monkeypatch):
        monkeypatch.setattr(
            robots,
            "_load_robots",
            lambda origin, timeout: robots._CacheEntry(parser=None, fetched_at=0.0, reachable=False),
        )
        assert robots.check("https://example.com/page").allowed

    def test_crawl_delay_is_surfaced(self, monkeypatch):
        monkeypatch.setattr(
            robots,
            "_load_robots",
            lambda origin, timeout: _parsed("User-agent: *\nCrawl-delay: 5\nDisallow: /nope"),
        )
        assert robots.check("https://example.com/ok").crawl_delay == 5.0


def _parsed(body: str):
    """Build a cache entry from robots.txt text."""
    import time
    from urllib.robotparser import RobotFileParser

    parser = RobotFileParser()
    parser.parse(body.splitlines())
    return robots._CacheEntry(parser=parser, fetched_at=time.time(), reachable=True)


class TestFetchHtmlString:
    def test_wraps_in_memory_html(self):
        result = fetch_html_string("<body><main><p>In memory content</p></main></body>")
        assert result.ok
        assert result.renderer == "memory"
        assert "In memory content" in result.normalized_text

    def test_result_serialises(self):
        payload = fetch_html_string("<body><p>x</p></body>").as_dict()
        assert payload["ok"] is True
        assert "content_hash" in payload


class TestPlaywrightFallback:
    def test_missing_playwright_is_reported_cleanly(self, monkeypatch):
        from app.scrapers import playwright_fetcher

        monkeypatch.setattr(playwright_fetcher, "is_available", lambda: False)
        result = playwright_fetcher.fetch_with_playwright("https://example.com")
        assert isinstance(result, FetchResult)
        assert not result.ok
        assert result.error_kind == "playwright_missing"
