"""Pydantic contracts for LLM output.

Raw model output is never trusted.  Every response is parsed into one of these
models; anything that fails validation is discarded and the deterministic
fallback is used instead.  Fields are deliberately forgiving about *type*
(scores arrive as strings surprisingly often) but strict about *range*.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.entities import ChangeCategory

_VALID_CATEGORIES = {c.value for c in ChangeCategory}


class ChangeAnalysis(BaseModel):
    """Structured competitive analysis of a single detected change."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    # The model's own verdict on whether this change is worth a founder's
    # attention. Defaults to True so a model that omits the field does not
    # silently suppress a change the deterministic layer already kept.
    is_meaningful: bool = True
    title: str = Field(min_length=3, max_length=300)
    category: str = ChangeCategory.OTHER.value
    summary: str = Field(default="", max_length=2000)
    before: str | None = Field(default=None, max_length=1200)
    after: str | None = Field(default=None, max_length=1200)
    business_impact: str = Field(default="", max_length=2000)
    recommended_action: str | None = Field(default=None, max_length=1000)
    relevance_score: float = Field(default=50.0, ge=0.0, le=100.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, value: object) -> str:
        """Map free-text categories onto the known enum, defaulting to other."""
        text = str(value or "").strip().casefold()
        if text in _VALID_CATEGORIES:
            return text
        aliases = {
            "price": ChangeCategory.PRICING.value,
            "prices": ChangeCategory.PRICING.value,
            "feature": ChangeCategory.FEATURES.value,
            "hiring_signal": ChangeCategory.HIRING.value,
            "jobs": ChangeCategory.HIRING.value,
            "recruiting": ChangeCategory.HIRING.value,
            "integration": ChangeCategory.INTEGRATIONS.value,
            "partnership": ChangeCategory.INTEGRATIONS.value,
            "partnerships": ChangeCategory.INTEGRATIONS.value,
            "positioning": ChangeCategory.MESSAGING.value,
            "marketing": ChangeCategory.MESSAGING.value,
            "copy": ChangeCategory.MESSAGING.value,
            "products": ChangeCategory.PRODUCT.value,
            "launch": ChangeCategory.PRODUCT.value,
        }
        return aliases.get(text, ChangeCategory.OTHER.value)

    @field_validator("relevance_score", mode="before")
    @classmethod
    def _coerce_score(cls, value: object) -> float:
        """Accept 0-100, 0-1 floats, and strings like '91%' or 'high'."""
        if value is None:
            return 50.0
        if isinstance(value, (int, float)):
            score = float(value)
        else:
            text = str(value).strip().rstrip("%")
            words = {"noise": 15.0, "low": 40.0, "medium": 60.0, "high": 78.0, "critical": 92.0}
            if text.casefold() in words:
                return words[text.casefold()]
            match = re.search(r"-?\d+(?:\.\d+)?", text)
            if not match:
                return 50.0
            score = float(match.group(0))
        # A model answering on a 0-1 scale is a common failure mode.
        if 0.0 < score <= 1.0:
            score *= 100.0
        return max(0.0, min(100.0, score))

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        """Accept 0-1, 0-100 and percentage strings."""
        if value is None:
            return 0.5
        if isinstance(value, (int, float)):
            conf = float(value)
        else:
            match = re.search(r"-?\d+(?:\.\d+)?", str(value))
            if not match:
                return 0.5
            conf = float(match.group(0))
        if conf > 1.0:
            conf /= 100.0
        return max(0.0, min(1.0, conf))

    @field_validator("is_meaningful", mode="before")
    @classmethod
    def _coerce_bool(cls, value: object) -> bool:
        """Accept true/false, "yes"/"no", 1/0 and null."""
        if value is None:
            return True
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().casefold() in {"true", "yes", "y", "1", "meaningful"}

    @field_validator("title", "summary", "business_impact", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> str:
        """Flatten lists and None into plain strings."""
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value)
        return str(value)


class DigestHighlight(BaseModel):
    """One numbered entry in a weekly digest."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    competitor: str = Field(default="Unknown", max_length=200)
    category: str = ChangeCategory.OTHER.value
    headline: str = Field(default="", max_length=300)
    detail: str = Field(default="", max_length=1000)
    impact: str = Field(default="", max_length=1000)

    _coerce_category = field_validator("category", mode="before")(
        ChangeAnalysis._coerce_category.__func__  # type: ignore[attr-defined]
    )


class DigestNarrative(BaseModel):
    """LLM-authored prose portion of a weekly digest."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    headline: str = Field(default="", max_length=500)
    highlights: list[DigestHighlight] = Field(default_factory=list)
    outlook: str = Field(default="", max_length=2000)

    @field_validator("highlights", mode="before")
    @classmethod
    def _coerce_highlights(cls, value: object) -> list:
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []
