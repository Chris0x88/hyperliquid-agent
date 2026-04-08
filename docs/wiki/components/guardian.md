# Guardian Angel

**Purpose:** Dev-side meta-system that prevents architectural drift and surfaces recurring pain while Claude Code is working in the repo.

**Scope:** Dev-only. Never runs in the trading daemon. Never touches agent runtime, agent prompts, auth, or runtime data paths.

## Architecture

Three tiers:

1. **Silent workers** (pure Python stdlib): `guardian/cartographer.py`, `guardian/drift.py`, `guardian/friction.py`, `guardian/gate.py`, `guardian/sweep.py`
2. **Background sub-agents** (dispatched via the Agent tool during active sessions): runs `guardian.sweep.run_sweep()` then synthesizes a natural-language report
3. **Surface point** (hooks + Claude's judgment): `.claude/hooks/session_start.py`, `.claude/hooks/pre_tool_use.py`

See ADR-014 for the full rationale.

## Key files

| File | Responsibility |
|---|---|
| `guardian/cartographer.py` | Scans the repo, builds `inventory.json` + `map.mmd` |
| `guardian/drift.py` | Detects orphans, parallel tracks, Telegram gaps, plan/code mismatches |
| `guardian/friction.py` | Reads user logs, detects repeated corrections and recurring errors |
| `guardian/gate.py` | PreToolUse rule dispatcher. Registered rules: `telegram-completeness`, `parallel-track-warning`, `recent-delete-guard`, `stale-adr-guard` |
| `guardian/sweep.py` | Runs the tier-1 pipeline end-to-end, writes `current_report.md` |
| `guardian/guide.md` | User-facing contract document |
| `.claude/hooks/session_start.py` | SessionStart hook — injects state into Claude's context, lazy sweep |
| `.claude/hooks/pre_tool_use.py` | PreToolUse hook — runs gate.py checks |
| `.claude/commands/guide.md` | `/guide` slash command |
| `.claude/commands/guardian.md` | `/guardian` manual sweep command |

## State files (gitignored)

| File | Contents |
|---|---|
| `guardian/state/inventory.json` | Current wiring inventory |
| `guardian/state/inventory.prev.json` | Previous inventory (for drift diff) |
| `guardian/state/map.mmd` | Mermaid graph |
| `guardian/state/map.md` | Summary stats |
| `guardian/state/drift_report.{json,md}` | Drift findings |
| `guardian/state/friction_report.{json,md}` | Friction findings |
| `guardian/state/current_report.md` | Compiled report read by SessionStart hook |
| `guardian/state/sweep.log` | Append-only sweep log |

## Kill switches

See `guardian/guide.md` for the full table. Global off: `GUARDIAN_ENABLED=0`.

## Testing

```bash
cd agent-cli && .venv/bin/python -m pytest guardian/tests/ -x -q
```

Fixtures live in `guardian/tests/fixtures/`. Tests use real tmp dirs (no filesystem mocks).

## Related documents

- ADR-014 — `docs/wiki/decisions/014-guardian-system.md`
- Design spec — `docs/superpowers/specs/2026-04-09-guardian-angel-design.md`
- Implementation plan — `docs/superpowers/plans/2026-04-09-guardian-angel.md`
- Phase status — `docs/plans/GUARDIAN_PLAN.md`
- User guide — `guardian/guide.md`
