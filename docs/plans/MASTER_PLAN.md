# HyperLiquid Trading System — Master Plan

> **Start every session by reading this file + the relevant package `CLAUDE.md`.**
> **For system knowledge: `docs/wiki/`** | **For build history: `docs/wiki/build-log.md`**

## What This System Is

A Financial Assistant + Trading Research Agent + Risk Manager. One product, three roles:
1. **Portfolio copilot** — Chris brings the thesis (petroleum engineering edge), system executes with discipline
2. **Research agent** — Proactively hunts for trades, challenges thesis, learns from outcomes
3. **Risk manager** — Autonomous stops, leverage management, ruin prevention

## Current Phase: Hardening (audit fix execution)

The active work is closing the items in `docs/plans/AUDIT_FIX_PLAN.md`
(self-audit performed by the embedded agent on 2026-04-07). Phase 3
shipped via the autoresearch iterator before the audit ran.

For the deferred research-app build (parked), see
`docs/wiki/decisions/011-two-app-architecture-research-sibling.md` —
status `Proposed`, no implementation.

### What's Next After Hardening

- **Phase 4: Self-Improving** — Auto-tuning, catalyst calendar, convergence tracking
- See `docs/plans/PHASE_4_SELF_IMPROVING.md`
- **Optional: ADR-011 research-app** — only if Chris greenlights it

## What Has Shipped

### v4 (2026-04-05) — embedded agent runtime
- **Embedded agent runtime** — `cli/agent_runtime.py` ported from Claude Code (parallel tools, streaming, compaction, dream)
- Tool inventory: see `cli/agent_tools.py` (`TOOL_DEFS`)
- **Agent memory** — persistent `data/agent_memory/` with auto-loaded MEMORY.md
- **Self-improvement** — agent can read/edit its own code with user approval
- **Wiki documentation system** — single source of truth in `docs/wiki/`, MAINTAINING.md guide

### Phase 3 (REFLECT loop) — SHIPPED
The autoresearch daemon iterator now runs `ReflectEngine` on a regular
cycle and emits round-trip metrics into the daemon log and memory.
See `cli/daemon/iterators/autoresearch.py`. The Phase 3 plan document
remains as the historical spec — its `Status: Planned` field is stale.

### Audit hardening (2026-04-07) — IN PROGRESS
- F1 (agent self-knowledge), F2 (auto-watchlist), F3 (model selection
  honoured by dream/compaction), F5 (LIVE CONTEXT staleness), F7
  (tool execution verification), F8 (model logging), web_search fix
- F4 (context_harness verification) — verified, no fix needed
- F6 (liquidation cushion alerts) — new `liquidation_monitor` iterator
  in all 3 tiers, alert-only
- F9 (chat history continuity) — bot is already stateless; added
  startup diagnostic log line
- H4 (account snapshot dual-write) — new `account_snapshots` table in
  memory.db, dual-written from `account_collector` iterator

## Open Questions / Priorities

- SILVER and GOLD thesis stale — conviction auto-clamped
- Streaming not yet wired to Telegram output (helper exists, needs integration into main flow)
- Dream consolidation runs but doesn't yet use agent tools (marks complete only)
- Vault BTC positions are not included in `_fetch_account_state_for_harness()`
  (vault rebalancer manages it independently — minor gap, not yet scoped)

## Package Map

| Package | CLAUDE.md | Wiki |
|---------|-----------|------|
| `common/` | `common/CLAUDE.md` | [wiki/architecture.md](../wiki/architecture.md) |
| `cli/` | `cli/CLAUDE.md` | [wiki/components/telegram-bot.md](../wiki/components/telegram-bot.md) |
| `cli/daemon/` | `cli/daemon/CLAUDE.md` | [wiki/components/daemon.md](../wiki/components/daemon.md) |
| `modules/` | `modules/CLAUDE.md` | [wiki/components/conviction-engine.md](../wiki/components/conviction-engine.md) |
| `parent/` | `parent/CLAUDE.md` | [wiki/components/risk-manager.md](../wiki/components/risk-manager.md) |
| `agent/` | `agent/AGENT.md` + `SOUL.md` | [wiki/components/ai-agent.md](../wiki/components/ai-agent.md) |

## Session Workflow

```
1. Read this file (MASTER_PLAN.md)
2. Read the relevant package CLAUDE.md for your work
3. If needed, browse docs/wiki/ for deeper context
4. Do the work, run tests, commit
5. If architecture changed: update the relevant wiki page
6. Run /alignment at end of session to verify docs match reality
```

## Critical Rules

1. **NEVER touch `~/.openclaw/`** — Chris's entire AI agent ecosystem
2. **Thesis files are the shared contract** — Chris writes conviction via Opus, daemon reads and executes
3. **Coin name normalization** — xyz clearinghouse returns `xyz:BRENTOIL`, native returns `BTC`. Always handle both.
4. **LONG or NEUTRAL only on oil** — never short
5. **Always add specific files to git** — never `git add -A`
6. **Every position MUST have SL + TP on exchange**
