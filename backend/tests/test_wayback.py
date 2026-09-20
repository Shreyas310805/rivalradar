"""Tests for the Wayback Machine client and the evaluation harness.

Network calls are mocked by default.  The live-Archive test is marked
``network`` and can be deselected with ``-m 'not network'``.
"""

from __future__ import annotations

import httpx
import pytest

from app.evaluation.runner import (
    EvaluationReport,
    PageEvaluation,
    evaluate_html_pair,
    format_report,
)
from app.services import wayback as wayback_module
from app.services.wayback import (
    WaybackError,
    WaybackSnapshot,
    decode_archive_bytes,
    download_snapshot,
    list_snapshots,
    select_snapshot_pair,
)

CDX_PAYLOAD = [
    ["timestamp", "original", "statuscode", "digest", "length"],
    ["20230101120000", "https://example.com/", "200", "AAAA1111", "5000"],
    ["20230601120000", "https://example.com/", "200", "BBBB2222", "5200"],
    ["20240101120000", "https://example.com/", "200", "CCCC3333", "5400"],
]


def _response(*args, **kwargs) -> httpx.Response:
    """Build a Response with a request attached, so raise_for_status works."""
    kwargs.setdefault("request", httpx.Request("GET", "https://web.archive.org/cdx"))
    return httpx.Response(*args, **kwargs)


def _snapshot(timestamp: str, digest: str = "X") -> WaybackSnapshot:
    return WaybackSnapshot(
        timestamp=timestamp,
        original_url="https://example.com/",
        status_code="200",
        digest=digest,
    )


class TestSnapshotModel:
    def test_archive_url_uses_raw_form(self):
        """The id_ suffix suppresses the Archive's injected toolbar."""
        assert "id_/" in _snapshot("20230101120000").archive_url

    def test_parses_timestamp(self):
        assert _snapshot("20230101120000").date.year == 2023

    def test_iso_date(self):
        assert _snapshot("20230415120000").iso_date == "2023-04-15"

    def test_malformed_timestamp_is_survivable(self):
        assert _snapshot("garbage").date is None


class TestListSnapshots:
    def test_parses_cdx_rows(self, monkeypatch):
        monkeypatch.setattr(
            wayback_module.httpx, "get", lambda *a, **k: _response(200, json=CDX_PAYLOAD)
        )
        snapshots = list_snapshots("https://example.com/")
        assert len(snapshots) == 3
        assert snapshots[0].timestamp == "20230101120000"

    def test_returns_empty_when_archive_has_nothing(self, monkeypatch):
        monkeypatch.setattr(
            wayback_module.httpx, "get", lambda *a, **k: _response(200, json=[])
        )
        assert list_snapshots("https://example.com/") == []

    def test_results_are_sorted_by_time(self, monkeypatch):
        shuffled = [CDX_PAYLOAD[0], CDX_PAYLOAD[3], CDX_PAYLOAD[1], CDX_PAYLOAD[2]]
        monkeypatch.setattr(
            wayback_module.httpx, "get", lambda *a, **k: _response(200, json=shuffled)
        )
        timestamps = [s.timestamp for s in list_snapshots("https://example.com/")]
        assert timestamps == sorted(timestamps)

    def test_raises_on_persistent_failure(self, monkeypatch):
        def boom(*_a, **_k):
            raise httpx.ConnectError("archive down")

        monkeypatch.setattr(wayback_module.httpx, "get", boom)
        monkeypatch.setattr(wayback_module.time, "sleep", lambda _s: None)
        with pytest.raises(WaybackError):
            list_snapshots("https://example.com/")

    def test_rejects_unsafe_target(self):
        with pytest.raises(WaybackError):
            list_snapshots("http://127.0.0.1/")

    def test_rejects_malformed_dates(self, monkeypatch):
        monkeypatch.setattr(
            wayback_module.httpx, "get", lambda *a, **k: _response(200, json=CDX_PAYLOAD)
        )
        with pytest.raises(ValueError):
            list_snapshots("https://example.com/", from_date="not-a-date")

    def test_negative_limit_requests_newest(self, monkeypatch):
        captured = {}

        def capture(*_a, **kwargs):
            captured.update(kwargs.get("params", {}))
            return _response(200, json=CDX_PAYLOAD)

        monkeypatch.setattr(wayback_module.httpx, "get", capture)
        list_snapshots("https://example.com/", limit=10, newest_first=True)
        assert captured["limit"] == -10


class TestSelectSnapshotPair:
    def test_picks_the_widest_gap(self):
        older, newer = select_snapshot_pair(
            [_snapshot("20230101120000", "A"), _snapshot("20230601120000", "B"), _snapshot("20240101120000", "C")]
        )
        assert older.timestamp == "20230101120000"
        assert newer.timestamp == "20240101120000"

    def test_raises_when_only_one_snapshot(self):
        with pytest.raises(WaybackError):
            select_snapshot_pair([_snapshot("20230101120000")])

    def test_raises_on_empty_list(self):
        with pytest.raises(WaybackError):
            select_snapshot_pair([])

    def test_collapses_identical_digests(self):
        """Two captures of the same bytes are not a usable comparison."""
        with pytest.raises(WaybackError):
            select_snapshot_pair(
                [_snapshot("20230101120000", "SAME"), _snapshot("20240101120000", "SAME")]
            )


class TestDownloadSnapshot:
    def test_returns_html(self, monkeypatch):
        monkeypatch.setattr(
            wayback_module.httpx,
            "get",
            lambda *a, **k: _response(200, html="<html><body><p>archived</p></body></html>"),
        )
        assert "archived" in download_snapshot(_snapshot("20230101120000"))

    def test_raises_on_http_error(self, monkeypatch):
        monkeypatch.setattr(wayback_module.httpx, "get", lambda *a, **k: _response(404))
        with pytest.raises(WaybackError):
            download_snapshot(_snapshot("20230101120000"))

    def test_raises_on_empty_document(self, monkeypatch):
        monkeypatch.setattr(wayback_module.httpx, "get", lambda *a, **k: _response(200, text="  "))
        with pytest.raises(WaybackError):
            download_snapshot(_snapshot("20230101120000"))


class TestDecoding:
    def test_prefers_utf8(self):
        response = httpx.Response(200, content="café pricing".encode())
        assert "café" in decode_archive_bytes(response)

    def test_falls_back_for_legacy_encodings(self):
        """Mis-decoded bytes used to show up as spurious diffs."""
        response = httpx.Response(200, content="naïve".encode("cp1252"))
        assert decode_archive_bytes(response)

    def test_empty_body(self):
        assert decode_archive_bytes(httpx.Response(200, content=b"")) == ""


class TestEvaluateHtmlPair:
    def test_measures_the_funnel(self, pricing_page_v1, pricing_page_v2):
        stats, changes = evaluate_html_pair(pricing_page_v1, pricing_page_v2, url="https://x.com")
        assert stats.raw_changes == len(changes)
        assert stats.raw_changes == stats.noise_changes + stats.meaningful_changes
        assert stats.noise_changes > 0
        assert stats.meaningful_changes > 0

    def test_identical_pages_yield_nothing(self, pricing_page_v1):
        stats, changes = evaluate_html_pair(pricing_page_v1, pricing_page_v1)
        assert stats.raw_changes == 0
        assert changes == []

    def test_noise_reduction_is_a_percentage(self, pricing_page_v1, pricing_page_v2):
        stats, _ = evaluate_html_pair(pricing_page_v1, pricing_page_v2)
        assert 0.0 <= stats.noise_reduction <= 100.0


class TestEvaluationReport:
    def _report(self) -> EvaluationReport:
        from app.diff.types import DiffStats

        report = EvaluationReport(targets=["https://a.com", "https://b.com"])
        report.pages = [
            PageEvaluation(
                url="https://a.com",
                stats=DiffStats(100, 80, 20, 8),
                categories={"pricing": 2, "features": 3},
                date_a="2023-01-01",
                date_b="2024-01-01",
            ),
            PageEvaluation(
                url="https://b.com",
                stats=DiffStats(50, 40, 10, 4),
                categories={"pricing": 1, "hiring": 2},
                date_a="2023-01-01",
                date_b="2024-01-01",
            ),
            PageEvaluation(url="https://c.com", status="no_snapshots", error="nothing archived"),
        ]
        return report

    def test_aggregates_only_successful_pages(self):
        report = self._report()
        assert len(report.successful_pages) == 2
        assert report.stats.raw_changes == 150
        assert report.stats.noise_changes == 120

    def test_aggregate_noise_reduction(self):
        assert self._report().stats.noise_reduction == 80.0

    def test_merges_category_counts(self):
        assert self._report().categories["pricing"] == 3

    def test_serialises(self):
        payload = self._report().to_dict()
        assert payload["pages_evaluated"] == 2
        assert payload["pages_failed"] == 1
        assert payload["noise_reduction"] == 80.0

    def test_formats_a_readable_report(self):
        text = format_report(self._report())
        assert "Raw changes:" in text
        assert "Noise reduction:" in text
        assert "80.0%" in text

    def test_report_mentions_failures(self):
        assert "no_snapshots" in format_report(self._report())

    def test_empty_report_does_not_divide_by_zero(self):
        assert EvaluationReport().stats.noise_reduction == 0.0


class TestEvaluateWaybackUrl:
    def test_missing_snapshots_degrade_gracefully(self, monkeypatch):
        """No archived captures must not raise, just report the reason."""
        from app.evaluation import runner

        monkeypatch.setattr(runner, "list_snapshots_spread", lambda *a, **k: [])
        page = runner.evaluate_wayback_url("https://example.com")
        assert page.status == "no_snapshots"
        assert page.stats.raw_changes == 0

    def test_archive_error_is_captured(self, monkeypatch):
        from app.evaluation import runner

        def boom(*_a, **_k):
            raise WaybackError("rate limited")

        monkeypatch.setattr(runner, "list_snapshots_spread", boom)
        page = runner.evaluate_wayback_url("https://example.com")
        assert page.status == "failed"
        assert "rate limited" in page.error

    def test_full_comparison(self, monkeypatch, pricing_page_v1, pricing_page_v2):
        from app.evaluation import runner

        monkeypatch.setattr(
            runner,
            "list_snapshots_spread",
            lambda *a, **k: [_snapshot("20230101120000", "A"), _snapshot("20240101120000", "B")],
        )
        pages = iter([pricing_page_v1, pricing_page_v2])
        monkeypatch.setattr(runner, "download_snapshot", lambda _s: next(pages))

        page = runner.evaluate_wayback_url("https://example.com")
        assert page.status == "completed"
        assert page.stats.raw_changes > 0
        assert page.stats.meaningful_changes > 0
        assert page.date_a == "2023-01-01"
        assert page.top_changes


@pytest.mark.network
class TestLiveArchive:
    def test_real_cdx_query(self):
        """Hits the real Internet Archive. Deselect with -m 'not network'."""
        snapshots = list_snapshots(
            "https://www.python.org/", from_date="2023-01-01", to_date="2023-03-01", limit=5
        )
        assert snapshots
        assert all(snap.status_code == "200" for snap in snapshots)
