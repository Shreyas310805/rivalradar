"""API integration tests using FastAPI's TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database.session import get_db
from app.main import app


@pytest.fixture
def client(engine):
    """A TestClient wired to the in-memory test database."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestSystemRoutes:
    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root(self, client):
        assert client.get("/").status_code == 200

    def test_openapi_schema(self, client):
        assert client.get("/openapi.json").status_code == 200


class TestCompetitorCRUD:
    def test_create_and_read(self, client):
        created = client.post(
            "/api/competitors",
            json={"name": "NovaStack", "website_url": "https://novastack.example.com"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "NovaStack"
        # A homepage is tracked by default so the competitor is never empty.
        assert len(body["tracked_urls"]) == 1

        fetched = client.get(f"/api/competitors/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "NovaStack"

    def test_list_is_empty_initially(self, client):
        assert client.get("/api/competitors").json() == []

    def test_duplicate_name_conflicts(self, client):
        payload = {"name": "Dup", "website_url": "https://dup.example.com"}
        assert client.post("/api/competitors", json=payload).status_code == 201
        assert client.post("/api/competitors", json=payload).status_code == 409

    def test_update(self, client):
        cid = client.post(
            "/api/competitors", json={"name": "Edit", "website_url": "https://edit.example.com"}
        ).json()["id"]
        response = client.put(f"/api/competitors/{cid}", json={"description": "changed"})
        assert response.status_code == 200
        assert response.json()["description"] == "changed"

    def test_toggle_active(self, client):
        cid = client.post(
            "/api/competitors", json={"name": "Toggle", "website_url": "https://t.example.com"}
        ).json()["id"]
        assert client.post(f"/api/competitors/{cid}/toggle?active=false").json()["active"] is False

    def test_delete(self, client):
        cid = client.post(
            "/api/competitors", json={"name": "Gone", "website_url": "https://gone.example.com"}
        ).json()["id"]
        assert client.delete(f"/api/competitors/{cid}").status_code == 204
        assert client.get(f"/api/competitors/{cid}").status_code == 404

    def test_missing_competitor_is_404(self, client):
        assert client.get("/api/competitors/99999").status_code == 404
        assert client.delete("/api/competitors/99999").status_code == 404


class TestValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://localhost:8000",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "ftp://example.com",
        ],
    )
    def test_rejects_unsafe_urls(self, client, url):
        """SSRF protection is enforced at the API boundary."""
        response = client.post("/api/competitors", json={"name": "Bad", "website_url": url})
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"

    def test_rejects_empty_name(self, client):
        response = client.post(
            "/api/competitors", json={"name": "", "website_url": "https://example.com"}
        )
        assert response.status_code == 422

    def test_rejects_missing_fields(self, client):
        assert client.post("/api/competitors", json={"name": "NoURL"}).status_code == 422

    def test_error_body_shape_is_uniform(self, client):
        body = client.get("/api/competitors/99999").json()
        assert "detail" in body
        assert "code" in body


class TestTrackedURLs:
    def test_add_list_update_delete(self, client):
        cid = client.post(
            "/api/competitors", json={"name": "Pages", "website_url": "https://pages.example.com"}
        ).json()["id"]

        created = client.post(
            f"/api/competitors/{cid}/urls",
            json={"url": "https://pages.example.com/pricing", "label": "Pricing"},
        )
        assert created.status_code == 201
        # Page type is inferred from the path.
        assert created.json()["page_type"] == "pricing"
        url_id = created.json()["id"]

        assert len(client.get(f"/api/competitors/{cid}/urls").json()) == 2

        updated = client.put(f"/api/competitors/urls/{url_id}", json={"active": False})
        assert updated.json()["active"] is False

        assert client.delete(f"/api/competitors/urls/{url_id}").status_code == 204

    def test_duplicate_url_conflicts(self, client):
        cid = client.post(
            "/api/competitors", json={"name": "Dupe", "website_url": "https://dupe.example.com"}
        ).json()["id"]
        payload = {"url": "https://dupe.example.com/pricing"}
        assert client.post(f"/api/competitors/{cid}/urls", json=payload).status_code == 201
        assert client.post(f"/api/competitors/{cid}/urls", json=payload).status_code == 409

    def test_rejects_unsafe_tracked_url(self, client):
        cid = client.post(
            "/api/competitors", json={"name": "Safe", "website_url": "https://safe.example.com"}
        ).json()["id"]
        response = client.post(f"/api/competitors/{cid}/urls", json={"url": "http://127.0.0.1/x"})
        assert response.status_code == 422


class TestIntelligenceRoutes:
    @pytest.fixture
    def seeded(self, client, engine, pricing_page_v1, pricing_page_v2):
        """A competitor with a real scanned change pair."""
        from app.models.entities import Competitor
        from app.scrapers.fetcher import fetch_html_string
        from app.services.scan import scan_tracked_url

        cid = client.post(
            "/api/competitors",
            json={
                "name": "Seeded",
                "website_url": "https://seeded.example.com",
                "tracked_urls": [{"url": "https://seeded.example.com/pricing"}],
            },
        ).json()["id"]

        factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        session = factory()
        try:
            competitor = session.get(Competitor, cid)
            tracked = [u for u in competitor.tracked_urls if u.url.endswith("/pricing")][0]
            scan_tracked_url(
                session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v1)
            )
            scan_tracked_url(
                session, competitor, tracked, fetch_result=fetch_html_string(pricing_page_v2)
            )
            # scan_tracked_url flushes but leaves committing to its caller
            # (normally scan_competitor), so the fixture must commit itself.
            session.commit()
        finally:
            session.close()
        return cid

    def test_lists_changes(self, client, seeded):
        changes = client.get("/api/changes").json()
        assert changes
        assert all(not change["is_noise"] for change in changes)

    def test_include_noise_flag(self, client, seeded):
        clean = client.get("/api/changes").json()
        noisy = client.get("/api/changes?include_noise=true").json()
        assert len(noisy) > len(clean)
        assert any(change["is_noise"] for change in noisy)

    def test_change_detail_has_word_diff(self, client, seeded):
        change_id = client.get("/api/changes").json()[0]["id"]
        detail = client.get(f"/api/changes/{change_id}").json()
        assert detail["diff_segments"]
        assert {segment["op"] for segment in detail["diff_segments"]} & {"insert", "delete", "equal"}

    def test_change_404(self, client):
        assert client.get("/api/changes/99999").status_code == 404

    def test_filters_by_competitor_and_category(self, client, seeded):
        assert client.get(f"/api/changes?competitor_id={seeded}").json()
        assert client.get("/api/changes?competitor_id=99999").json() == []
        assert isinstance(client.get("/api/changes?category=pricing").json(), list)

    def test_filters_by_min_score(self, client, seeded):
        high = client.get("/api/changes?min_score=70").json()
        assert all(change["relevance_score"] >= 70 for change in high)

    def test_lists_intelligence(self, client, seeded):
        items = client.get("/api/intelligence").json()
        assert items
        for item in items:
            assert item["title"]
            assert 0 <= item["relevance_score"] <= 100
            assert 0 <= item["confidence"] <= 1
            assert item["competitor_name"]

    def test_stats_funnel_is_consistent(self, client, seeded):
        stats = client.get("/api/stats").json()
        assert stats["raw_changes"] == stats["noise_changes"] + stats["meaningful_changes"]
        assert 0 <= stats["noise_reduction"] <= 100

    def test_analytics_payload(self, client, seeded):
        payload = client.get("/api/analytics").json()
        for key in (
            "stats",
            "categories",
            "timeline",
            "noise_reasons",
            "severity_distribution",
            "top_competitors",
        ):
            assert key in payload
        assert payload["noise_reasons"], "expected noise reasons to be reported"

    def test_digest_generate_and_fetch(self, client, seeded):
        generated = client.post("/api/digest/generate", json={"days": 7})
        assert generated.status_code == 200
        body = generated.json()
        assert "RIVALRADAR" in body["content"]
        assert body["raw_changes"] >= 0

        latest = client.get("/api/digest/latest")
        assert latest.status_code == 200
        assert latest.json()["id"] == body["id"]

    def test_digest_404_before_generation(self, client):
        assert client.get("/api/digest/latest").status_code == 404


class TestEvaluationRoutes:
    def test_empty_evaluation_list(self, client):
        assert client.get("/api/evaluation/wayback").json() == []

    def test_latest_404_when_none(self, client):
        assert client.get("/api/evaluation/wayback/latest").status_code == 404

    def test_rejects_unsafe_evaluation_target(self, client):
        response = client.post("/api/evaluation/wayback", json={"url": "http://127.0.0.1/"})
        assert response.status_code == 422
