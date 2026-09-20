"""SQLAlchemy ORM entities for RivalRadar.

Schema overview::

    Competitor 1--* TrackedURL 1--* Snapshot 1--* Change 1--1 Intelligence
    ScanRun    *--1 Competitor
    Digest     (standalone, period-scoped)
    Evaluation (standalone, Wayback experiment results)
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, utcnow

__all__ = [
    "Base",
    "Competitor",
    "TrackedURL",
    "Snapshot",
    "Change",
    "Intelligence",
    "Digest",
    "ScanRun",
    "Evaluation",
    "TrackingFrequency",
    "ChangeType",
    "ChangeCategory",
    "Severity",
]


class TrackingFrequency(str, enum.Enum):
    """How often a competitor should be re-scanned."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"

    @property
    def minutes(self) -> int:
        return {
            TrackingFrequency.HOURLY: 60,
            TrackingFrequency.DAILY: 60 * 24,
            TrackingFrequency.WEEKLY: 60 * 24 * 7,
            TrackingFrequency.MANUAL: 0,
        }[self]


class ChangeType(str, enum.Enum):
    """Structural nature of a detected difference."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    TEXT_CHANGE = "text_change"
    PRICE_CHANGE = "price_change"
    FEATURE_CHANGE = "feature_change"
    HEADLINE_CHANGE = "headline_change"
    PRODUCT_CHANGE = "product_change"
    HIRING_SIGNAL = "hiring_signal"
    INTEGRATION_CHANGE = "integration_change"


class ChangeCategory(str, enum.Enum):
    """Business-facing bucket used for reporting and analytics."""

    PRICING = "pricing"
    FEATURES = "features"
    PRODUCT = "product"
    HIRING = "hiring"
    INTEGRATIONS = "integrations"
    MESSAGING = "messaging"
    OTHER = "other"


class Severity(str, enum.Enum):
    """Relevance band derived from the numeric relevance score."""

    NOISE = "noise"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: float) -> Severity:
        """Map a 0-100 relevance score onto a severity band."""
        if score < 30:
            return cls.NOISE
        if score < 50:
            return cls.LOW
        if score < 70:
            return cls.MEDIUM
        if score < 85:
            return cls.HIGH
        return cls.CRITICAL


class Competitor(Base):
    """A company being tracked."""

    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    website_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tracking_frequency: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TrackingFrequency.DAILY.value
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    tracked_urls: Mapped[list[TrackedURL]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan", lazy="selectin"
    )
    scan_runs: Mapped[list[ScanRun]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )


class TrackedURL(Base):
    """A specific page of a competitor, not merely the domain."""

    __tablename__ = "tracked_urls"
    __table_args__ = (
        UniqueConstraint("competitor_id", "url", name="uq_tracked_url_per_competitor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    page_type: Mapped[str] = mapped_column(String(40), nullable=False, default="generic")
    render_js: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    competitor: Mapped[Competitor] = relationship(back_populates="tracked_urls")
    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="tracked_url", cascade="all, delete-orphan"
    )


class Snapshot(Base):
    """A point-in-time capture of a tracked page."""

    __tablename__ = "snapshots"
    __table_args__ = (Index("ix_snapshot_url_time", "tracked_url_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracked_url_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_urls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    status_code: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_html_path: Mapped[str | None] = mapped_column(String(1024))
    raw_html: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str | None] = mapped_column(String(512))
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetch_duration_ms: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="live")

    tracked_url: Mapped[TrackedURL] = relationship(back_populates="snapshots")
    changes: Mapped[list[Change]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        foreign_keys="Change.snapshot_id",
    )


class Change(Base):
    """A single detected difference between two snapshots."""

    __tablename__ = "changes"
    __table_args__ = (Index("ix_change_noise_score", "is_noise", "relevance_score"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL")
    )
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default=ChangeType.MODIFIED.value
    )
    category: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ChangeCategory.OTHER.value
    )
    location: Mapped[str] = mapped_column(String(120), nullable=False, default="body")
    before: Mapped[str | None] = mapped_column(Text)
    after: Mapped[str | None] = mapped_column(Text)
    magnitude: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_noise: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    noise_reason: Mapped[str | None] = mapped_column(String(200))
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default=Severity.NOISE.value)
    classifier_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")

    snapshot: Mapped[Snapshot] = relationship(
        back_populates="changes", foreign_keys=[snapshot_id]
    )
    intelligence: Mapped[Intelligence | None] = relationship(
        back_populates="change", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class Intelligence(Base):
    """Business-facing interpretation of a change, validated from LLM output."""

    __tablename__ = "intelligence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("changes.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ChangeCategory.OTHER.value
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    before: Mapped[str | None] = mapped_column(Text)
    after: Mapped[str | None] = mapped_column(Text)
    business_impact: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommended_action: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default=Severity.LOW.value)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    analysed_by: Mapped[str] = mapped_column(String(40), nullable=False, default="deterministic")

    # What actually happened when this record was produced:
    # ok | skipped | failed | rate_limited | budget.  Never claim an LLM ran
    # when it did not.
    llm_status: Mapped[str] = mapped_column(String(20), nullable=False, default="skipped")
    llm_error: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(String(120))

    # --- Traceability -------------------------------------------------------
    # Every record points back at the exact evidence it came from, so the UI
    # can offer "View source" and "View comparison".
    tracked_url_id: Mapped[int | None] = mapped_column(
        ForeignKey("tracked_urls.id", ondelete="SET NULL"), index=True
    )
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL")
    )
    previous_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL")
    )
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )

    change: Mapped[Change] = relationship(back_populates="intelligence")


class Digest(Base):
    """A generated weekly competitive-intelligence report."""

    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    title: Mapped[str] = mapped_column(
        String(300), nullable=False, default="Weekly Competitive Intelligence"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    headline: Mapped[str | None] = mapped_column(Text)
    raw_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noise_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meaningful_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_impact_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noise_reduction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    generated_by: Mapped[str] = mapped_column(String(40), nullable=False, default="heuristic")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )


class ScanRun(Base):
    """Audit record for one scan of one competitor."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    urls_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noise_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meaningful_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_impact_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noise_reduction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)

    competitor: Mapped[Competitor] = relationship(back_populates="scan_runs")


class Evaluation(Base):
    """Results of a Wayback Machine benchmark run."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="wayback")
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    snapshot_a: Mapped[str | None] = mapped_column(String(40))
    snapshot_b: Mapped[str | None] = mapped_column(String(40))
    pages_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noise_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meaningful_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_impact_changes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noise_reduction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    category_breakdown: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    report_path: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
