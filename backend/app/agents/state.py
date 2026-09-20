"""LangGraph state for the RivalRadar intelligence pipeline."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _replace(_old: Any, new: Any) -> Any:
    """Reducer: later writes win (nodes own their slice of state)."""
    return new


def _extend(old: list | None, new: list | None) -> list:
    """Reducer: accumulate list fragments across nodes."""
    return [*(old or []), *(new or [])]


class RivalRadarState(TypedDict, total=False):
    """State threaded through the intelligence graph.

    Populated progressively:

    ``fetch_snapshot``    -> current_snapshot, previous_snapshot
    ``normalize``         -> normalized_before, normalized_after
    ``diff``              -> raw_changes
    ``filter_noise``      -> filtered_changes (annotated), noise_reasons
    ``classify``          -> classified_changes
    ``score_relevance``   -> important_changes
    ``llm_analysis``      -> analyses, llm_calls, llm_status
    ``validate_output``   -> analyses (validated), rejected_analyses
    ``generate_intelligence`` -> intelligence
    ``store_result``      -> stats, persisted_ids
    """

    # --- Inputs ---
    competitor: Annotated[dict, _replace]
    tracked_url: Annotated[dict, _replace]

    # --- Snapshots ---
    current_snapshot: Annotated[dict, _replace]
    previous_snapshot: Annotated[dict | None, _replace]
    normalized_before: Annotated[str, _replace]
    normalized_after: Annotated[str, _replace]

    # --- Change funnel ---
    raw_changes: Annotated[list[dict], _replace]
    filtered_changes: Annotated[list[dict], _replace]
    classified_changes: Annotated[list[dict], _replace]
    important_changes: Annotated[list[dict], _replace]

    # --- Output ---
    analyses: Annotated[list[dict], _replace]
    intelligence: Annotated[list[dict], _replace]
    persisted_ids: Annotated[list[int], _extend]

    # --- Metrics and control ---
    stats: Annotated[dict, _replace]
    noise_reasons: Annotated[dict, _replace]
    skipped: Annotated[bool, _replace]
    skip_reason: Annotated[str | None, _replace]
    errors: Annotated[list[str], _extend]
    llm_enabled: Annotated[bool, _replace]
    analysis_limit: Annotated[int, _replace]
    llm_calls: Annotated[int, _replace]
    llm_status: Annotated[str, _replace]
    rejected_analyses: Annotated[int, _replace]


def new_state(competitor: dict, tracked_url: dict, **overrides: Any) -> RivalRadarState:
    """Build an initial state with safe defaults."""
    state: RivalRadarState = {
        "competitor": competitor,
        "tracked_url": tracked_url,
        "previous_snapshot": None,
        "raw_changes": [],
        "filtered_changes": [],
        "classified_changes": [],
        "important_changes": [],
        "analyses": [],
        "intelligence": [],
        "persisted_ids": [],
        "stats": {},
        "noise_reasons": {},
        "skipped": False,
        "skip_reason": None,
        "errors": [],
        "llm_enabled": True,
        "analysis_limit": None,
        "llm_calls": 0,
        "llm_status": "skipped",
        "rejected_analyses": 0,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state
