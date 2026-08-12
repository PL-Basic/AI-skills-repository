from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
AGENT_PATH = ROOT / "skill" / "scripts" / "risk-agent.py"


def load_agent():
    spec = importlib.util.spec_from_file_location("agent_error_guard_test_agent", AGENT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load risk agent.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_hook(agent, event: str, payload: dict) -> dict | None:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    with patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(stdout):
        result = agent.hook(event)
    if result != 0:
        raise AssertionError(f"Hook {event} returned {result}.")
    text = stdout.getvalue().strip()
    return json.loads(text) if text else None


def item(item_id: str) -> dict:
    return {
        "id": item_id,
        "forbidden": f"Do not trigger {item_id}.",
        "score": 50.0,
        "layer": "current-task",
        "impact": "project",
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-error-guard-test-") as state:
        os.environ["AGENT_ERROR_GUARD_STATE"] = state
        agent = load_agent()
        agent.STATE_ROOT = Path(state)
        agent.PROFILE_PATH = agent.STATE_ROOT / "host-profile.json"
        agent.CONFIG_PATH = agent.STATE_ROOT / "config.json"
        agent.RECENT_PATH = agent.STATE_ROOT / "recent-commands.json"
        agent.FEEDBACK_PATH = agent.STATE_ROOT / "feedback.json"
        agent.RISK_INDEX = agent.STATE_ROOT / "risk-index.tsv"
        agent.SESSION_PATH = agent.STATE_ROOT / "session-hotsets.json"
        agent.METRICS_ROOT = agent.STATE_ROOT / "metrics"
        sets = {
            "alpha": [
                item("POL-HOST-001"),
                item("POL-SECRET-001"),
                item("POL-PROJECT-001"),
            ],
            "beta": [
                item("POL-HOST-001"),
                item("POL-FIRMWARE-001"),
                item("POL-RETRY-001"),
            ],
            "gamma": [
                item("POL-RECURSION-001"),
                item("POL-LONGRUN-001"),
                item("POL-FRONTEND-001"),
            ],
            "delta": [
                item("POL-HOST-001"),
                item("POL-PROJECT-001"),
                item("POL-RETRY-001"),
            ],
        }

        def recommendations(task: str, cwd: str, limit=None, layer=""):
            return sets.get(task, sets["alpha"])

        agent.recommend = recommendations
        base = {"session_id": "session-1", "cwd": str(ROOT)}
        baseline = run_hook(agent, "session-start", base)
        if not baseline or "injected once" not in str(baseline):
            raise AssertionError("Session baseline was not injected.")
        if run_hook(agent, "session-start", base) is not None:
            raise AssertionError("Resumed session baseline was injected again.")
        first = run_hook(agent, "user-prompt", {**base, "prompt": "alpha"})
        if not first or "hot set v1" not in str(first):
            raise AssertionError("First prompt did not inject hot set v1.")
        if run_hook(agent, "user-prompt", {**base, "prompt": "alpha"}) is not None:
            raise AssertionError("Unchanged hot set was injected again.")
        second = run_hook(agent, "user-prompt", {**base, "prompt": "beta"})
        if not second or "hot set v2" not in str(second):
            raise AssertionError("Changed hot set did not inject v2.")
        if run_hook(agent, "user-prompt", {**base, "prompt": "gamma"}) is not None:
            raise AssertionError("Minimum prompt interval was ignored.")
        third = run_hook(agent, "user-prompt", {**base, "prompt": "gamma"})
        if not third or "hot set v3" not in str(third):
            raise AssertionError("Third bounded hot-set update was not emitted.")
        run_hook(agent, "user-prompt", {**base, "prompt": "delta"})
        if run_hook(agent, "user-prompt", {**base, "prompt": "delta"}) is not None:
            raise AssertionError("Hot-set update budget was exceeded.")

        denied_git = run_hook(
            agent,
            "pre-tool",
            {"command": "git reset --hard HEAD"},
        )
        if denied_git["hookSpecificOutput"]["permissionDecision"] != "deny":
            raise AssertionError("Destructive Git command was not denied.")
        denied_firmware = run_hook(
            agent,
            "pre-tool",
            {"command": "Remove-Item -Recurse .pio"},
        )
        if denied_firmware["hookSpecificOutput"]["permissionDecision"] != "deny":
            raise AssertionError("Firmware output deletion was not denied.")

        session_state = json.loads(agent.SESSION_PATH.read_text(encoding="utf-8"))
        entry = next(iter(session_state["sessions"].values()))
        if entry["update_count"] != 3 or entry["context_chars"] > 3000:
            raise AssertionError("Session hot-set budget is invalid.")
        metric = agent.read_metric("POL-HOST-001", "policy")
        if metric["counts"].get("context_injected", 0) < 1:
            raise AssertionError("Context injection metric was not recorded.")
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(
                executor.map(
                    lambda _: agent.update_metric(
                        "POL-HOST-001",
                        "confirmed_triggered",
                        source="explicit",
                    ),
                    range(40),
                )
            )
        metric = agent.read_metric("POL-HOST-001", "policy")
        if metric["counts"].get("confirmed_triggered") != 40:
            raise AssertionError("Concurrent metric updates lost increments.")
        summary = agent.metrics_summary()
        if (
            summary["risk_shards"] < 1
            or summary["totals"]["failures"] != 0
            or metric["counts"].get("context_injected", 0) < 1
            or metric["counts"].get("confirmed_triggered", 0) != 40
        ):
            raise AssertionError("Metric summary did not aggregate shards.")
        config = agent.load_config()
        row = agent.find_risk("ERR-20000101-001")
        baseline = agent.score_row(row, "PowerShell rg fixed search", str(ROOT), {}, config)
        for _ in range(20):
            agent.update_metric(
                "ERR-20000101-001",
                "confirmed_triggered",
                source="explicit",
            )
        measured = agent.score_row(row, "PowerShell rg fixed search", str(ROOT), {}, config)
        if (
            abs(measured["probability"] - baseline["probability"])
            > config["max_metric_probability_blend"] + 0.01
        ):
            raise AssertionError("Metric evidence exceeded the probability blend cap.")
        if not measured["basic_solution"]:
            raise AssertionError("Safe solution did not contribute an availability signal.")
        solution = agent.get_solution("ERR-20000101-001", track=False)
        if solution["command"] != "rg -F 'needle' .":
            raise AssertionError("Basic solution lookup returned the wrong command.")
        try:
            agent.validate_solution_command("Remove-Item -Recurse .")
            raise AssertionError("Destructive basic solution was accepted.")
        except ValueError:
            pass
        try:
            agent.validate_solution_command("rg -F needle . | Select-Object -First 1")
            raise AssertionError("Chained basic solution was accepted.")
        except ValueError:
            pass
        try:
            agent.register_solution(
                "POL-HOST-001",
                "Get-ChildItem .",
            )
            raise AssertionError("A policy was allowed to own a basic solution.")
        except ValueError:
            pass
        try:
            synthetic_user_path = "C:" + "\\Us" + "ers\\example\\project"
            agent.validate_solution_command(f"rg -F needle {synthetic_user_path}")
            raise AssertionError("A machine-specific solution path was accepted.")
        except ValueError:
            pass
        try:
            agent.update_metric(
                "POL-HOST-001",
                "solution_succeeded",
                source="explicit",
            )
            raise AssertionError("Solution success was recorded without a solution.")
        except ValueError:
            pass

    print("Release tests passed: hot-set budget, no-op reuse, and command guards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
