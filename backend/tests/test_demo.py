"""Tests for demo data and the seeding path.

Seeding must produce its numbers by running the real pipeline, never by
inserting pre-written change rows — the dashboard's credibility depends on it.
"""

from __future__ import annotations

from app.database.demo_pages import COMPETITORS, demo_html_for, is_demo_url, tracked_pages
from app.database.seed import seed
from app.models.entities import Change, Competitor, Intelligence, Snapshot


class TestDemoPages:
    def test_three_fictional_competitors(self):
        names = {entry["name"] for entry in COMPETITORS}
        assert names == {"NovaStack", "CloudPilot", "DataForge"}

    def test_every_page_has_both_revisions(self):
        for page in tracked_pages():
            assert page["v1"].strip().startswith("<!DOCTYPE html>")
            assert page["v2"].strip().startswith("<!DOCTYPE html>")
            assert page["v1"] != page["v2"]

    def test_pages_contain_the_planted_signals(self):
        pages = {page["url"]: page for page in tracked_pages()}
        pricing = pages["https://novastack.example.com/pricing"]
        assert "Rs 999/month" in pricing["v1"]
        assert "Rs 1499/month" in pricing["v2"]
        assert "5 projects" in pricing["v1"]
        assert "10 projects" in pricing["v2"]

        careers = pages["https://cloudpilot.example.com/careers"]
        assert "Machine Learning Engineer" not in careers["v1"]
        assert "Machine Learning Engineer" in careers["v2"]

    def test_pages_contain_noise_to_filter(self):
        """The fixtures must challenge the filter, not flatter it."""
        for page in tracked_pages():
            assert "cookie-banner" in page["v1"]
            assert "Session ID" in page["v1"]
            assert "Copyright 2025" in page["v1"]
            assert "Copyright 2026" in page["v2"]

    def test_demo_lookup(self):
        assert is_demo_url("https://novastack.example.com/pricing")
        assert not is_demo_url("https://example.com/pricing")
        assert demo_html_for("https://not-a-demo.example.org") is None


class TestSeeding:
    def test_seed_runs_the_real_pipeline(self, session):
        stats = seed(session, reset=True)

        assert session.query(Competitor).count() == 3
        assert session.query(Snapshot).count() > 0
        assert session.query(Change).count() > 0
        assert session.query(Intelligence).count() > 0

        assert stats.raw_changes > 0
        assert stats.meaningful_changes > 0
        assert stats.noise_changes > 0

    def test_seeded_funnel_matches_stored_rows(self, session):
        """The reported funnel must be countable from the database."""
        stats = seed(session, reset=True)

        stored_raw = session.query(Change).count()
        stored_noise = session.query(Change).filter(Change.is_noise.is_(True)).count()

        assert stats.raw_changes == stored_raw
        assert stats.noise_changes == stored_noise
        assert stats.meaningful_changes == stored_raw - stored_noise

    def test_seeding_detects_the_price_rise(self, session):
        seed(session, reset=True)
        pricing = (
            session.query(Change)
            .filter(Change.category == "pricing", Change.is_noise.is_(False))
            .all()
        )
        assert pricing, "the planted price change must be detected"
        assert any("1499" in (change.after or "") for change in pricing)

    def test_seeding_detects_ml_hiring(self, session):
        seed(session, reset=True)
        hiring = (
            session.query(Change)
            .filter(Change.category == "hiring", Change.is_noise.is_(False))
            .all()
        )
        assert hiring, "the planted ML hiring signal must be detected"

    def test_seeding_rejects_the_planted_noise(self, session):
        seed(session, reset=True)
        noise = session.query(Change).filter(Change.is_noise.is_(True)).all()
        reasons = {change.noise_reason for change in noise}
        assert noise
        assert any("identical" in (reason or "") for reason in reasons)

    def test_seeding_is_idempotent_with_reset(self, session):
        first = seed(session, reset=True)
        second = seed(session, reset=True)
        assert first.raw_changes == second.raw_changes
        assert session.query(Competitor).count() == 3
