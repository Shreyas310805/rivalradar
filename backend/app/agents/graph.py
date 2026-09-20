"""The RivalRadar LangGraph pipeline.

::

    START
      -> fetch_snapshot
      -> normalize
      -> diff                (skipped when the content hash is unchanged)
      -> filter_noise
      -> classify
      -> calculate_relevance
      -> llm_analysis        (only for candidates scoring >= LLM_MIN_RELEVANCE)
      -> validate_output     (Pydantic + grounding check; drops invented output)
      -> generate_intelligence
      -> store_result
      -> END

A conditional edge after ``fetch_snapshot`` short-circuits straight to
``store_result`` when there is nothing to compare, so an unchanged page costs
one hash comparison and zero tokens.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    calculate_relevance,
    classify,
    diff_snapshots,
    fetch_snapshot,
    filter_noise_node,
    generate_intelligence,
    llm_analysis,
    normalize,
    store_result,
    validate_output,
)
from app.agents.state import RivalRadarState, new_state
from app.config.logging import get_logger

logger = get_logger(__name__)


def _route_after_fetch(state: dict) -> str:
    """Skip the expensive middle of the graph when there is nothing to diff."""
    return "store_result" if state.get("skipped") else "normalize"


def build_graph() -> Any:
    """Construct and compile the intelligence graph."""
    graph = StateGraph(RivalRadarState)

    graph.add_node("fetch_snapshot", fetch_snapshot)
    graph.add_node("normalize", normalize)
    graph.add_node("diff", diff_snapshots)
    graph.add_node("filter_noise", filter_noise_node)
    graph.add_node("classify", classify)
    graph.add_node("calculate_relevance", calculate_relevance)
    graph.add_node("llm_analysis", llm_analysis)
    graph.add_node("validate_output", validate_output)
    graph.add_node("generate_intelligence", generate_intelligence)
    graph.add_node("store_result", store_result)

    graph.add_edge(START, "fetch_snapshot")
    graph.add_conditional_edges(
        "fetch_snapshot",
        _route_after_fetch,
        {"normalize": "normalize", "store_result": "store_result"},
    )
    graph.add_edge("normalize", "diff")
    graph.add_edge("diff", "filter_noise")
    graph.add_edge("filter_noise", "classify")
    graph.add_edge("classify", "calculate_relevance")
    graph.add_edge("calculate_relevance", "llm_analysis")
    graph.add_edge("llm_analysis", "validate_output")
    graph.add_edge("validate_output", "generate_intelligence")
    graph.add_edge("generate_intelligence", "store_result")
    graph.add_edge("store_result", END)

    return graph.compile()


@lru_cache(maxsize=1)
def get_graph() -> Any:
    """Return the compiled graph singleton (compilation is not free)."""
    logger.debug("Compiling RivalRadar intelligence graph")
    return build_graph()


def run_pipeline(
    competitor: dict,
    tracked_url: dict,
    current_snapshot: dict,
    previous_snapshot: dict | None,
    *,
    llm_enabled: bool = True,
    analysis_limit: int = 25,
) -> dict:
    """Run the full intelligence pipeline for one page comparison.

    Returns the final graph state, including ``stats``, ``intelligence`` and
    the full annotated ``classified_changes`` funnel.
    """
    state = new_state(
        competitor,
        tracked_url,
        current_snapshot=current_snapshot,
        previous_snapshot=previous_snapshot,
        llm_enabled=llm_enabled,
        analysis_limit=analysis_limit,
    )
    graph = get_graph()
    try:
        return dict(graph.invoke(state))
    except Exception as exc:  # noqa: BLE001 - the graph must never crash a scan
        logger.error("Intelligence graph failed for %s", tracked_url.get("url"), exc_info=True)
        failed = dict(state)
        failed["errors"] = [*failed.get("errors", []), f"graph: {exc}"]
        failed["stats"] = {
            "raw_changes": 0,
            "noise_changes": 0,
            "meaningful_changes": 0,
            "high_impact_changes": 0,
            "noise_reduction": 0.0,
        }
        return failed


def render_mermaid() -> str:
    """Return a Mermaid diagram of the graph, for the README and docs."""
    try:
        return get_graph().get_graph().draw_mermaid()
    except Exception:  # pragma: no cover - drawing is best effort
        logger.debug("Could not render graph diagram", exc_info=True)
        return ""
