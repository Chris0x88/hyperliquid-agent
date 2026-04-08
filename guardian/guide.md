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

All 6 phases shipped.

- **Phase 1 — Foundation:** cartographer (imports + Telegram + iterators), SessionStart hook, state directory, guide stub.
- **Phase 2 — Drift:** orphan detection, parallel-track detection, Telegram completeness gap reporting, plan/code mismatch, report writer.
- **Phase 3 — Gate:** PreToolUse hook with four rules — telegram-completeness, parallel-track-warning, recent-delete-guard, stale-adr-guard. Each individually kill-switchable.
- **Phase 4 — Friction:** repeated-correction pattern, recurring-error pattern, friction report builder + writer.
- **Phase 5 — Orchestrator + sub-agents:** `sweep.py` runs the full tier-1 pipeline; SessionStart hook runs a lazy sweep when state is stale; `/guardian` slash command dispatches a background sub-agent for natural-language synthesis.
- **Phase 6 — Lock-in:** this guide, ADR-014, `docs/wiki/components/guardian.md`, `docs/plans/GUARDIAN_PLAN.md`, cross-links in MASTER_PLAN.md and root CLAUDE.md.

See `docs/plans/GUARDIAN_PLAN.md` for the full status table with commit hashes.

## How to extend Guardian

- **Add a drift rule:** write a new function in `guardian/drift.py`, call it from `build_drift_report()`, write a test in `guardian/tests/`.
- **Add a friction pattern:** write a new detector in `guardian/friction.py`, call it from `build_friction_report()`, write a test.
- **Add a gate rule:** write a new function in `guardian/gate.py` decorated with `@register_rule("rule-name")`, add a kill switch env var, write a test.
- **Add a new kill switch:** document it in the Kill Switches table above.

## Known limits

- Guardian only runs while a Claude Code session is active. It cannot observe drift or friction that occurs outside of sessions.
- The parallel-track-warning rule uses a 60% Jaccard token similarity threshold and can produce false positives on files that legitimately share naming conventions.
- The stale-adr-guard rule tracks session reads via `/tmp/guardian_session_reads.txt`. On multi-user systems this could theoretically be racy — acceptable for a single-user dev setup.
- The friction surfacer assumes entries in `feedback.jsonl` have `type: "user_correction"` and `subject` fields; entries in other schemas are ignored. Extend `detect_repeated_corrections()` if the schema evolves.

## Failure modes

See `docs/wiki/decisions/014-guardian-system.md` §Risks for the full list.
