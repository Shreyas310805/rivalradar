"""Demo page content for the three fictional competitors.

Every company, product and price here is invented.  Nothing in this module
describes a real organisation.

Each page has a ``v1`` and ``v2`` revision.  Seeding stores v1 as the baseline
snapshot, then scans v2 so the whole pipeline runs for real and the dashboard
fills with genuinely detected changes rather than hardcoded rows.

The revisions deliberately mix real signals (a price rise, an AI feature, ML
hiring, new integrations) with noise (rotating session ids, copyright years,
visitor counters, cookie banners, nav tweaks) so the noise filter has something
to earn its keep against.
"""

from __future__ import annotations

# --- Shared chrome ---------------------------------------------------------

_NAV = """
<nav class="site-nav">
  <a href="/">Home</a><a href="/product">Product</a><a href="/pricing">Pricing</a>
  <a href="/integrations">Integrations</a><a href="/careers">Careers</a>
  {extra}
</nav>
<div class="cookie-banner">We use cookies to improve your experience. Accept all | Manage preferences</div>
"""

_FOOTER = """
<footer class="site-footer">
  <p>Copyright {year} {company}. All rights reserved.</p>
  <p>Privacy Policy | Terms of Service</p>
  <p>Session ID: {session}</p>
  <p>Page generated {generated}</p>
  <p>{visitors} visitors online right now</p>
</footer>
"""


def _page(*, company: str, title: str, body: str, nav_extra: str = "", year: str,
          session: str, generated: str, visitors: str) -> str:
    """Assemble a full HTML document from a body plus shared chrome."""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title></head>
<body>
{_NAV.format(extra=nav_extra)}
<main>
{body}
</main>
{_FOOTER.format(company=company, year=year, session=session, generated=generated, visitors=visitors)}
</body></html>"""


# =============================== NovaStack =================================
# Story: raises Pro pricing, doubles the project limit, ships AI analytics.

_NOVASTACK_PRICING_BODY_V1 = """
<h1>Simple pricing for growing teams</h1>
<p class="subtitle">Start free. Upgrade when your team outgrows it.</p>
<section class="pricing-table">
  <div class="plan"><h3>Starter</h3><p class="price">Free</p>
    <ul><li>1 project</li><li>Community support</li><li>Basic analytics</li></ul></div>
  <div class="plan"><h3>Pro</h3><p class="price">Rs 999/month</p>
    <ul><li>5 projects</li><li>Email support</li><li>Basic analytics</li><li>10 GB storage</li></ul></div>
  <div class="plan"><h3>Enterprise</h3><p class="price">Contact sales</p>
    <ul><li>Unlimited projects</li><li>Dedicated support</li><li>SSO and audit logs</li></ul></div>
</section>
<p class="faq">All plans are billed monthly and can be cancelled at any time.</p>
"""

_NOVASTACK_PRICING_BODY_V2 = """
<h1>Simple pricing for growing teams</h1>
<p class="subtitle">Start free. Upgrade when your team outgrows it.</p>
<section class="pricing-table">
  <div class="plan"><h3>Starter</h3><p class="price">Free</p>
    <ul><li>1 project</li><li>Community support</li><li>Basic analytics</li></ul></div>
  <div class="plan"><h3>Pro</h3><p class="price">Rs 1499/month</p>
    <ul><li>10 projects</li><li>Priority email support</li><li>AI-powered analytics</li><li>25 GB storage</li></ul></div>
  <div class="plan"><h3>Enterprise</h3><p class="price">Contact sales</p>
    <ul><li>Unlimited projects</li><li>Dedicated support</li><li>SSO and audit logs</li></ul></div>
</section>
<p class="faq">All plans are billed monthly and can be cancelled at any time.</p>
"""

_NOVASTACK_PRODUCT_BODY_V1 = """
<h1>The workspace for modern engineering teams</h1>
<p>NovaStack brings your projects, docs and deployments into one place.</p>
<section class="features">
  <h2>Built for teams that ship</h2>
  <p>Track work across projects with a shared timeline.</p>
  <p>Basic analytics show you what your team shipped last week.</p>
  <p>Deploy previews for every branch.</p>
</section>
"""

_NOVASTACK_PRODUCT_BODY_V2 = """
<h1>The AI workspace for modern engineering teams</h1>
<p>NovaStack brings your projects, docs and deployments into one place.</p>
<section class="features">
  <h2>Built for teams that ship</h2>
  <p>Track work across projects with a shared timeline.</p>
  <p>Introducing NovaStack Insight: AI-powered analytics that explain why your delivery slowed down.</p>
  <p>Deploy previews for every branch.</p>
  <p>Now available: automated release notes generated from your commit history.</p>
</section>
"""

# =============================== CloudPilot =================================
# Story: hires an ML team and repositions towards enterprise.

_CLOUDPILOT_CAREERS_BODY_V1 = """
<h1>Careers at CloudPilot</h1>
<p>We are a remote-first team building infrastructure tooling.</p>
<section class="openings">
  <h2>Open roles</h2>
  <ul>
    <li>Senior Backend Engineer - Remote - Full-time</li>
    <li>Product Designer - Berlin - Full-time</li>
  </ul>
</section>
"""

_CLOUDPILOT_CAREERS_BODY_V2 = """
<h1>Careers at CloudPilot</h1>
<p>We are a remote-first team building infrastructure tooling.</p>
<section class="openings">
  <h2>Open roles</h2>
  <ul>
    <li>Senior Backend Engineer - Remote - Full-time</li>
    <li>Product Designer - Berlin - Full-time</li>
    <li>Machine Learning Engineer - Remote - Full-time</li>
    <li>Senior Machine Learning Engineer, Platform - Remote - Full-time</li>
    <li>Research Scientist, Applied ML - London - Full-time</li>
    <li>MLOps Engineer - Remote - Full-time</li>
  </ul>
</section>
"""

_CLOUDPILOT_HOME_BODY_V1 = """
<h1>Ship infrastructure without the yak shaving</h1>
<p>CloudPilot is the deployment platform built for small teams.</p>
<section class="social-proof"><p>Trusted by 4,200 developers</p></section>
<section class="cta"><p>Start free, no credit card required.</p></section>
"""

_CLOUDPILOT_HOME_BODY_V2 = """
<h1>The enterprise deployment platform for regulated teams</h1>
<p>CloudPilot is the deployment platform built for enterprise engineering organisations.</p>
<section class="social-proof"><p>Trusted by 5,100 developers</p></section>
<section class="cta"><p>Talk to our sales team about enterprise onboarding.</p></section>
"""

# ================================ DataForge =================================
# Story: launches a product and adds integrations; moves off a free tier.

_DATAFORGE_INTEGRATIONS_BODY_V1 = """
<h1>Integrations</h1>
<p>DataForge connects to the tools your data team already uses.</p>
<section class="integration-grid">
  <p>Integrates with Snowflake for warehouse sync.</p>
  <p>Integrates with Slack for alerting.</p>
  <p>REST API available for custom pipelines.</p>
</section>
"""

_DATAFORGE_INTEGRATIONS_BODY_V2 = """
<h1>Integrations</h1>
<p>DataForge connects to the tools your data team already uses.</p>
<section class="integration-grid">
  <p>Integrates with Snowflake for warehouse sync.</p>
  <p>Integrates with Slack for alerting.</p>
  <p>REST API available for custom pipelines.</p>
  <p>Now works with Databricks, dbt and Salesforce for end-to-end lineage.</p>
  <p>New: webhook connector and a Zapier plugin for no-code automation.</p>
</section>
"""

_DATAFORGE_PRICING_BODY_V1 = """
<h1>DataForge pricing</h1>
<section class="pricing-table">
  <div class="plan"><h3>Free</h3><p class="price">$0</p>
    <ul><li>1 workspace</li><li>100 requests per day</li></ul></div>
  <div class="plan"><h3>Team</h3><p class="price">$49 per month</p>
    <ul><li>5 workspaces</li><li>Unlimited requests</li></ul></div>
</section>
"""

_DATAFORGE_PRICING_BODY_V2 = """
<h1>DataForge pricing</h1>
<section class="pricing-table">
  <div class="plan"><h3>Developer</h3><p class="price">$19 per month</p>
    <ul><li>1 workspace</li><li>100 requests per day</li></ul></div>
  <div class="plan"><h3>Team</h3><p class="price">$79 per month</p>
    <ul><li>5 workspaces</li><li>Unlimited requests</li></ul></div>
</section>
<p>Launching DataForge Lineage, our new product for automated data lineage mapping.</p>
"""


# --- Page registry ----------------------------------------------------------
# (competitor, url path, label, page_type, body_v1, body_v2)

_PAGES: list[tuple[str, str, str, str, str, str]] = [
    ("NovaStack", "/pricing", "Pricing", "pricing", _NOVASTACK_PRICING_BODY_V1, _NOVASTACK_PRICING_BODY_V2),
    ("NovaStack", "/product", "Product", "product", _NOVASTACK_PRODUCT_BODY_V1, _NOVASTACK_PRODUCT_BODY_V2),
    ("CloudPilot", "/careers", "Careers", "careers", _CLOUDPILOT_CAREERS_BODY_V1, _CLOUDPILOT_CAREERS_BODY_V2),
    ("CloudPilot", "/", "Homepage", "generic", _CLOUDPILOT_HOME_BODY_V1, _CLOUDPILOT_HOME_BODY_V2),
    ("DataForge", "/integrations", "Integrations", "integrations", _DATAFORGE_INTEGRATIONS_BODY_V1, _DATAFORGE_INTEGRATIONS_BODY_V2),
    ("DataForge", "/pricing", "Pricing", "pricing", _DATAFORGE_PRICING_BODY_V1, _DATAFORGE_PRICING_BODY_V2),
]

# Noise that differs between the two revisions but means nothing.
_CHROME_V1 = {
    "year": "2025",
    "session": "8f14e45f-ceea-467a-9a1e-4b2d3c9f0011",
    "generated": "2026-09-05T08:14:22Z",
    "visitors": "213",
    "nav_extra": "",
}
_CHROME_V2 = {
    "year": "2026",
    "session": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    "generated": "2026-09-19T11:47:03Z",
    "visitors": "438",
    "nav_extra": '<a href="/blog">Blog</a>',
}

COMPETITORS: list[dict] = [
    {
        "name": "NovaStack",
        "website_url": "https://novastack.example.com",
        "description": "Fictional engineering workspace used for the RivalRadar demo.",
        "tracking_frequency": "daily",
    },
    {
        "name": "CloudPilot",
        "website_url": "https://cloudpilot.example.com",
        "description": "Fictional deployment platform used for the RivalRadar demo.",
        "tracking_frequency": "daily",
    },
    {
        "name": "DataForge",
        "website_url": "https://dataforge.example.com",
        "description": "Fictional data-tooling company used for the RivalRadar demo.",
        "tracking_frequency": "weekly",
    },
]

_BASE_URLS = {entry["name"]: entry["website_url"] for entry in COMPETITORS}


def tracked_pages() -> list[dict]:
    """Return every demo page with both revisions rendered as full HTML."""
    pages: list[dict] = []
    for company, path, label, page_type, body_v1, body_v2 in _PAGES:
        base = _BASE_URLS[company].rstrip("/")
        title = f"{company} {label}"
        pages.append(
            {
                "competitor": company,
                "url": f"{base}{path}",
                "label": label,
                "page_type": page_type,
                "v1": _page(company=company, title=title, body=body_v1, **_CHROME_V1),
                "v2": _page(company=company, title=title, body=body_v2, **_CHROME_V2),
            }
        )
    return pages


def demo_html_for(url: str) -> str | None:
    """Return the current demo revision for a demo URL, else ``None``.

    The demo competitors use fictional ``*.example.com`` domains that do not
    resolve, so a live scan of them would only ever report DNS failures.  This
    lookup lets ``rivalradar scan`` serve their fixture content instead, which
    exercises the real snapshot/diff path end to end without inventing a
    network request.  Only these exact seeded URLs are ever matched.
    """
    for page in tracked_pages():
        if page["url"] == url:
            return page["v2"]
    return None


def is_demo_url(url: str) -> bool:
    """True when ``url`` is one of the seeded demo pages."""
    return demo_html_for(url) is not None


# Names and hosts belonging to the fictional demo set.
_DEMO_NAMES = frozenset(entry["name"].casefold() for entry in COMPETITORS)
_DEMO_HOSTS = frozenset(
    entry["website_url"].split("://", 1)[-1].strip("/").casefold() for entry in COMPETITORS
)


def is_demo_competitor(name: str, website_url: str = "") -> bool:
    """True when a competitor is one of the seeded fictional demo companies.

    The API surfaces this so the dashboard can label demo rows explicitly.
    Fictional data must never be presented as real competitive intelligence.
    """
    if name and name.casefold() in _DEMO_NAMES:
        return True
    host = (website_url or "").split("://", 1)[-1].strip("/").casefold()
    return bool(host) and host in _DEMO_HOSTS
