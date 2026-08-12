from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_SKILL = PACKAGE_ROOT / "skill"
MARKER = "[Agent Error Guard]"
MCP_NAME = "agent-error-guard"


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def fixed_drives() -> list[Path]:
    if os.name != "nt":
        return []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    result: list[Path] = []
    for index in range(26):
        if not mask & (1 << index):
            continue
        root = f"{chr(ord('A') + index)}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:
            result.append(Path(root))
    return result


def choose_state_root(explicit: str) -> tuple[Path, str]:
    if explicit:
        return Path(explicit).expanduser().resolve(), "explicit"
    if os.name == "nt":
        system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/").lower()
        candidates = [
            drive / "AgentErrorGuard" / "state"
            for drive in fixed_drives()
            if str(drive).rstrip("\\/").lower() != system_drive
        ]
        for path in candidates:
            try:
                path.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=path, delete=True):
                    pass
                return path, (
                    "existing-non-system-drive"
                    if any(path.iterdir())
                    else "non-system-drive"
                )
            except OSError:
                continue
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state).expanduser() / "agent-error-guard", "xdg-fallback"
    return (
        Path.home() / ".local" / "state" / "agent-error-guard",
        "user-state-fallback",
    )


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def command_text(skill_root: Path, event: str) -> str:
    return subprocess.list2cmdline(
        [
            sys.executable,
            str(skill_root / "scripts" / "risk-agent.py"),
            "hook",
            "--event",
            event,
        ]
    )


def hook_entry(skill_root: Path, event: str, timeout: int, message: str) -> dict:
    return {
        "type": "command",
        "command": command_text(skill_root, event),
        "timeout": timeout,
        "statusMessage": f"{MARKER} {message}",
    }


def remove_managed_hooks(config: dict[str, Any]) -> None:
    hooks = config.setdefault("hooks", {})
    for event, groups in list(hooks.items()):
        retained_groups = []
        for group in groups if isinstance(groups, list) else []:
            managed = [
                hook
                for hook in group.get("hooks", [])
                if str(hook.get("statusMessage", "")).startswith(MARKER)
            ]
            if not managed:
                retained_groups.append(group)
                continue
            remaining = [
                hook for hook in group.get("hooks", []) if hook not in managed
            ]
            if remaining:
                group["hooks"] = remaining
                retained_groups.append(group)
        if retained_groups:
            hooks[event] = retained_groups
        else:
            hooks.pop(event, None)


def install_hooks(home: Path, skill_root: Path) -> Path:
    path = home / "hooks.json"
    config = load_json(path, {"hooks": {}})
    if not isinstance(config, dict):
        raise ValueError(f"Invalid hooks JSON root: {path}")
    remove_managed_hooks(config)
    hooks = config.setdefault("hooks", {})
    entries = {
        "PreToolUse": (
            "Bash",
            hook_entry(skill_root, "pre-tool", 3, "Checking command risk"),
        ),
        "PostToolUse": (
            "Bash",
            hook_entry(skill_root, "post-tool", 3, "Recording command outcome"),
        ),
        "SessionStart": (
            "startup|resume",
            hook_entry(skill_root, "session-start", 5, "Loading host risks"),
        ),
        "UserPromptSubmit": (
            None,
            hook_entry(skill_root, "user-prompt", 5, "Updating task hot set"),
        ),
    }
    for event, (matcher, hook) in entries.items():
        group: dict[str, Any] = {"hooks": [hook]}
        if matcher:
            group["matcher"] = matcher
        hooks.setdefault(event, []).append(group)
    write_json_atomic(path, config)
    return path


def codex_executable() -> str:
    candidates = ["codex.cmd", "codex.exe", "codex"] if os.name == "nt" else ["codex"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FileNotFoundError("Codex CLI was not found on PATH.")


def install_mcp(skill_root: Path, state_root: Path) -> None:
    codex = codex_executable()
    subprocess.run([codex, "mcp", "remove", MCP_NAME], capture_output=True, text=True)
    command = [
        codex,
        "mcp",
        "add",
        MCP_NAME,
        "--env",
        f"AGENT_ERROR_GUARD_STATE={state_root}",
        "--",
        sys.executable,
        str(skill_root / "scripts" / "mcp-server.py"),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Agent Error Guard for Codex.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--workspace", action="append", default=[])
    parser.add_argument("--refresh-profile", action="store_true")
    parser.add_argument("--skip-mcp", action="store_true")
    args = parser.parse_args()

    home = codex_home().resolve()
    skill_root = home / "skills" / "agent-error-guard"
    state_root, state_strategy = choose_state_root(args.state_dir)
    state_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SOURCE_SKILL,
        skill_root,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "risk-index.tsv"),
    )
    write_json_atomic(
        skill_root / "state-location.json",
        {"schema": 1, "state_root": str(state_root)},
    )
    hooks_path = install_hooks(home, skill_root)
    env = os.environ.copy()
    env["AGENT_ERROR_GUARD_STATE"] = str(state_root)
    subprocess.run(
        [sys.executable, str(skill_root / "scripts" / "risk-agent.py"), "build-index"],
        check=True,
        env=env,
    )
    profile_path = state_root / "host-profile.json"
    if args.refresh_profile or not profile_path.exists():
        command = [
            sys.executable,
            str(skill_root / "scripts" / "risk-agent.py"),
            "profile",
        ]
        for workspace in args.workspace:
            command.extend(["--workspace", workspace])
        subprocess.run(command, check=True, env=env)
    if not args.skip_mcp:
        install_mcp(skill_root, state_root)
    manifest = {
        "schema": 1,
        "skill_root": str(skill_root),
        "state_root": str(state_root),
        "state_strategy": state_strategy,
        "python": sys.executable,
        "hooks": str(hooks_path),
        "mcp": None if args.skip_mcp else MCP_NAME,
    }
    write_json_atomic(state_root / "install-manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if state_strategy.endswith("fallback"):
        print(
            "Warning: no writable non-system fixed drive was selected; "
            "use --state-dir to choose durable storage.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
