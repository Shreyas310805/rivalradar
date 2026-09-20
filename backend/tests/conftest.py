"""Shared pytest fixtures.

Every test runs against an in-memory SQLite database and the offline heuristic
LLM provider, so the suite needs no API key and makes no network requests
(except tests explicitly marked ``network``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Force a deterministic, offline configuration before app modules import.
#
# These are set unconditionally (not setdefault) so the suite NEVER picks up a
# real API key from backend/.env. Tests must be hermetic: no live LLM calls, no
# spending a developer's free-tier quota, and identical results on CI.
# Environment variables take precedence over the .env file in pydantic-settings.
os.environ["LLM_PROVIDER"] = "deterministic"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["OPENROUTER_MODEL"] = "openrouter/free"
os.environ["OPENAI_API_KEY"] = ""
os.environ["DEMO_MODE"] = "false"
os.environ.setdefault("RESPECT_ROBOTS_TXT", "false")
os.environ.setdefault("REQUEST_DELAY_SECONDS", "0")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.models.entities import Competitor, TrackedURL  # noqa: E402


@pytest.fixture
def engine():
    """A fresh in-memory database per test.

    ``StaticPool`` keeps every connection pointed at the *same* in-memory
    database.  Without it each new connection gets its own blank database, and
    TestClient (which runs the app on another thread) sees no tables.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session(engine):
    """A session bound to the in-memory database."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def competitor(session) -> Competitor:
    """A saved competitor with one tracked URL."""
    record = Competitor(
        name="NovaStack",
        website_url="https://novastack.example.com",
        tracking_frequency="daily",
        active=True,
    )
    session.add(record)
    session.flush()
    session.add(
        TrackedURL(
            competitor_id=record.id,
            url="https://novastack.example.com/pricing",
            label="Pricing",
            page_type="pricing",
        )
    )
    session.commit()
    session.refresh(record)
    return record


@pytest.fixture
def pricing_page_v1() -> str:
    """Baseline pricing page with navigation, footer and cookie-banner noise."""
    return """
    <html><head><title>NovaStack Pricing</title></head><body>
      <nav class="site-nav"><a href="/?utm_source=x">Home</a><a href="/pricing">Pricing</a></nav>
      <div class="cookie-banner">We use cookies to improve your experience. Accept all</div>
      <main>
        <h1>Simple pricing for growing teams</h1>
        <section class="pricing-table">
          <div class="plan"><h3>Pro Plan</h3><p class="price">Rs 999/month</p>
            <ul><li>5 projects</li><li>Basic analytics</li></ul></div>
        </section>
      </main>
      <footer class="site-footer">
        <p>Copyright 2025 NovaStack. All rights reserved.</p>
        <p>Session ID: 8f14e45f-ceea-467a-9a1e-4b2d3c9f0011</p>
        <p>Generated 2025-04-01T10:22:31Z</p>
      </footer>
    </body></html>
    """


@pytest.fixture
def pricing_page_v2() -> str:
    """Updated pricing page: price rise, plan-limit bump and an AI feature."""
    return """
    <html><head><title>NovaStack Pricing</title></head><body>
      <nav class="site-nav"><a href="/?utm_source=y">Home</a><a href="/pricing">Pricing</a></nav>
      <div class="cookie-banner">We use cookies to improve your experience. Accept all</div>
      <main>
        <h1>Simple pricing for growing teams</h1>
        <section class="pricing-table">
          <div class="plan"><h3>Pro Plan</h3><p class="price">Rs 1499/month</p>
            <ul><li>10 projects</li><li>AI-powered analytics</li></ul></div>
        </section>
      </main>
      <footer class="site-footer">
        <p>Copyright 2026 NovaStack. All rights reserved.</p>
        <p>Session ID: 1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed</p>
        <p>Generated 2026-05-01T11:02:09Z</p>
      </footer>
    </body></html>
    """


@pytest.fixture
def careers_page_v1() -> str:
    return """
    <html><body><main><section class="careers">
      <h1>Careers at CloudPilot</h1>
      <ul><li>Senior Backend Engineer - Remote</li><li>Product Designer - Berlin</li></ul>
    </section></main></body></html>
    """


@pytest.fixture
def careers_page_v2() -> str:
    return """
    <html><body><main><section class="careers">
      <h1>Careers at CloudPilot</h1>
      <ul><li>Senior Backend Engineer - Remote</li><li>Product Designer - Berlin</li>
      <li>Machine Learning Engineer - Remote</li>
      <li>Senior Machine Learning Engineer, Platform - Remote</li>
      <li>Research Scientist, Applied ML - London</li></ul>
    </section></main></body></html>
    """
