from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from install import MCP_NAME, codex_executable, codex_home, load_json, remove_managed_hooks


def main() -> int:
    parser = argparse.ArgumentParser(description="Uninstall Agent Error Guard.")
    parser.add_argument(
        "--remove-state",
        action="store_true",
        help="Also remove the configured profile and runtime state.",
    )
    args = parser.parse_args()
    home = codex_home().resolve()
    skill_root = home / "skills" / "agent-error-guard"
    state_location = load_json(skill_root / "state-location.json", {})
    configured_state = str(state_location.get("state_root", ""))
    hooks_path = home / "hooks.json"
    hooks = load_json(hooks_path, {"hooks": {}})
    remove_managed_hooks(hooks)
    hooks_path.write_text(
        json.dumps(hooks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        subprocess.run(
            [codex_executable(), "mcp", "remove", MCP_NAME],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pass
    if skill_root.exists():
        shutil.rmtree(skill_root)
    state = os.environ.get("AGENT_ERROR_GUARD_STATE", "") or configured_state
    if args.remove_state and state:
        state_root = Path(state).expanduser().resolve()
        if state_root.name == "state" and state_root.parent.name == "AgentErrorGuard":
            shutil.rmtree(state_root)
        elif state_root.name == "agent-error-guard":
            shutil.rmtree(state_root)
        else:
            raise ValueError("Refusing to remove an unrecognized state directory.")
    print("Agent Error Guard hooks, MCP registration, and Skill were removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
