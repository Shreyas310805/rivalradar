"""Request and response models for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.models.entities import TrackingFrequency
from app.redaction import redact_secrets
from app.scrapers.url_guard import UnsafeURLError, validate_url

_ORM = ConfigDict(from_attributes=True)

# Error text that may have come from an exception. Redacted when serialised,
# so rows written before the redaction fix cannot leak a credential either.
RedactedStr = Annotated[str, PlainSerializer(redact_secrets, return_type=str)]


def _validate_public_url(value: str) -> str:
    """Shared validator: URLs must be public http(s) endpoints.

    DNS resolution failures are tolerated here (``strict_dns=False``) so a
    competitor is not rejected because DNS is momentarily unavailable.  The
    fetcher re-validates with strict DNS before any request is issued, so an
    unresolvable host still never reaches the network.
    """
    try:
        return validate_url(value, strict_dns=False)
    except UnsafeURLError as exc:
        raise ValueError(str(exc)) from exc


# --- Tracked URLs -----------------------------------------------------------


class TrackedURLCreate(BaseModel):
    """Payload for adding a page to a competitor."""

    url: str = Field(min_length=3, max_length=2048)
    label: str | None = Field(default=None, max_length=120)
    page_type: str | None = Field(default=None, max_length=40)
    render_js: bool = False
    active: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return _validate_public_url(value)


class TrackedURLUpdate(BaseModel):
    """Partial update for a tracked page."""

    label: str | None = Field(default=None, max_length=120)
    page_type: str | None = Field(default=None, max_length=40)
    render_js: bool | None = None
    active: bool | None = None


class TrackedURLRead(BaseModel):
    model_config = _ORM

    id: int
    competitor_id: int
    url: str
    label: str | None = None
    page_type: str = "generic"
    render_js: bool = False
    active: bool = True
    last_checked: datetime | None = None
    last_status: str | None = None
    last_error: RedactedStr | None = None
    created_at: datetime


# --- Competitors ------------------------------------------------------------


class CompetitorCreate(BaseModel):
    """Payload for creating a competitor."""

    name: str = Field(min_length=1, max_length=200)
    website_url: str = Field(min_length=3, max_length=2048)
    description: str | None = Field(default=None, max_length=2000)
    tracking_frequency: TrackingFrequency = TrackingFrequency.DAILY
    active: bool = True
    tracked_urls: list[TrackedURLCreate] = Field(default_factory=list)

    @field_validator("website_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return _validate_public_url(value)


class CompetitorUpdate(BaseModel):
    """Partial update for a competitor."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    website_url: str | None = Field(default=None, min_length=3, max_length=2048)
    description: str | None = Field(default=None, max_length=2000)
    tracking_frequency: TrackingFrequency | None = None
    active: bool | None = None

    @field_validator("website_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        return _validate_public_url(value) if value else value


class CompetitorRead(BaseModel):
    model_config = _ORM

    id: int
    name: str
    website_url: str
    description: str | None = None
    tracking_frequency: str
    active: bool
    created_at: datetime
    updated_at: datetime
    tracked_urls: list[TrackedURLRead] = Field(default_factory=list)


class CompetitorSummary(CompetitorRead):
    """Competitor plus rolled-up activity counters for the dashboard."""

    # True for the seeded fictional companies, so the UI can label them DEMO
    # and never present invented data as real competitive intelligence.
    is_demo: bool = False
    tracked_url_count: int = 0
    last_scan: datetime | None = None
    changes_this_week: int = 0
    high_impact_this_week: int = 0
    total_changes: int = 0


# --- Changes and intelligence ----------------------------------------------


class IntelligenceRead(BaseModel):
    model_config = _ORM

    id: int
    change_id: int
    competitor_id: int
    title: str
    category: str
    summary: str
    before: str | None = None
    after: str | None = None
    business_impact: str
    recommended_action: str | None = None
    relevance_score: float
    severity: str
    confidence: float
    analysed_by: str
    # What actually produced this record. The stored llm_error is deliberately
    # not exposed: the UI needs only the status, and error text is diagnostics.
    llm_status: str = "skipped"
    llm_model: str | None = None
    # Traceability: the exact evidence behind the record.
    tracked_url_id: int | None = None
    snapshot_id: int | None = None
    previous_snapshot_id: int | None = None
    source_url: str = ""
    created_at: datetime


class ChangeRead(BaseModel):
    model_config = _ORM

    id: int
    snapshot_id: int
    previous_snapshot_id: int | None = None
    competitor_id: int
    change_type: str
    category: str
    location: str
    before: str | None = None
    after: str | None = None
    magnitude: float
    is_noise: bool
    noise_reason: str | None = None
    relevance_score: float
    severity: str
    classifier_confidence: float
    detected_at: datetime
    source_url: str


class DiffSegment(BaseModel):
    """One word-level segment for the before/after comparison UI."""

    op: str
    before: str = ""
    after: str = ""


class ChangeDetail(ChangeRead):
    """A change plus its analysis, competitor name and word-level diff."""

    competitor_name: str = ""
    intelligence: IntelligenceRead | None = None
    diff_segments: list[DiffSegment] = Field(default_factory=list)


class IntelligenceItem(IntelligenceRead):
    """Intelligence enriched with competitor and source context.

    ``source_url`` is inherited from :class:`IntelligenceRead`, which now
    stores it directly on the record for traceability.
    """

    competitor_name: str = ""
    change_type: str = ""
    location: str = ""


# --- Scans ------------------------------------------------------------------


class ScanStats(BaseModel):
    """The noise-reduction funnel for one scan."""

    raw_changes: int = 0
    noise_changes: int = 0
    meaningful_changes: int = 0
    high_impact_changes: int = 0
    noise_reduction: float = 0.0


class ScanURLResult(BaseModel):
    """Per-page outcome within a scan."""

    url: str
    status: str
    message: RedactedStr | None = None
    stats: ScanStats = Field(default_factory=ScanStats)


class ScanResponse(BaseModel):
    """Result of scanning one competitor."""

    scan_run_id: int | None = None
    competitor_id: int
    competitor_name: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    urls_scanned: int = 0
    urls_failed: int = 0
    stats: ScanStats = Field(default_factory=ScanStats)
    results: list[ScanURLResult] = Field(default_factory=list)
    intelligence: list[IntelligenceRead] = Field(default_factory=list)
    errors: list[RedactedStr] = Field(default_factory=list)


class ScanRunRead(BaseModel):
    model_config = _ORM

    id: int
    competitor_id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    urls_scanned: int
    urls_failed: int
    raw_changes: int
    noise_changes: int
    meaningful_changes: int
    high_impact_changes: int
    noise_reduction: float
    error: RedactedStr | None = None


# --- Digest -----------------------------------------------------------------


class DigestRead(BaseModel):
    model_config = _ORM

    id: int
    period_start: datetime
    period_end: datetime
    title: str
    content: str
    headline: str | None = None
    raw_changes: int
    noise_changes: int
    meaningful_changes: int
    high_impact_changes: int
    noise_reduction: float
    generated_by: str
    created_at: datetime


class DigestGenerateRequest(BaseModel):
    """Options for generating a digest."""

    days: int = Field(default=7, ge=1, le=90)
    competitor_id: int | None = None


# --- Evaluation -------------------------------------------------------------


class WaybackRequest(BaseModel):
    """Options for a Wayback Machine evaluation run."""

    url: str = Field(min_length=3, max_length=2048)
    from_date: str | None = Field(default=None, description="YYYY-MM-DD")
    to_date: str | None = Field(default=None, description="YYYY-MM-DD")
    limit: int = Field(default=2, ge=2, le=12)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return _validate_public_url(value)


class EvaluationRead(BaseModel):
    model_config = _ORM

    id: int
    kind: str
    target_url: str
    snapshot_a: str | None = None
    snapshot_b: str | None = None
    pages_evaluated: int
    raw_changes: int
    noise_changes: int
    meaningful_changes: int
    high_impact_changes: int
    noise_reduction: float
    category_breakdown: str
    report_path: str | None = None
    status: str
    error: RedactedStr | None = None
    created_at: datetime


# --- Analytics --------------------------------------------------------------


class CategoryCount(BaseModel):
    category: str
    count: int


class TimelinePoint(BaseModel):
    date: str
    raw_changes: int = 0
    meaningful_changes: int = 0
    high_impact_changes: int = 0


class NoiseReasonCount(BaseModel):
    reason: str
    count: int


class DashboardStats(BaseModel):
    """Everything the dashboard landing page needs in one call."""

    tracked_competitors: int = 0
    active_competitors: int = 0
    tracked_urls: int = 0
    total_snapshots: int = 0
    raw_changes: int = 0
    noise_changes: int = 0
    meaningful_changes: int = 0
    high_impact_changes: int = 0
    noise_reduction: float = 0.0
    changes_this_week: int = 0
    high_impact_this_week: int = 0
    last_scan: datetime | None = None
    # Analyst description — never claims an LLM ran when one did not.
    llm_provider: str = "deterministic"
    llm_model: str = ""
    llm_is_llm: bool = False
    llm_label: str = "Deterministic"
    llm_configured: bool = False
    llm_last_status: str | None = None
    demo_mode: bool = False


class AnalyticsResponse(BaseModel):
    """Aggregates for the analytics page."""

    stats: DashboardStats
    categories: list[CategoryCount] = Field(default_factory=list)
    timeline: list[TimelinePoint] = Field(default_factory=list)
    noise_reasons: list[NoiseReasonCount] = Field(default_factory=list)
    severity_distribution: list[CategoryCount] = Field(default_factory=list)
    top_competitors: list[dict] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Uniform error body."""

    detail: str
    code: str = "error"
