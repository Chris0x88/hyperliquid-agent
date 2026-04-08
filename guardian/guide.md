# Guardian Angel — User Guide

> This is the living contract between Chris and Guardian. If it's not documented here, Guardian doesn't do it.

## What is Guardian?

A dev-side meta-system that watches the HyperLiquid_Bot repo while Claude Code is working in it. It runs only during active Claude Code sessions. It does not run on cron, does not touch the trading agent, and does not push anything to Telegram.

## What does it do?

1. **Cartographer** scans the repo every session start and builds a wiring inventory (modules, imports, Telegram commands, daemon iterators).
2. **Drift Detector** (Phase 2+) compares snapshots and flags orphans, parallel tracks, plan/code mismatches, and Telegram gaps.
3. **Review Gate** (Phase 3+) blocks destructive or incomplete actions via a PreToolUse hook.
4. **Friction Surfacer** (Phase 4+) reads user logs and detects recurring pain patterns.
5. **Advisor** (Phase 5+) synthesizes everything into a natural-language report.
6. **Guide** (this document) — the contract.

## When does it run?

- **SessionStart:** reads the current report, injects a compact summary into Claude's context.
- **PreToolUse (Phase 3+):** runs gate checks on Edit/Write/Bash calls.
- **Mid-session sub-agent dispatch (Phase 5+):** when the conversation suggests deeper analysis would help.
- **Never otherwise.** When you close Claude Code, Guardian sleeps.

## How do I read a report?

`guardian/state/current_report.md` is the single source of truth. It has:
- A one-paragraph summary of repo state
- P0 findings (action required)
- P1 findings (investigate soon)
- Questions worth asking

## Slash commands

| Command | What it does |
|---|---|
| `/guide` | Prints this guide |
| `/guardian` | Force a guardian sweep now (Phase 5+) |

## Kill switches

Every component has an environment variable kill switch. Set to `0` to disable.

| Scope | Env var |
|---|---|
| Global | `GUARDIAN_ENABLED` |
| Cartographer | `GUARDIAN_CARTOGRAPHER_ENABLED` |
| Drift | `GUARDIAN_DRIFT_ENABLED` |
| Friction | `GUARDIAN_FRICTION_ENABLED` |
| Gate (all rules) | `GUARDIAN_GATE_ENABLED` |
| Gate — Telegram completeness | `GUARDIAN_RULE_TELEGRAM_COMPLETENESS` |
| Gate — Parallel track | `GUARDIAN_RULE_PARALLEL_TRACK` |
| Gate — Recent delete guard | `GUARDIAN_RULE_RECENT_DELETE` |
| Gate — Stale ADR guard | `GUARDIAN_RULE_STALE_ADR` |
| Sub-agent dispatch | `GUARDIAN_SUBAGENTS_ENABLED` |

To silence Guardian entirely for one session:
```bash
GUARDIAN_ENABLED=0 claude
```

## What Guardian never touches

- `cli/agent_runtime.py`
- `agent/AGENT.md`, `agent/SOUL.md`
- `~/.openclaw/`
- Daemon iterators
- `data/thesis/`, `data/agent_memory/`, `data/feedback.jsonl`
- Telegram bot runtime
- Existing wiki pages, ADRs, plans (only additive changes)

## Current status

**Phase 1 — Foundation.** Cartographer + SessionStart hook (read-only) shipped. No gate, no sub-agents, no drift detection yet.

See `docs/plans/GUARDIAN_PLAN.md` for the phase status table.
