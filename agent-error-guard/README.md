# Agent Error Guard

Agent Error Guard is a local, explainable risk-ranking and retry-protection
extension for Codex. It combines a one-time host profile, task-aware risk
ranking, bounded session hot-set updates, command guards, and an MCP interface.

## Introduction

Coding agents often fail for reasons that are specific to the current machine
and project: an unavailable tool, a locked file, a busy port, a destructive
command, an unchanged retry, or a long operation that should have been stopped.
General model knowledge cannot reliably predict these local conditions, while
loading a complete error history into every conversation wastes context.

Agent Error Guard provides a small local safety layer between those two
extremes. It keeps detailed error records outside the conversation, builds a
one-time host profile, and ranks only the risks that are relevant to the
current task. A bounded hot set gives Codex the most useful warnings before an
operation, while command guards remain active after the context budget is
exhausted.

The tool learns from sharded runtime evidence without hiding its decisions.
Each recommendation exposes its probability, impact, task similarity, and
observed outcome signals. Simple, low-risk errors may link to one validated
command in the basic-solution library, allowing the agent to use the known
answer without turning a routine lookup into a larger debugging exercise.

Agent Error Guard is not an autonomous repair system and does not bypass user
approval, operating-system permissions, or project ownership rules. It is an
offline, inspectable guardrail that helps coding agents avoid repeated,
destructive, expensive, and locally predictable mistakes.

## Install

Requirements:

- Python 3.10 or newer
- Codex CLI on `PATH`
- Python package `mcp` for the MCP server

Run:

```powershell
python .\install.py --workspace C:\path\to\project
```

The installer resolves the active Python executable and `CODEX_HOME` at runtime.
On Windows it selects a fixed non-system drive for state by default. Override
the location explicitly when needed:

```powershell
python .\install.py --state-dir <non-system-drive>:\AgentErrorGuard\state
```

Environment collection is explicit-only. It records operating-system and
toolchain versions plus marker-based workspace types. It does not scan ports,
services, credentials, source files, or entire drives.

The installer creates the profile once. A later install preserves it. Refresh
only after the host toolchain changes:

```powershell
python .\install.py --refresh-profile --workspace C:\path\to\project
```

## Context Behavior

Codex currently cannot delete one previously injected context item by ID.
Therefore the Hook never claims physical deletion. It injects:

- one short host baseline at session start;
- a versioned task hot set only when enough IDs change;
- at most three task updates and 3000 task-context characters per session.

Each newer hot-set version semantically replaces older versions. After the
budget is exhausted, command guards and MCP recommendations continue without
adding prompt context.

## Evidence And Ranking

Runtime evidence is stored outside the Skill as one JSON shard per risk ID:

```text
state/
  metrics/
    agent-tooling/
      20260812/
        ERR-20000101-001.json
```

The ranking model uses bounded Bayesian evidence from recommendations,
confirmed triggers, observed failures, repeat failures, corrected successes,
blocks, and solution outcomes. Evidence can adjust only a configured fraction
of estimated probability, so sparse or noisy samples cannot dominate task,
environment, recency, and impact signals.

Basic solutions are deliberately narrow. One eligible error links to one
non-destructive command of at most 240 characters. Chaining, redirection,
deletion, database mutation, network publication, privilege escalation,
destructive Git, and sensitive assignments are rejected.

Use MCP `metrics` for compact totals and `solution` for one command. The agent
does not load the entire metric or solution tree.

`inferred_correction_rate` is based on a later successful, token-similar
command after a recorded failure. It is operational evidence, not proof that
the underlying issue was fully resolved. Use explicit `solution_succeeded`
events for verified basic-solution outcomes.

## Uninstall

```powershell
python .\uninstall.py
```

Runtime state is retained by default. Set `AGENT_ERROR_GUARD_STATE` and add
`--remove-state` only when that exact state directory should also be removed.
