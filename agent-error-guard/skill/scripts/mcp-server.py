from __future__ import annotations

import json
import importlib.util
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP


SCRIPT_DIR = Path(__file__).resolve().parent
RISK_AGENT_PATH = SCRIPT_DIR / "risk-agent.py"
SPEC = importlib.util.spec_from_file_location("wifi_error_guard_risk_agent", RISK_AGENT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load risk agent: {RISK_AGENT_PATH}")
risk_agent = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = risk_agent
SPEC.loader.exec_module(risk_agent)


mcp = FastMCP(
    "agent-error-guard",
    instructions=(
        "Proactive local risk recommendations for coding-agent work. "
        "The host profile is explicit-refresh only; recommendations are offline."
    ),
)


@mcp.tool()
def recommend(task: str, cwd: str = "", limit: int = 0) -> str:
    """Rank likely and harmful local errors for the current task."""
    items = risk_agent.recommend(
        task,
        cwd or os.getcwd(),
        limit=limit or None,
    )
    return risk_agent.compact_context(items, "MCP recommendation")


@mcp.tool()
def explain(error_id: str, task: str = "", cwd: str = "") -> str:
    """Return the score components and full record for one ranked error ID."""
    matches = [
        row
        for row in risk_agent.recommend(task, cwd or os.getcwd(), limit=1000)
        if row["id"] == error_id
    ]
    if not matches:
        raise ValueError(f"Unknown risk ID: {error_id}")
    item = matches[0]
    result = {
        key: item[key]
        for key in (
            "id",
            "score",
            "probability",
            "harm",
            "similarity",
            "environment_match",
            "metric_samples",
            "metric_confidence",
            "observed_trigger_rate",
            "correction_rate",
            "repeat_rate",
            "solution_rate",
            "basic_solution",
            "layer",
            "impact",
            "forbidden",
        )
    }
    if item["record"]:
        path = risk_agent.SKILL_ROOT / item["record"]
        result["record"] = path.read_text(encoding="utf-8")
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_profile() -> str:
    """Read the cached host profile without scanning the host."""
    return json.dumps(
        risk_agent.read_json(risk_agent.PROFILE_PATH, {"profile_exists": False}),
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def refresh_profile(
    workspaces: list[str] | None = None,
    confirm_explicit_refresh: bool = False,
) -> str:
    """Explicitly refresh the host toolchain profile once."""
    if not confirm_explicit_refresh:
        raise ValueError(
            "Set confirm_explicit_refresh=true only after the user requests a "
            "profile refresh or confirms that the host toolchain changed."
        )
    return json.dumps(
        risk_agent.create_profile(workspaces or []),
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def configure(
    top_k: int = 0,
    session_top_k: int = 0,
    max_context_chars: int = 0,
    max_hotset_updates: int = 0,
    max_session_context_chars: int = 0,
    hotset_change_threshold: int = 0,
    hotset_min_prompt_interval: int = 0,
    metric_probability_weight: float = -1,
    max_metric_probability_blend: float = -1,
    basic_solution_priority_boost: float = -1,
    probability_weight: float = -1,
    impact_weight: float = -1,
) -> str:
    """Adjust recommendation count, context budget, and probability/impact balance."""
    class Args:
        pass

    args = Args()
    args.top_k = top_k or None
    args.session_top_k = session_top_k or None
    args.max_context_chars = max_context_chars or None
    args.max_hotset_updates = max_hotset_updates or None
    args.max_session_context_chars = max_session_context_chars or None
    args.hotset_change_threshold = hotset_change_threshold or None
    args.hotset_min_prompt_interval = hotset_min_prompt_interval or None
    args.metric_probability_weight = (
        metric_probability_weight if metric_probability_weight >= 0 else None
    )
    args.max_metric_probability_blend = (
        max_metric_probability_blend if max_metric_probability_blend >= 0 else None
    )
    args.basic_solution_priority_boost = (
        basic_solution_priority_boost if basic_solution_priority_boost >= 0 else None
    )
    args.probability_weight = probability_weight if probability_weight >= 0 else None
    args.impact_weight = impact_weight if impact_weight >= 0 else None
    return json.dumps(risk_agent.configure(args), indent=2)


@mcp.tool()
def feedback(error_id: str, outcome: str) -> str:
    """Record whether a recommended risk was triggered or successfully avoided."""
    if outcome not in {"triggered", "avoided"}:
        raise ValueError("outcome must be triggered or avoided")
    return json.dumps(risk_agent.record_feedback(error_id, outcome), indent=2)


@mcp.tool()
def record_metric(risk_id: str, event: str, amount: int = 1) -> str:
    """Record an explicit outcome in the independent sharded metric store."""
    return json.dumps(
        risk_agent.update_metric(
            risk_id,
            event,
            amount=amount,
            source="explicit",
        ),
        indent=2,
    )


@mcp.tool()
def metrics(category: str = "") -> str:
    """Read a compact aggregate without loading all metric shards into context."""
    return json.dumps(risk_agent.metrics_summary(category), indent=2)


@mcp.tool()
def solution(error_id: str) -> str:
    """Return the single safe command for one registered basic error."""
    return json.dumps(risk_agent.get_solution(error_id), indent=2)


@mcp.tool()
def add_solution(error_id: str, command: str) -> str:
    """Register one validated non-destructive command for a basic error."""
    return json.dumps(risk_agent.register_solution(error_id, command), indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
