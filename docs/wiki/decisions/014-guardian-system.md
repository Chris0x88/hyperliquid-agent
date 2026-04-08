# ADR-014: Guardian Angel — Dev-Side Meta-System

**Status:** Accepted
**Date:** 2026-04-09
**Supersedes:** none

## Context

The HyperLiquid_Bot codebase has grown past the point where any single person (or Claude session) can hold the full architecture in working memory. Chris reported six recurring failure modes:

1. Parallel tracks — new work built without integrating with existing work
2. UI-completeness gap — features shipping in code but not reaching Telegram
3. Recurring fights becoming invisible signals (e.g., repeatedly canceling auto-set SL/TPs)
4. Inability to see architectural connections visually
5. Orphaning of old good work during scope pivots
6. Reactive-only Claude behavior — Chris leads every insight

The 2026-04-07 hardening postmortem documented a concrete instance of failure mode 5 + operating on stale state: a ~600-line ADR was drafted against a repo picture that was already obsolete, wasting a brainstorming pass.

## Decision

Build Guardian Angel — a dev-side meta-system that:

1. Runs **only** while a Claude Code dev session is active. Never on cron, never in the trading agent's runtime loop, never pushing to Telegram.
2. Uses a **three-tier architecture**:
   - **Tier 1 — silent workers** (pure Python, stdlib only): `cartographer.py`, `drift.py`, `friction.py`, `gate.py`
   - **Tier 2 — background sub-agents** (dispatched via the Agent tool during active sessions, `run_in_background=true`) for natural-language synthesis
   - **Tier 3 — surface point** (SessionStart hook + PreToolUse gate): Claude reads the report silently and surfaces P0 findings in natural language, or says nothing
3. Lives entirely under `agent-cli/guardian/` + `agent-cli/.claude/hooks/` + `agent-cli/.claude/commands/`.
4. Has **zero external dependencies** (Python stdlib + Mermaid for graph output).
5. Has **kill switches on every component** (one env var each, plus `GUARDIAN_ENABLED` as global override).
6. Is **read-only** on all runtime trading data paths.

## Consequences

### Positive
- Parallel-track creation is mechanically blocked by the PreToolUse gate.
- Telegram UI-completeness is enforced by the gate rather than by human memory.
- The `/tmp/guardian_session_reads.txt` tracker + `stale-adr-guard` rule mechanically prevents the 2026-04-07 failure mode.
- Recurring user fights (SL/TP cancel loops) become visible at session start without requiring Chris to remember to check.
- Sub-agent synthesis gives Chris proactive insights without token cost when he's not working.

### Negative
- Adds ~1500 lines of Python and 6 new config files to the repo.
- First session after a long absence takes ~5s longer while the lazy sweep runs.
- Gate rules can produce false positives (all kill-switchable).
- Sub-agent dispatch costs a small but non-zero number of tokens per stale session.

## Alternatives Considered

### Alternative 1: Scheduled cron / `scheduled-tasks` MCP
Rejected. Chris explicitly said "the agent is a trader, not a self-reviewer." Running Guardian on cron would piggyback on the trading agent's operational footprint and introduce a separate autonomous Claude invocation path. In-session dispatch keeps Guardian entirely within the dev workflow.

### Alternative 2: Slash-command-heavy interface (`/map`, `/drift`, `/friction`, `/suggest`)
Rejected. Chris said "I don't want to have to run those commands." Commands-you-must-remember add cognitive load rather than reducing it. The only user-facing slash commands are `/guide` (read the contract) and `/guardian` (force a refresh).

### Alternative 3: Inline in the trading daemon
Rejected. The daemon is load-bearing and any modification risks trading safety. Guardian must not share a process space or runtime loop with trading code.

## Implementation

See:
- Design spec: `docs/superpowers/specs/2026-04-09-guardian-angel-design.md`
- Implementation plan: `docs/superpowers/plans/2026-04-09-guardian-angel.md`
- Phase status table: `docs/plans/GUARDIAN_PLAN.md`
- User guide: `guardian/guide.md`

## Risks

- **False positives in gate rules** — mitigated by per-rule kill switches and gradual rollout (one rule enabled per commit).
- **Sub-agent token costs** — mitigated by lazy dispatch (only when state is stale) and a 5000-token budget cap per sub-agent run.
- **State file corruption** — mitigated by `rm -rf guardian/state/` as a safe reset; the next sweep rebuilds from scratch.
- **Hook breakage blocking Claude Code** — mitigated by fail-open exception handling in both hooks (`session_start.py` and `pre_tool_use.py`).

## Supersession

This ADR is self-contained and supersedes nothing. If Guardian is ever retired or restructured, a successor ADR should reference this one.
