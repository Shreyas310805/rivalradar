"""Shared value objects for the diff and intelligence pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.entities import ChangeCategory, ChangeType, Severity


@dataclass(slots=True)
class DetectedChange:
    """A single difference found between two snapshots.

    The same object flows through the whole pipeline, accumulating annotations:
    the diff engine sets the structural fields, the noise filter sets
    ``is_noise``/``noise_reason``, the classifier sets ``category`` and
    ``change_type``, and the scorer sets ``relevance_score``/``severity``.
    """

    change_type: str = ChangeType.MODIFIED.value
    location: str = "body"
    before: str = ""
    after: str = ""
    magnitude: float = 0.0
    category: str = ChangeCategory.OTHER.value
    is_noise: bool = False
    noise_reason: str | None = None
    relevance_score: float = 0.0
    severity: str = Severity.NOISE.value
    classifier_confidence: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self) -> dict[str, object]:
        """Plain-dict form used by the LangGraph state and the API layer."""
        return {
            "type": self.change_type,
            "change_type": self.change_type,
            "location": self.location,
            "before": self.before,
            "after": self.after,
            "magnitude": round(self.magnitude, 4),
            "category": self.category,
            "is_noise": self.is_noise,
            "noise_reason": self.noise_reason,
            "relevance_score": round(self.relevance_score, 2),
            "severity": self.severity,
            "classifier_confidence": round(self.classifier_confidence, 3),
            "signals": {k: round(v, 3) for k, v in self.signals.items()},
            "evidence": list(self.evidence),
            "source_url": self.source_url,
        }

    @property
    def is_high_impact(self) -> bool:
        """High-impact means relevance >= 70 (the HIGH and CRITICAL bands)."""
        return (not self.is_noise) and self.relevance_score >= 70.0


@dataclass(slots=True)
class DiffStats:
    """Funnel counters for one comparison.

    These are the numbers behind the headline noise-reduction metric, and they
    are only ever produced by counting real pipeline output.
    """

    raw_changes: int = 0
    noise_changes: int = 0
    meaningful_changes: int = 0
    high_impact_changes: int = 0

    @property
    def noise_reduction(self) -> float:
        """Percentage of raw changes discarded as noise."""
        if self.raw_changes <= 0:
            return 0.0
        return round(self.noise_changes / self.raw_changes * 100.0, 2)

    def merge(self, other: DiffStats) -> DiffStats:
        """Combine two funnels (used when aggregating across pages)."""
        return DiffStats(
            raw_changes=self.raw_changes + other.raw_changes,
            noise_changes=self.noise_changes + other.noise_changes,
            meaningful_changes=self.meaningful_changes + other.meaningful_changes,
            high_impact_changes=self.high_impact_changes + other.high_impact_changes,
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "raw_changes": self.raw_changes,
            "noise_changes": self.noise_changes,
            "meaningful_changes": self.meaningful_changes,
            "high_impact_changes": self.high_impact_changes,
            "noise_reduction": self.noise_reduction,
        }

    @classmethod
    def from_changes(cls, changes: list[DetectedChange]) -> DiffStats:
        """Derive the funnel directly from a list of annotated changes."""
        noise = sum(1 for c in changes if c.is_noise)
        meaningful = len(changes) - noise
        high = sum(1 for c in changes if c.is_high_impact)
        return cls(
            raw_changes=len(changes),
            noise_changes=noise,
            meaningful_changes=meaningful,
            high_impact_changes=high,
        )
