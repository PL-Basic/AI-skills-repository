from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
REFERENCES = SKILL_ROOT / "references"
RECORD_ROOT = REFERENCES / "records"
ERROR_INDEX = REFERENCES / "index.tsv"
POLICY_INDEX = REFERENCES / "policies.tsv"
DEFAULTS_PATH = REFERENCES / "risk-defaults.json"
STATE_LOCATION_PATH = SKILL_ROOT / "state-location.json"


def windows_fixed_drives() -> list[Path]:
    if os.name != "nt":
        return []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    drives: list[Path] = []
    for index in range(26):
        if not mask & (1 << index):
            continue
        root = f"{chr(ord('A') + index)}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:
            drives.append(Path(root))
    return drives


def default_state_root() -> Path:
    explicit = os.environ.get("AGENT_ERROR_GUARD_STATE") or os.environ.get(
        "WIFI_ERROR_GUARD_STATE"
    )
    if explicit:
        return Path(explicit).expanduser()
    if STATE_LOCATION_PATH.exists():
        try:
            configured = json.loads(STATE_LOCATION_PATH.read_text(encoding="utf-8"))
            if isinstance(configured, dict) and configured.get("state_root"):
                return Path(str(configured["state_root"])).expanduser()
        except (OSError, json.JSONDecodeError):
            pass
    if os.name == "nt":
        system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/").lower()
        candidates = [
            drive / "AgentErrorGuard" / "state"
            for drive in windows_fixed_drives()
            if str(drive).rstrip("\\/").lower() != system_drive
        ]
        existing = [path for path in candidates if path.exists()]
        if existing:
            return existing[0]
        if candidates:
            return candidates[0]
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state).expanduser() / "agent-error-guard"
    return Path.home() / ".local" / "state" / "agent-error-guard"


STATE_ROOT = default_state_root()
PROFILE_PATH = STATE_ROOT / "host-profile.json"
CONFIG_PATH = STATE_ROOT / "config.json"
RECENT_PATH = STATE_ROOT / "recent-commands.json"
FEEDBACK_PATH = STATE_ROOT / "feedback.json"
RISK_INDEX = STATE_ROOT / "risk-index.tsv"
SESSION_PATH = STATE_ROOT / "session-hotsets.json"
METRICS_ROOT = STATE_ROOT / "metrics"
SOLUTIONS_ROOT = REFERENCES / "solutions"

METRIC_EVENTS = {
    "recommended",
    "context_injected",
    "observed_failure",
    "confirmed_triggered",
    "confirmed_avoided",
    "corrected_success",
    "repeat_failure",
    "blocked",
    "solution_shown",
    "solution_succeeded",
}

FIELDS = (
    "Signature",
    "Date",
    "Repository and branch",
    "Related paths",
    "Trigger command or operation",
    "Increment task",
    "Confirmed cause or unknowns",
    "Ineffective actions",
    "Proven fix",
    "Allowed next actions",
    "Forbidden repeated actions",
    "Stop and ask the user when",
)

RISK_FIELDS = (
    "id",
    "source",
    "category",
    "primary_domain",
    "layer",
    "impact",
    "severity",
    "likelihood",
    "loop_risk",
    "duration_risk",
    "destructive_risk",
    "date",
    "title",
    "signature",
    "forbidden",
    "tags",
    "record",
)

TOKEN_RE = re.compile(r"[a-z][a-z0-9_.:/\\-]{1,}|[\u4e00-\u9fff]{2,}", re.I)
VERSION_COMMANDS = {
    "git": ["git", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm.cmd" if os.name == "nt" else "npm", "--version"],
    "python": [sys.executable, "--version"],
    "java": ["java", "-version"],
    "maven": ["mvn.cmd" if os.name == "nt" else "mvn", "--version"],
    "platformio": ["platformio", "--version"],
    "docker": ["docker", "--version"],
}

DOMAIN_TERMS = {
    "frontend": {
        "frontend",
        "vue",
        "vite",
        "npm",
        "node",
        "playwright",
        "chromium",
        "browser",
        "ui",
        "css",
    },
    "backend": {
        "backend",
        "java",
        "maven",
        "mvn",
        "spring",
        "gateway",
        "feign",
        "service",
        "controller",
        "mapper",
    },
    "database": {
        "database",
        "mysql",
        "jdbc",
        "flyway",
        "migration",
        "schema",
        "sql",
        "mapper",
        "xml",
    },
    "firmware": {
        "firmware",
        "esp32",
        "platformio",
        "pio",
        "idf",
        "flash",
        "upload",
        "serial",
        "com",
        "partition",
    },
    "git": {
        "git",
        "worktree",
        "branch",
        "commit",
        "staging",
        "push",
        "rebase",
        "merge",
    },
    "agent": {
        "agent",
        "codex",
        "powershell",
        "shell",
        "context",
        "tool",
        "command",
        "apply_patch",
        "regex",
    },
}

DOMAIN_TOOLS = {
    "frontend": {"node", "npm"},
    "backend": {"java", "maven"},
    "database": {"java", "maven"},
    "firmware": {"platformio", "python"},
    "git": {"git"},
    "agent": {"python", "git"},
}


def resolve_tool_command(name: str, command: list[str]) -> list[str]:
    if shutil.which(command[0]):
        return command
    candidates: dict[str, list[Path]] = {
        "platformio": [
            Path.home() / ".platformio" / "penv" / "Scripts" / "platformio.exe"
        ],
    }
    for candidate in candidates.get(name, []):
        if candidate.exists():
            return [str(candidate), *command[1:]]
    return command


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def risk_bucket(item_id: str) -> tuple[str, str]:
    if re.fullmatch(r"ERR-\d{8}-\d{3}", item_id):
        return "error", item_id.split("-")[1]
    if re.fullmatch(r"POL-[A-Z0-9]+-\d{3}", item_id):
        return "policy", item_id.split("-")[1].lower()
    raise ValueError(f"Invalid risk ID: {item_id}")


def metric_path(item_id: str, category: str = "") -> Path:
    source, bucket = risk_bucket(item_id)
    if not category:
        category = find_risk(item_id)["category"]
    safe_category = re.sub(r"[^a-z0-9-]", "", category.lower())
    if not safe_category:
        safe_category = source
    return METRICS_ROOT / safe_category / bucket / f"{item_id}.json"


def solution_path(item_id: str, category: str) -> Path:
    _, bucket = risk_bucket(item_id)
    safe_category = re.sub(r"[^a-z0-9-]", "", category.lower())
    if not safe_category:
        raise ValueError("A solution requires a valid category.")
    return SOLUTIONS_ROOT / safe_category / bucket / f"{item_id}.cmd"


def acquire_file_lock(path: Path, timeout_seconds: float = 2.0) -> Path:
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_seconds
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 10:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.time() >= deadline:
                raise TimeoutError(f"Metric shard lock timed out: {lock}")
            time.sleep(0.025)


def update_metric(
    item_id: str,
    event: str,
    amount: int = 1,
    source: str = "automatic",
) -> dict[str, Any]:
    if event not in METRIC_EVENTS:
        raise ValueError(f"Unknown metric event: {event}")
    if amount < 1 or amount > 1000:
        raise ValueError("Metric amount must be between 1 and 1000.")
    if event in {"solution_shown", "solution_succeeded"}:
        row = find_risk(item_id)
        if not solution_path(item_id, row["category"]).is_file():
            raise ValueError(f"Cannot record {event}; {item_id} has no basic solution.")
    path = metric_path(item_id)
    lock = acquire_file_lock(path)
    try:
        state = read_json(
            path,
            {
                "schema": 1,
                "risk_id": item_id,
                "counts": {},
                "sources": {"automatic": 0, "explicit": 0},
            },
        )
        counts = state.setdefault("counts", {})
        counts[event] = int(counts.get(event, 0)) + amount
        sources = state.setdefault("sources", {"automatic": 0, "explicit": 0})
        source_key = "explicit" if source == "explicit" else "automatic"
        sources[source_key] = int(sources.get(source_key, 0)) + amount
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(path, state)
        return state
    finally:
        lock.unlink(missing_ok=True)


def read_metric(item_id: str, category: str = "") -> dict[str, Any]:
    return read_json(
        metric_path(item_id, category),
        {
            "schema": 1,
            "risk_id": item_id,
            "counts": {},
            "sources": {"automatic": 0, "explicit": 0},
        },
    )


def migrate_legacy_feedback() -> None:
    legacy = read_json(FEEDBACK_PATH, {})
    if not isinstance(legacy, dict):
        return
    marker = METRICS_ROOT / ".legacy-feedback-migrated"
    if marker.exists():
        return
    migration_lock = acquire_file_lock(marker)
    try:
        if marker.exists():
            return
        for item_id, entry in legacy.items():
            if not isinstance(entry, dict):
                continue
            triggered = max(0, int(entry.get("triggered", 0)))
            avoided = max(0, int(entry.get("avoided", 0)))
            if triggered:
                update_metric(
                    item_id, "confirmed_triggered", triggered, source="explicit"
                )
            if avoided:
                update_metric(
                    item_id, "confirmed_avoided", avoided, source="explicit"
                )
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(
            datetime.now(timezone.utc).isoformat() + "\n",
            encoding="utf-8",
        )
        temporary.replace(marker)
    finally:
        migration_lock.unlink(missing_ok=True)


def find_risk(item_id: str) -> dict[str, str]:
    matches = [row for row in load_rows() if row["id"] == item_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one risk row for {item_id}, found {len(matches)}.")
    return matches[0]


def validate_solution_command(command: str) -> str:
    normalized = command.strip()
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise ValueError("A basic solution must be exactly one non-empty line.")
    if len(normalized) > 240:
        raise ValueError("A basic solution must not exceed 240 characters.")
    if re.search(r"(;|&&|\|\||\||>|<|`|\$\()", normalized):
        raise ValueError("A basic solution cannot contain chaining or redirection.")
    forbidden = re.compile(
        r"(?i)\b("
        r"remove-item|rm|del|rmdir|format|diskpart|shutdown|restart-computer|"
        r"git\s+(?:reset|clean|rebase|merge|push|checkout)|"
        r"drop|delete\s+from|truncate|update\s+\w+\s+set|insert\s+into|"
        r"invoke-webrequest|curl|wget|ssh|scp|chmod|chown|runas|sudo"
        r")\b"
    )
    if forbidden.search(normalized):
        raise ValueError("A basic solution cannot mutate host, project, data, or network state.")
    if re.search(
        r"(?i)(password|passwd|token|cookie|secret|api[_-]?key)\s*[:=]",
        normalized,
    ):
        raise ValueError("A basic solution cannot contain sensitive assignments.")
    if re.search(
        r"(?i)(?:[a-z]:[\\/]|\\\\[^\\\s]+[\\/]|/(?:home|users?)/[^/\s]+)",
        normalized,
    ):
        raise ValueError("A basic solution cannot contain a machine-specific absolute path.")
    return normalized


def register_solution(item_id: str, command: str) -> dict[str, str]:
    row = find_risk(item_id)
    if not item_id.startswith("ERR-"):
        raise ValueError("Basic solutions can only be linked to error records.")
    if row["impact"] == "host":
        raise ValueError("Host-impact risks cannot use one-line basic solutions.")
    if int(row["severity"]) > 3 or int(row["destructive_risk"]) > 2:
        raise ValueError("This risk exceeds the basic-solution safety threshold.")
    normalized = validate_solution_command(command)
    path = solution_path(item_id, row["category"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8").strip() != normalized:
            raise ValueError(f"A different solution already exists for {item_id}.")
        path.write_text(normalized + "\n", encoding="utf-8")
        record_path = SKILL_ROOT / row["record"]
        record_text = record_path.read_text(encoding="utf-8")
        relative_solution = os.path.relpath(path, record_path.parent).replace("\\", "/")
        link_line = f"- Basic solution: [{item_id}]({relative_solution})"
        if re.search(r"(?m)^-\s+Basic solution:\s+.*$", record_text):
            record_text = re.sub(
                r"(?m)^-\s+Basic solution:\s+.*$",
                link_line,
                record_text,
                count=1,
            )
        else:
            record_text = record_text.rstrip() + "\n" + link_line + "\n"
        record_path.write_text(record_text, encoding="utf-8")
    except PermissionError as error:
        raise PermissionError(
            "The installed Skill is read-only. Add solutions only with explicit "
            "write access to the owned Skill directory."
        ) from error
    return {
        "risk_id": item_id,
        "solution": str(path.relative_to(SKILL_ROOT)).replace("\\", "/"),
    }


def get_solution(item_id: str, track: bool = True) -> dict[str, str]:
    row = find_risk(item_id)
    path = solution_path(item_id, row["category"])
    if not path.is_file():
        raise ValueError(f"No basic solution is registered for {item_id}.")
    command = validate_solution_command(path.read_text(encoding="utf-8"))
    if track:
        update_metric(item_id, "solution_shown")
    return {"risk_id": item_id, "command": command}


def metrics_summary(category: str = "") -> dict[str, Any]:
    files = list(METRICS_ROOT.glob("*/*/*.json"))
    rows: list[dict[str, Any]] = []
    for path in files:
        state = read_json(path, {})
        item_id = str(state.get("risk_id", ""))
        if not item_id:
            continue
        try:
            risk = find_risk(item_id)
        except ValueError:
            continue
        if category and risk["category"] != category:
            continue
        counts = state.get("counts", {})
        rows.append(
            {
                "risk_id": item_id,
                "category": risk["category"],
                "recommended": int(counts.get("recommended", 0)),
                "failures": int(counts.get("observed_failure", 0)),
                "repeat_failures": int(counts.get("repeat_failure", 0)),
                "corrected_successes": int(counts.get("corrected_success", 0)),
                "blocked": int(counts.get("blocked", 0)),
                "solution_shown": int(counts.get("solution_shown", 0)),
                "solution_succeeded": int(counts.get("solution_succeeded", 0)),
            }
        )
    totals = {
        key: sum(int(row[key]) for row in rows)
        for key in (
            "recommended",
            "failures",
            "repeat_failures",
            "corrected_successes",
            "blocked",
            "solution_shown",
            "solution_succeeded",
        )
    }
    failures = totals["failures"]
    totals["inferred_correction_rate"] = round(
        totals["corrected_successes"] / failures, 4
    ) if failures else None
    totals["repeat_failure_rate"] = round(
        totals["repeat_failures"] / failures, 4
    ) if failures else None
    totals["solution_success_rate"] = round(
        totals["solution_succeeded"] / totals["solution_shown"], 4
    ) if totals["solution_shown"] else None
    return {
        "schema": 1,
        "category": category or "all",
        "risk_shards": len(rows),
        "totals": totals,
        "top_failures": sorted(
            rows,
            key=lambda row: (
                row["failures"],
                row["repeat_failures"],
                row["risk_id"],
            ),
            reverse=True,
        )[:10],
    }


def load_config() -> dict[str, Any]:
    config = read_json(DEFAULTS_PATH, {})
    config.update(read_json(CONFIG_PATH, {}))
    return config


def tokenize(text: str) -> list[str]:
    result: list[str] = []
    for match in TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip("`.,:;/\\")
        if not token:
            continue
        result.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", token):
            result.extend(token[index : index + 2] for index in range(len(token) - 1))
    return result


def parse_record(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    heading = re.search(
        r"^###\s+(ERR-\d{8}-\d{3})\s+([a-z0-9][a-z0-9-]*)\s*$",
        text,
        re.M,
    )
    if not heading:
        raise ValueError(f"Invalid record heading: {path}")
    result = {"id": heading.group(1), "title": heading.group(2)}
    for field in FIELDS:
        match = re.search(rf"^-\s+{re.escape(field)}:\s*(.*)$", text, re.M)
        if not match or not match.group(1).strip():
            raise ValueError(f"Missing field {field}: {path}")
        result[field] = re.sub(r"\s+", " ", match.group(1)).strip()
    return result


def infer_layer(text: str, category: str) -> str:
    host_terms = (
        "powershell",
        "windows",
        "execution policy",
        "access denied",
        "permission",
        "pathnotfound",
        "sandbox",
        "temp",
        "provider",
        "network",
        "registry",
        "port",
        "process",
        "shell",
    )
    session_terms = (
        "context",
        "output limit",
        "tool call",
        "apply_patch",
        "blind",
        "retry",
        "parser",
        "regex",
        "command",
        "timeout",
    )
    if any(term in text for term in host_terms):
        return "host-environment"
    if category == "agent-tooling" or any(term in text for term in session_terms):
        return "agent-session"
    return "current-task"


def infer_impact(text: str, category: str) -> tuple[str, int, int]:
    host_danger = (
        "format",
        "boot",
        "shutdown",
        "system-wide",
        "secret",
        "credential",
        "acl",
        "recursive delete",
    )
    project_danger = (
        "reset --hard",
        "git clean",
        "rebase",
        "merge",
        "delete",
        "drop database",
        "migration",
        "firmware",
        "build output",
        "cache",
        "staging",
        "push",
    )
    if any(term in text for term in host_danger):
        return "host", 5, 5
    if any(term in text for term in project_danger):
        return "project", 4, 4
    if category in {
        "database-migration",
        "firmware-serial",
        "git-worktree",
        "filesystem-permission-lock",
    }:
        return "project", 4, 3
    if category in {"service-integration", "frontend-browser", "build-test"}:
        return "project", 3, 2
    return "session", 2, 1


def infer_risks(text: str) -> tuple[int, int, int, int]:
    recurrence = len(
        re.findall(
            r"\brecur(?:red|rence)?\b|\brepeat(?:ed|edly)?\b|\bagain\b|two noisy|twice",
            text,
        )
    )
    loop_terms = (
        "retry",
        "repeat",
        "again",
        "loop",
        "unchanged",
        "third",
        "recursive",
        "context",
    )
    duration_terms = (
        "timeout",
        "long-running",
        "build",
        "compile",
        "recursive",
        "background",
        "lock wait",
        "no progress",
    )
    destructive_terms = (
        "delete",
        "remove-item",
        "reset",
        "clean",
        "rebase",
        "merge",
        "drop",
        "acl",
        "secret",
        "flash",
        "build output",
    )
    likelihood = min(5, 2 + recurrence + int("commonly" in text or "every" in text))
    loop_risk = min(5, 1 + sum(term in text for term in loop_terms))
    duration_risk = min(5, 1 + sum(term in text for term in duration_terms))
    destructive_risk = min(5, 1 + sum(term in text for term in destructive_terms))
    return likelihood, loop_risk, duration_risk, destructive_risk


def infer_primary_domain(category: str, text: str) -> str:
    fixed = {
        "firmware-serial": "firmware",
        "frontend-browser": "frontend",
        "database-migration": "database",
        "git-worktree": "git",
        "service-integration": "backend",
        "agent-tooling": "agent",
    }
    if category in fixed:
        return fixed[category]
    ordered = ("firmware", "frontend", "database", "backend", "git")
    scores = {
        domain: sum(term in text for term in DOMAIN_TERMS[domain])
        for domain in ordered
    }
    best = max(ordered, key=lambda domain: scores[domain])
    return best if scores[best] > 0 else "general"


def build_risk_index() -> int:
    rows: list[dict[str, Any]] = []
    for path in sorted(RECORD_ROOT.rglob("ERR-*.md")):
        record = parse_record(path)
        category = path.parent.name
        combined = " ".join(record.values()).lower()
        primary_domain = infer_primary_domain(category, combined)
        layer = infer_layer(combined, category)
        impact, severity, inferred_destructive = infer_impact(combined, category)
        likelihood, loop_risk, duration_risk, destructive_risk = infer_risks(combined)
        destructive_risk = max(destructive_risk, inferred_destructive)
        tags = " ".join(
            dict.fromkeys(
                [category, layer, impact]
                + tokenize(
                    " ".join(
                        (
                            record["title"],
                            record["Signature"],
                            record["Repository and branch"],
                            record["Related paths"],
                            record["Trigger command or operation"],
                        )
                    )
                )[:48]
            )
        )
        rows.append(
            {
                "id": record["id"],
                "source": "error",
                "category": category,
                "primary_domain": primary_domain,
                "layer": layer,
                "impact": impact,
                "severity": severity,
                "likelihood": likelihood,
                "loop_risk": loop_risk,
                "duration_risk": duration_risk,
                "destructive_risk": destructive_risk,
                "date": record["Date"],
                "title": record["title"],
                "signature": record["Signature"],
                "forbidden": record["Forbidden repeated actions"],
                "tags": tags,
                "record": str(path.relative_to(SKILL_ROOT)).replace("\\", "/"),
            }
        )
    with POLICY_INDEX.open("r", encoding="utf-8", newline="") as handle:
        for policy in csv.DictReader(handle, delimiter="\t"):
            policy_row = {field: policy.get(field, "") for field in RISK_FIELDS}
            policy_row["source"] = "policy"
            policy_row["category"] = "policy"
            policy_row["date"] = ""
            policy_row["record"] = ""
            rows.append(policy_row)
    rows.sort(key=lambda row: row["id"], reverse=True)
    RISK_INDEX.parent.mkdir(parents=True, exist_ok=True)
    temporary = RISK_INDEX.with_suffix(".tsv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RISK_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(RISK_INDEX)
    return len(rows)


def ensure_risk_index() -> None:
    sources = [ERROR_INDEX, POLICY_INDEX, Path(__file__)]
    if not RISK_INDEX.exists() or any(
        source.exists() and source.stat().st_mtime > RISK_INDEX.stat().st_mtime
        for source in sources
    ):
        build_risk_index()


def command_version(command: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {"available": False}
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout + " " + result.stderr).strip().splitlines()
        return {
            "available": True,
            "path": executable,
            "version": output[0][:240] if output else "unknown",
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"available": True, "path": executable, "version": type(error).__name__}


def workspace_facts(path_text: str) -> dict[str, Any]:
    path = Path(path_text).expanduser().resolve()
    markers = {
        "frontend": ["package.json", "vite.config.js", "vite.config.ts"],
        "backend": ["pom.xml", "mvnw.cmd", "mvnw"],
        "firmware": ["platformio.ini", "CMakeLists.txt", "sdkconfig"],
        "git": [".git"],
    }
    tags = [
        tag
        for tag, names in markers.items()
        if any((path / name).exists() for name in names)
    ]
    return {"path": str(path), "exists": path.exists(), "tags": tags}


def create_profile(workspaces: list[str]) -> dict[str, Any]:
    tools = {
        name: command_version(resolve_tool_command(name, command))
        for name, command in VERSION_COMMANDS.items()
    }
    profile = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "refresh_mode": "explicit-only",
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "shell": {
            "comspec": os.environ.get("COMSPEC", ""),
            "powershell": shutil.which("powershell") or shutil.which("pwsh") or "",
        },
        "tools": tools,
        "workspaces": [workspace_facts(path) for path in workspaces],
        "safety": {
            "firmware_build_outputs_immutable": True,
            "protect_dirty_worktrees": True,
            "no_broad_recursive_operations": True,
            "no_secret_store_scans": True,
        },
    }
    write_json(PROFILE_PATH, profile)
    return profile


def load_rows() -> list[dict[str, str]]:
    ensure_risk_index()
    with RISK_INDEX.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def detect_domains(text: str) -> set[str]:
    tokens = set(tokenize(text))
    domains = {
        domain for domain, terms in DOMAIN_TERMS.items() if tokens & terms
    }
    return domains


def current_workspace(profile: dict[str, Any], cwd: str) -> dict[str, Any]:
    normalized_cwd = os.path.normcase(os.path.abspath(cwd))
    candidates = []
    for workspace in profile.get("workspaces", []):
        workspace_path = os.path.normcase(os.path.abspath(workspace.get("path", "")))
        if normalized_cwd == workspace_path or normalized_cwd.startswith(
            workspace_path + os.sep
        ):
            candidates.append((len(workspace_path), workspace))
    return max(candidates, default=(0, {}), key=lambda value: value[0])[1]


def profile_tokens(
    profile: dict[str, Any],
    cwd: str,
    task_domains: set[str],
) -> set[str]:
    terms = [
        profile.get("os", {}).get("system", ""),
        profile.get("os", {}).get("release", ""),
        cwd,
    ]
    workspace = current_workspace(profile, cwd)
    terms.append(workspace.get("path", ""))
    terms.extend(workspace.get("tags", []))
    relevant_domains = set(task_domains) | set(workspace.get("tags", [])) | {"git"}
    relevant_tools = set().union(
        *(DOMAIN_TOOLS.get(domain, set()) for domain in relevant_domains)
    )
    for name, detail in profile.get("tools", {}).items():
        if detail.get("available") and name in relevant_tools:
            terms.extend((name, detail.get("path", ""), detail.get("version", "")))
    return set(tokenize(" ".join(map(str, terms))))


def cosine_similarity(query_tokens: list[str], document_tokens: list[str]) -> float:
    if not query_tokens or not document_tokens:
        return 0.0
    query = Counter(query_tokens)
    document = Counter(document_tokens)
    overlap = set(query) & set(document)
    numerator = sum(query[token] * document[token] for token in overlap)
    query_norm = math.sqrt(sum(value * value for value in query.values()))
    document_norm = math.sqrt(sum(value * value for value in document.values()))
    return numerator / (query_norm * document_norm) if query_norm and document_norm else 0.0


def days_since(date_text: str) -> int:
    match = re.search(r"\d{4}-\d{2}-\d{2}", date_text)
    if not match:
        return 365
    try:
        date = datetime.strptime(match.group(0), "%Y-%m-%d").date()
        return max(0, (datetime.now().date() - date).days)
    except ValueError:
        return 365


def metric_factors(item_id: str, category: str) -> dict[str, float]:
    counts = read_metric(item_id, category).get("counts", {})
    recommended = max(0, int(counts.get("recommended", 0)))
    observed = max(0, int(counts.get("observed_failure", 0)))
    confirmed = max(0, int(counts.get("confirmed_triggered", 0)))
    avoided = max(0, int(counts.get("confirmed_avoided", 0)))
    corrected = max(0, int(counts.get("corrected_success", 0)))
    repeated = max(0, int(counts.get("repeat_failure", 0)))
    solution_shown = max(0, int(counts.get("solution_shown", 0)))
    solution_succeeded = max(0, int(counts.get("solution_succeeded", 0)))
    weighted_triggers = confirmed + 0.35 * observed
    exposure = max(recommended, math.ceil(weighted_triggers + avoided))
    trigger_rate = (1.0 + weighted_triggers) / (2.0 + exposure)
    correction_rate = (1.0 + corrected) / (2.0 + weighted_triggers)
    repeat_rate = (1.0 + repeated) / (2.0 + weighted_triggers)
    solution_rate = (1.0 + solution_succeeded) / (2.0 + solution_shown)
    confidence = 1.0 - math.exp(-exposure / 8.0)
    return {
        "samples": float(exposure),
        "confidence": min(1.0, confidence),
        "trigger_rate": min(1.0, trigger_rate),
        "correction_rate": min(1.0, correction_rate),
        "repeat_rate": min(1.0, repeat_rate),
        "solution_rate": min(1.0, solution_rate),
    }


def solution_available(row: dict[str, str]) -> bool:
    if not row["id"].startswith("ERR-"):
        return False
    if row["impact"] == "host":
        return False
    if int(row["severity"]) > 3 or int(row["destructive_risk"]) > 2:
        return False
    return solution_path(row["id"], row["category"]).is_file()


def score_row(
    row: dict[str, str],
    task: str,
    cwd: str,
    profile: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    task_tokens = tokenize(f"{task} {cwd}")
    task_domains = detect_domains(f"{task} {cwd}")
    row_tokens = tokenize(
        " ".join(
            (
                row["category"],
                row["primary_domain"],
                row["layer"],
                row["impact"],
                row["title"],
                row["signature"],
                row["forbidden"],
                row["tags"],
            )
        )
    )
    similarity = cosine_similarity(task_tokens, row_tokens)
    environment = len(profile_tokens(profile, cwd, task_domains) & set(row_tokens))
    environment = min(1.0, environment / 4.0)
    primary_domain = row["primary_domain"]
    if primary_domain == "general":
        domain_relevance = 0.45
    elif primary_domain in task_domains:
        domain_relevance = 1.0
    elif row["layer"] in {"host-environment", "agent-session"} and primary_domain in {
        "agent",
        "git",
    }:
        domain_relevance = 0.62
    else:
        domain_relevance = 0.18
    layer_prior = {
        "host-environment": 1.0,
        "current-task": 0.78,
        "agent-session": 0.68,
    }.get(row["layer"], 0.5)
    frequency = int(row["likelihood"]) / 5.0
    recency = math.exp(-days_since(row["date"]) / 90.0) if row["date"] else 0.65
    metrics = metric_factors(row["id"], row["category"])
    base_probability = (
        float(config["task_similarity_weight"]) * similarity
        + float(config["environment_weight"]) * environment
        + float(config["frequency_weight"]) * frequency
        + float(config["recency_weight"]) * recency
    )
    base_probability = min(
        1.0,
        base_probability
        * (0.72 + 0.28 * layer_prior)
        * (0.55 + 0.45 * domain_relevance),
    )
    evidence_blend = min(
        float(config["max_metric_probability_blend"]),
        metrics["confidence"] * float(config["metric_probability_weight"]),
    )
    probability = (
        base_probability * (1.0 - evidence_blend)
        + metrics["trigger_rate"] * evidence_blend
    )
    impact_base = {"host": 1.0, "project": 0.78, "session": 0.52}.get(
        row["impact"], 0.4
    )
    threat = (
        0.35 * (int(row["severity"]) / 5.0)
        + 0.25 * (int(row["destructive_risk"]) / 5.0)
        + 0.24 * (int(row["loop_risk"]) / 5.0)
        + 0.16 * (int(row["duration_risk"]) / 5.0)
    )
    harm = min(1.0, 0.62 * impact_base + 0.38 * threat)
    probability_weight = float(config["probability_weight"])
    impact_weight = float(config["impact_weight"])
    weighted = (
        max(0.01, probability) ** probability_weight
        * max(0.01, harm) ** impact_weight
    )
    metric_priority = (
        1.0
        + 0.12 * metrics["repeat_rate"] * metrics["confidence"]
        + 0.08 * (1.0 - metrics["correction_rate"]) * metrics["confidence"]
    )
    has_solution = solution_available(row)
    solution_boost = (
        1.0
        + float(config["basic_solution_priority_boost"])
        * (0.5 + 0.5 * metrics["solution_rate"])
        if has_solution
        else 1.0
    )
    score = 100.0 * weighted * metric_priority * solution_boost
    return {
        **row,
        "score": round(score, 2),
        "probability": round(probability, 3),
        "harm": round(harm, 3),
        "similarity": round(similarity, 3),
        "environment_match": round(environment, 3),
        "domain_relevance": round(domain_relevance, 3),
        "metric_samples": int(metrics["samples"]),
        "metric_confidence": round(metrics["confidence"], 3),
        "observed_trigger_rate": round(metrics["trigger_rate"], 3),
        "correction_rate": round(metrics["correction_rate"], 3),
        "repeat_rate": round(metrics["repeat_rate"], 3),
        "solution_rate": round(metrics["solution_rate"], 3),
        "basic_solution": has_solution,
        "primary_domain": primary_domain,
        "task_domains": sorted(task_domains),
    }


def recommend(
    task: str,
    cwd: str,
    limit: int | None = None,
    layer: str = "",
    track: bool = True,
) -> list[dict[str, Any]]:
    config = load_config()
    profile = read_json(PROFILE_PATH, {})
    rows = load_rows()
    scored = [
        score_row(row, task, cwd, profile, config)
        for row in rows
        if not layer or row["layer"] == layer
    ]
    if not layer:
        task_domains = detect_domains(f"{task} {cwd}")
        relevant = [
            row
            for row in scored
            if row["primary_domain"] == "general"
            or row["primary_domain"] in task_domains
            or (
                row["layer"] in {"host-environment", "agent-session"}
                and row["primary_domain"] in {"agent", "git"}
            )
        ]
        scored = relevant
    scored.sort(key=lambda row: (row["score"], row["severity"], row["id"]), reverse=True)
    target = limit or int(config["top_k"])
    if layer:
        result = scored[:target]
        if track:
            for item in result:
                update_metric(item["id"], "recommended")
        return result
    quotas = {
        "host-environment": max(1, math.ceil(target * 0.25)),
        "current-task": max(1, math.ceil(target * 0.50)),
        "agent-session": max(1, math.floor(target * 0.25)),
    }
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for layer_name, quota in quotas.items():
        for row in (item for item in scored if item["layer"] == layer_name):
            if len([item for item in selected if item["layer"] == layer_name]) >= quota:
                break
            selected.append(row)
            selected_ids.add(row["id"])
    for row in scored:
        if len(selected) >= target:
            break
        if row["id"] not in selected_ids:
            selected.append(row)
            selected_ids.add(row["id"])
    selected.sort(
        key=lambda row: (row["score"], row["severity"], row["id"]),
        reverse=True,
    )
    result = selected[:target]
    if track:
        for item in result:
            update_metric(item["id"], "recommended")
    return result


def compact_context(items: list[dict[str, Any]], heading: str) -> str:
    config = load_config()
    lines = [
        f"[Error Guard proactive risks: {heading}]",
        "Treat these as execution constraints. Search/get the full record only if needed.",
    ]
    for item in items:
        forbidden = re.sub(r"\s+", " ", item["forbidden"]).strip()
        line = (
            f"- {item['id']} score={item['score']:.1f} "
            f"{item['layer']}/{item['impact']}: {forbidden}"
        )
        if item.get("basic_solution"):
            line += f" solution={item['id']}"
        if sum(len(value) + 1 for value in lines) + len(line) > int(
            config["max_context_chars"]
        ):
            break
        lines.append(line)
    return "\n".join(lines)


def hook_context(event_name: str, context: str) -> None:
    if not context:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event_name,
                    "additionalContext": context,
                }
            }
        )
    )


def session_key(payload: dict[str, Any], cwd: str) -> str:
    identity = payload_text(
        payload,
        {
            "session_id",
            "sessionid",
            "thread_id",
            "threadid",
            "conversation_id",
            "conversationid",
            "transcript_path",
        },
    )
    if not identity:
        identity = f"{cwd}|parent={os.getppid()}"
    return hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:24]


def load_session_state() -> dict[str, Any]:
    state = read_json(SESSION_PATH, {"schema": 1, "sessions": {}})
    if not isinstance(state, dict) or not isinstance(state.get("sessions"), dict):
        return {"schema": 1, "sessions": {}}
    return state


def save_session_state(state: dict[str, Any]) -> None:
    sessions = state.get("sessions", {})
    ordered = sorted(
        sessions.items(),
        key=lambda pair: float(pair[1].get("updated_at", 0)),
        reverse=True,
    )[:64]
    state["sessions"] = dict(ordered)
    write_json(SESSION_PATH, state)


def hotset_delta_context(
    payload: dict[str, Any],
    prompt: str,
    cwd: str,
    items: list[dict[str, Any]],
) -> str:
    config = load_config()
    state = load_session_state()
    key = session_key(payload, cwd)
    session = state["sessions"].setdefault(
        key,
        {
            "version": 0,
            "prompt_count": 0,
            "update_count": 0,
            "last_update_prompt": 0,
            "active_ids": [],
            "context_chars": 0,
        },
    )
    session["prompt_count"] = int(session.get("prompt_count", 0)) + 1
    active_ids = [item["id"] for item in items]
    previous_ids = list(session.get("active_ids", []))
    added_ids = [item_id for item_id in active_ids if item_id not in previous_ids]
    retired_ids = [item_id for item_id in previous_ids if item_id not in active_ids]
    changed = len(added_ids) + len(retired_ids)
    first_update = int(session.get("update_count", 0)) == 0
    prompt_gap = int(session["prompt_count"]) - int(session.get("last_update_prompt", 0))
    within_updates = int(session.get("update_count", 0)) < int(
        config["max_hotset_updates"]
    )
    within_chars = int(session.get("context_chars", 0)) < int(
        config["max_session_context_chars"]
    )
    eligible = first_update or (
        changed >= int(config["hotset_change_threshold"])
        and prompt_gap >= int(config["hotset_min_prompt_interval"])
    )
    context = ""
    if eligible and within_updates and within_chars:
        version = int(session.get("version", 0)) + 1
        item_by_id = {item["id"]: item for item in items}
        detail_ids = active_ids if first_update else added_ids
        lines = [
            f"[Error Guard hot set v{version}; replaces all earlier hot sets]",
            "Active risk IDs: " + ", ".join(active_ids),
        ]
        if retired_ids:
            lines.append("Retired risk IDs: " + ", ".join(retired_ids))
        for item_id in detail_ids:
            item = item_by_id[item_id]
            forbidden = re.sub(r"\s+", " ", item["forbidden"]).strip()
            suffix = f" solution={item_id}" if item.get("basic_solution") else ""
            lines.append(f"- {item_id}: {forbidden}{suffix}")
        available = int(config["max_session_context_chars"]) - int(
            session.get("context_chars", 0)
        )
        while len("\n".join(lines)) > available and len(lines) > 2:
            lines.pop()
        candidate = "\n".join(lines)
        if len(candidate) <= available:
            context = candidate
            session["version"] = version
            session["update_count"] = int(session.get("update_count", 0)) + 1
            session["last_update_prompt"] = session["prompt_count"]
            session["active_ids"] = active_ids
            session["context_chars"] = int(session.get("context_chars", 0)) + len(
                context
            )
            for item_id in active_ids:
                update_metric(item_id, "context_injected")
    session["updated_at"] = time.time()
    session["task_fingerprint"] = hashlib.sha256(
        prompt.encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    save_session_state(state)
    return context


def session_baseline_context(
    payload: dict[str, Any],
    cwd: str,
    items: list[dict[str, Any]],
) -> str:
    state = load_session_state()
    key = session_key(payload, cwd)
    session = state["sessions"].setdefault(key, {})
    if session.get("baseline_injected"):
        session["updated_at"] = time.time()
        save_session_state(state)
        return ""
    context = compact_context(items, "stable host environment; injected once")
    for item in items:
        update_metric(item["id"], "context_injected")
    session["baseline_injected"] = True
    session["baseline_ids"] = [item["id"] for item in items]
    session["updated_at"] = time.time()
    save_session_state(state)
    return context


def extract_hook_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {"raw": raw}


def deep_values(value: Any, keys: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in keys:
                found.append(child)
            found.extend(deep_values(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(deep_values(child, keys))
    return found


def payload_text(payload: dict[str, Any], keys: set[str]) -> str:
    values = deep_values(payload, keys)
    return " ".join(str(value) for value in values if isinstance(value, (str, int)))


def command_fingerprint(command: str) -> str:
    normalized = re.sub(r"\s+", " ", command).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def command_token_hashes(command: str) -> list[str]:
    normalized_tokens = {
        token
        for token in tokenize(command)
        if len(token) >= 3 and not re.search(r"[/\\:=]", token)
    }
    return sorted(
        hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        for token in normalized_tokens
    )[:32]


def token_hash_similarity(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def pre_tool_decision(command: str) -> tuple[bool, str, str]:
    lowered = command.lower()
    firmware_delete = re.search(
        r"(remove-item|rm\b|del\b|rmdir).*(\.pio|build[\\/]|release[\\/]|firmware)",
        lowered,
    )
    destructive_git = re.search(
        r"\bgit\s+(reset\s+--hard|clean\b|rebase\b|merge\b|checkout\s+--|push\b)",
        lowered,
    )
    host_destructive = re.search(
        r"\b(format(?:-volume)?|diskpart|bcdedit|shutdown|restart-computer)\b",
        lowered,
    )
    broad_recursive = (
        re.search(r"(remove-item|rm\b|rmdir|get-childitem|rg\b).*(-recurse|-r\b)", lowered)
        and re.search(r"(c:\\users|c:\\|\.codex|%temp%|\$env:temp)", lowered)
    )
    if firmware_delete:
        return (
            False,
            "Firmware build output and cache deletion is forbidden.",
            "POL-FIRMWARE-001",
        )
    if destructive_git:
        return (
            False,
            "Destructive Git history/worktree operation is forbidden.",
            "POL-PROJECT-001",
        )
    if host_destructive:
        return False, "Host-destructive maintenance command is forbidden.", "POL-HOST-001"
    if broad_recursive:
        return (
            False,
            "Broad recursive operation requires a bounded exact path and ownership proof.",
            "POL-RECURSION-001",
        )
    recent = read_json(RECENT_PATH, {})
    fingerprint = command_fingerprint(command)
    entry = recent.get(fingerprint, {})
    age = time.time() - float(entry.get("failed_at", 0))
    hours = float(load_config()["deny_unchanged_failed_command_hours"])
    if entry.get("failures", 0) >= 1 and age <= hours * 3600:
        return (
            False,
            "This exact command failed recently. Search the Error Guard and change an "
            "evidenced condition before retrying.",
            "POL-RETRY-001",
        )
    return True, "", ""


def correlate_failure(command: str, signature: str, cwd: str) -> list[str]:
    query = f"{command} {signature}"
    items = recommend(query, cwd, limit=3, track=False)
    matches = [
        item
        for item in items
        if item["similarity"] >= 0.12
        and item["primary_domain"] in detect_domains(f"{query} {cwd}")
    ]
    return [item["id"] for item in matches[:2]]


def update_recent_command(
    command: str,
    failed: bool,
    signature: str,
    cwd: str,
) -> list[str]:
    if not command:
        return []
    state = read_json(RECENT_PATH, {})
    fingerprint = command_fingerprint(command)
    if failed:
        previous = state.get(fingerprint, {})
        correlated_ids = correlate_failure(command, signature, cwd)
        state[fingerprint] = {
            "failures": int(previous.get("failures", 0)) + 1,
            "failed_at": time.time(),
            "signature_hash": hashlib.sha256(
                signature.encode("utf-8", errors="replace")
            ).hexdigest()[:16],
            "risk_ids": correlated_ids,
            "token_hashes": command_token_hashes(command),
        }
        for item_id in correlated_ids:
            update_metric(item_id, "observed_failure")
        if int(previous.get("failures", 0)) >= 1:
            for item_id in correlated_ids or previous.get("risk_ids", []):
                update_metric(item_id, "repeat_failure")
    else:
        current_hashes = command_token_hashes(command)
        corrected_fingerprints = [
            key
            for key, value in state.items()
            if time.time() - float(value.get("failed_at", 0)) <= 2 * 3600
            and token_hash_similarity(current_hashes, value.get("token_hashes", []))
            >= 0.45
        ]
        for key in corrected_fingerprints:
            previous = state.pop(key, {})
            for item_id in previous.get("risk_ids", []):
                update_metric(item_id, "corrected_success")
    cutoff = time.time() - 24 * 3600
    state = {
        key: value
        for key, value in state.items()
        if float(value.get("failed_at", 0)) >= cutoff
    }
    write_json(RECENT_PATH, state)
    return correlated_ids if failed else []


def hook(event: str) -> int:
    payload = extract_hook_payload()
    cwd = payload_text(payload, {"cwd", "working_directory"}) or os.getcwd()
    if event == "session-start":
        limit = int(load_config()["session_top_k"])
        items = recommend("", cwd, limit=limit, layer="host-environment")
        hook_context(
            "SessionStart",
            session_baseline_context(payload, cwd, items),
        )
        return 0
    if event == "user-prompt":
        prompt = payload_text(payload, {"prompt", "user_prompt", "message", "raw"})
        items = recommend(prompt, cwd)
        hook_context(
            "UserPromptSubmit",
            hotset_delta_context(payload, prompt, cwd, items),
        )
        return 0
    command = payload_text(payload, {"command", "cmd"})
    if event == "pre-tool":
        allowed, reason, risk_id = pre_tool_decision(command)
        if allowed:
            return 0
        if risk_id:
            update_metric(risk_id, "blocked")
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
        return 0
    if event == "post-tool":
        exit_text = payload_text(
            payload, {"exit_code", "exitcode", "status", "error", "stderr"}
        ).lower()
        failed = bool(
            re.search(r"\bexit(?:_code)?\D+[1-9]\d*\b|error|failed|exception", exit_text)
        )
        update_recent_command(command, failed, exit_text, cwd)
        return 0
    raise ValueError(f"Unknown hook event: {event}")


def configure(args: argparse.Namespace) -> dict[str, Any]:
    current = read_json(CONFIG_PATH, {})
    for key in (
        "top_k",
        "session_top_k",
        "max_context_chars",
        "max_hotset_updates",
        "max_session_context_chars",
        "hotset_change_threshold",
        "hotset_min_prompt_interval",
        "metric_probability_weight",
        "max_metric_probability_blend",
        "basic_solution_priority_boost",
        "probability_weight",
        "impact_weight",
    ):
        value = getattr(args, key, None)
        if value is not None:
            current[key] = value
    ranges = {
        "top_k": (1, 50),
        "session_top_k": (1, 20),
        "max_context_chars": (500, 12000),
        "max_hotset_updates": (1, 20),
        "max_session_context_chars": (800, 20000),
        "hotset_change_threshold": (1, 50),
        "hotset_min_prompt_interval": (1, 50),
    }
    for key, (minimum, maximum) in ranges.items():
        if key in current and not minimum <= int(current[key]) <= maximum:
            raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    if "probability_weight" in current or "impact_weight" in current:
        probability = float(
            current.get("probability_weight", load_config()["probability_weight"])
        )
        impact = float(current.get("impact_weight", load_config()["impact_weight"]))
        total = probability + impact
        if total <= 0:
            raise ValueError("Probability and impact weights must have a positive sum.")
        current["probability_weight"] = round(probability / total, 4)
        current["impact_weight"] = round(impact / total, 4)
    for key in (
        "metric_probability_weight",
        "max_metric_probability_blend",
        "basic_solution_priority_boost",
    ):
        if key in current and not 0 <= float(current[key]) <= 1:
            raise ValueError(f"{key} must be between 0 and 1.")
    write_json(CONFIG_PATH, current)
    return load_config()


def record_feedback(item_id: str, outcome: str) -> dict[str, Any]:
    mapping = {
        "triggered": "confirmed_triggered",
        "avoided": "confirmed_avoided",
    }
    if outcome not in mapping:
        raise ValueError("Legacy feedback outcome must be triggered or avoided.")
    return update_metric(item_id, mapping[outcome], source="explicit")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Proactive local Error Guard risk agent.")
    sub = result.add_subparsers(dest="action", required=True)
    profile = sub.add_parser("profile")
    profile.add_argument("--workspace", action="append", default=[])
    rank = sub.add_parser("recommend")
    rank.add_argument("--task", default="")
    rank.add_argument("--cwd", default=os.getcwd())
    rank.add_argument("--limit", type=int)
    rank.add_argument("--json", action="store_true")
    sub.add_parser("build-index")
    validate = sub.add_parser("validate")
    validate.add_argument("--json", action="store_true")
    hook_parser = sub.add_parser("hook")
    hook_parser.add_argument(
        "--event",
        required=True,
        choices=("session-start", "user-prompt", "pre-tool", "post-tool"),
    )
    config = sub.add_parser("configure")
    config.add_argument("--top-k", type=int)
    config.add_argument("--session-top-k", type=int)
    config.add_argument("--max-context-chars", type=int)
    config.add_argument("--max-hotset-updates", type=int)
    config.add_argument("--max-session-context-chars", type=int)
    config.add_argument("--hotset-change-threshold", type=int)
    config.add_argument("--hotset-min-prompt-interval", type=int)
    config.add_argument("--metric-probability-weight", type=float)
    config.add_argument("--max-metric-probability-blend", type=float)
    config.add_argument("--basic-solution-priority-boost", type=float)
    config.add_argument("--probability-weight", type=float)
    config.add_argument("--impact-weight", type=float)
    feedback = sub.add_parser("feedback")
    feedback.add_argument("--id", required=True)
    feedback.add_argument("--outcome", required=True, choices=("triggered", "avoided"))
    metric = sub.add_parser("metric")
    metric.add_argument("--id", required=True)
    metric.add_argument("--event", required=True, choices=sorted(METRIC_EVENTS))
    metric.add_argument("--amount", type=int, default=1)
    metrics = sub.add_parser("metrics")
    metrics.add_argument("--category", default="")
    solution = sub.add_parser("solution")
    solution.add_argument("--id", required=True)
    solution.add_argument("--no-track", action="store_true")
    solution_add = sub.add_parser("solution-add")
    solution_add.add_argument("--id", required=True)
    solution_add.add_argument("--command", required=True)
    return result


def validate_agent() -> dict[str, Any]:
    migrate_legacy_feedback()
    ensure_risk_index()
    rows = load_rows()
    ids = [row["id"] for row in rows]
    errors = []
    if len(ids) != len(set(ids)):
        errors.append("duplicate risk IDs")
    if any("System.Object[]" in row["tags"] for row in rows):
        errors.append("malformed PowerShell object-array token")
    if not any(row["source"] == "policy" for row in rows):
        errors.append("missing proactive policies")
    recommendation = recommend(
        "frontend vite temp file delete",
        os.getcwd(),
        limit=5,
        track=False,
    )
    if not recommendation:
        errors.append("empty recommendation")
    return {
        "ok": not errors,
        "risk_rows": len(rows),
        "profile_exists": PROFILE_PATH.exists(),
        "metric_shards": len(list(METRICS_ROOT.glob("*/*/*.json"))),
        "basic_solutions": len(list(SOLUTIONS_ROOT.glob("*/*/*.cmd"))),
        "errors": errors,
        "sample_ids": [row["id"] for row in recommendation],
    }


def main() -> int:
    args = parser().parse_args()
    migrate_legacy_feedback()
    if args.action == "profile":
        print(json.dumps(create_profile(args.workspace), indent=2))
    elif args.action == "recommend":
        items = recommend(args.task, args.cwd, args.limit)
        if args.json:
            print(json.dumps(items, indent=2))
        else:
            print(compact_context(items, "manual recommendation"))
    elif args.action == "build-index":
        print(f"Indexed {build_risk_index()} proactive risks.")
    elif args.action == "validate":
        result = validate_agent()
        print(json.dumps(result, indent=2) if args.json else result)
        return 0 if result["ok"] else 1
    elif args.action == "hook":
        return hook(args.event)
    elif args.action == "configure":
        print(json.dumps(configure(args), indent=2))
    elif args.action == "feedback":
        print(json.dumps(record_feedback(args.id, args.outcome), indent=2))
    elif args.action == "metric":
        print(
            json.dumps(
                update_metric(
                    args.id,
                    args.event,
                    amount=args.amount,
                    source="explicit",
                ),
                indent=2,
            )
        )
    elif args.action == "metrics":
        print(json.dumps(metrics_summary(args.category), indent=2))
    elif args.action == "solution":
        print(json.dumps(get_solution(args.id, track=not args.no_track), indent=2))
    elif args.action == "solution-add":
        print(json.dumps(register_solution(args.id, args.command), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
