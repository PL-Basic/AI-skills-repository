---
name: wifi-manager-error-guard
description: Proactively prevent likely local failures and record agent mistakes while delivering Wifi Manager frontend, backend, firmware, database, browser, and operations work. Use before every Wifi Manager work session, immediately after any error, and before retrying a failed command.
---

# Wifi Manager Error Guard

Use progressive disclosure. Never read the complete index or all records.

## Runtime

SessionStart injects one short host baseline. UserPromptSubmit emits a versioned
task hot set only when enough risk IDs change, with a hard per-session update
and character budget. A newer version semantically replaces earlier versions;
Codex does not currently support deleting one prior injected item by ID.

PreToolUse remains active after the context budget is exhausted. MCP provides
manual recommendation, explanation, profile, configuration, and feedback.
The host profile is refreshed only when the user requests it or the toolchain
changes.

Metrics are independent runtime shards under the configured state directory.
Never load all shards. Use the `metrics` MCP tool for compact totals or read one
risk ID shard. Automatic observations and explicit confirmations are stored
separately; treat explicit outcomes as stronger evidence.

Basic solutions are one-line, non-destructive commands under
`references/solutions/<category>/<bucket>/`. Error records contain only a
relative link. Read one solution through MCP only when a hot-set entry shows
`solution=<ERR-ID>`. Do not scan the solution tree.

## Failure Workflow

1. Stop after the first failure.
2. Search `references/index.tsv` using the exact signature, command, repository,
   and path.
3. Read only one likely record under `references/records/`.
4. Update the existing record for a known signature; create one complete record
   for a new signature.
5. Change an evidenced condition before retrying.
6. After the corrected operation fails identically, do not make a third blind
   attempt.
7. Ask the user when resolution depends on unclear ownership, permissions,
   locks, external services, database state, serial hardware, network state, or
   user-managed processes.

## Hard Rules

- Never persist passwords, tokens, cookies, keys, verification codes, or full
  sensitive responses.
- Never delete firmware build output, cache, binaries, or release artifacts.
- Check and stop the owned frontend process before treating undeletable
  frontend temporary files as ACL failures.
- Protect dirty worktrees. Do not run destructive Git operations, broad
  staging, or push without explicit authorization.
- Bound recursive operations to exact paths with confirmed ownership.
- Start a long build or integration test once and monitor it.

## Commands

Resolve scripts relative to this Skill. Use process-only execution-policy bypass
when the host blocks the PowerShell tool.

```powershell
python scripts/risk-agent.py recommend --task '<task>' --cwd '<workspace>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/error-guard.ps1 search -Query '<signature>' -Limit 5
```

Use `get`, `update`, `new`, and `add` only after a search. Use `validate`,
`reindex`, and `stats` only while maintaining this Skill.

Use metric outcomes consistently:

- `confirmed_triggered`: the risk definitely occurred.
- `confirmed_avoided`: the recommendation definitely prevented it.
- `solution_succeeded`: the linked one-line solution resolved the basic error.
- `repeat_failure`: the same problem recurred after an attempted correction.

Do not mark a solution successful from an unverified command exit alone.
