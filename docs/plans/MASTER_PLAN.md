# HyperLiquid Trading System — Master Plan

> **Start every session by reading this file + the relevant package `CLAUDE.md`.**
> **For system knowledge: `docs/wiki/`** | **For build history: `docs/wiki/build-log.md`**

## What This System Is

A Financial Assistant + Trading Research Agent + Risk Manager. One product, three roles:
1. **Portfolio copilot** — Chris brings the thesis (petroleum engineering edge), system executes with discipline
2. **Research agent** — Proactively hunts for trades, challenges thesis, learns from outcomes
3. **Risk manager** — Autonomous stops, leverage management, ruin prevention

## Current Phase: Phase 3 — REFLECT Loop

**Goal:** Wire meta-evaluation, journal, and playbook into the daemon.

Modules exist (`modules/reflect_engine.py`, `journal_engine.py`, `memory_engine.py`) but are CLI-only. Need daemon iterators to run them automatically.

See `docs/plans/PHASE_3_REFLECT_LOOP.md` for detailed plan.

### What's Next After Phase 3

- **Phase 4: Self-Improving** — Auto-tuning, catalyst calendar, convergence tracking
- See `docs/plans/PHASE_4_SELF_IMPROVING.md`

## Open Questions / Priorities

- SILVER and GOLD thesis stale (>4 days) — conviction auto-clamped
- Liquidity regime: dangerous — monitor closely
- REFLECT wiring: which iterators, what tier, what frequency?

## Package Map

| Package | CLAUDE.md | Wiki |
|---------|-----------|------|
| `common/` | `common/CLAUDE.md` | [wiki/architecture.md](../wiki/architecture.md) |
| `cli/` | `cli/CLAUDE.md` | [wiki/components/telegram-bot.md](../wiki/components/telegram-bot.md) |
| `cli/daemon/` | `cli/daemon/CLAUDE.md` | [wiki/components/daemon.md](../wiki/components/daemon.md) |
| `modules/` | `modules/CLAUDE.md` | [wiki/components/conviction-engine.md](../wiki/components/conviction-engine.md) |
| `parent/` | `parent/CLAUDE.md` | [wiki/components/risk-manager.md](../wiki/components/risk-manager.md) |
| `openclaw/` | `openclaw/CLAUDE.md` | [wiki/decisions/003-openclaw-bypass.md](../wiki/decisions/003-openclaw-bypass.md) |

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
