# HyperLiquid Trading System — Master Build Plan v2

> **Previous version archived at `MASTER_PLAN_v1.md`**
> **Start every session by reading this file + `docs/SYSTEM_ARCHITECTURE_v3.md` + the relevant package `CLAUDE.md`.**

## What This System Is

A Financial Assistant + Trading Research Agent + Risk Manager. One product, three roles:
1. **Portfolio copilot** — Chris brings the thesis (petroleum engineering edge), system executes with discipline
2. **Research agent** — Proactively hunts for trades, challenges thesis, learns from outcomes
3. **Risk manager** — Autonomous stops, leverage management, ruin prevention. Chris delegates this entirely.

## The Architecture (v3 — Agentic Tool-Calling)

Read `docs/SYSTEM_ARCHITECTURE_v3.md` for full mermaid diagrams. Previous versions at `_v1.md` and `_v2.md` for history.

```
CHRIS + CLAUDE CODE (Opus) ──writes──► data/thesis/*.json
                                           │
DAEMON (WATCH tier, 120s launchd) ──reads──┘──monitors──► HyperLiquid
                                           │
TELEGRAM BOT ──25 commands + AI router─────┘
    │
    └──free text──► AI AGENT (telegram_agent.py)
                        │
                        ├──9 tools (7 read, 2 write w/ approval)──► HyperLiquid
                        ├──context pipeline (account, technicals, thesis, memory)
                        └──OpenRouter (18 models, dual-mode tool calling)

VAULT REBALANCER (hourly launchd) ──BTC Power Law──► HyperLiquid
```

## Architecture Evolution

| Version | Date | Shift | Doc |
|---------|------|-------|-----|
| v1 | 2026-03 | Daemon-centric: 19 iterators, REFLECT, 4-phase plan | `SYSTEM_ARCHITECTURE.md` |
| v2 | 2026-04-02 AM | Interface-first: rich context, model selector, formatting | `SYSTEM_ARCHITECTURE_v2.md` |
| v3 | 2026-04-02 PM | Agentic: 9 tools, dual-mode calling, approval gates | `SYSTEM_ARCHITECTURE_v3.md` |
| v3.2 | 2026-04-04 | Interactive menu + hardening: buttons, write commands, protection chain, health window, renderer | (this doc) |

Key pattern: each version ADDS a capability layer. v1 daemon → v2 context → v3 tools → v3.2 interactive UX + infrastructure hardening.

## Current Phase Status

| Phase | Goal | Status |
|-------|------|--------|
| **Phase 1: Foundation** | Heartbeat, thesis contract, conviction engine, single-instance | ✅ DONE |
| **Phase 1.5: Agentic Interface** | Telegram 31 commands, AI agent with tools, context pipeline, model selector, centralized watchlist | ✅ DONE |
| **Phase 2: Daemon Switch** | Replace heartbeat with full daemon (WATCH tier, 120s tick, mainnet) | ✅ DONE — tick 1728+ as of 2026-04-04 |
| **Phase 2.5: Interactive UX + Hardening** | Button menu, write commands, signal engine, protection chain, health window, renderer interface | ✅ DONE |
| **Phase 3: REFLECT Loop** | Wire meta-evaluation, journal, playbook into daemon | NEXT |
| **Phase 4: Self-Improving** | Auto-tuning, catalyst calendar, convergence tracking | Future |

## What's Running Right Now

| Process | Script | Schedule | Purpose |
|---------|--------|----------|---------|
| **Daemon** | `cli/daemon/clock.py` | launchd 120s, WATCH tier | 19 iterators, protection chain (4), health window, 10 market snapshots |
| Commands Bot | `cli/telegram_bot.py` | background | 31 handlers + interactive menu + AI router |
| AI Agent | `cli/telegram_agent.py` | on-demand | OpenRouter + 12 tools, triple-mode calling |
| Vault Rebalancer | `scripts/run_vault_rebalancer.py` | launchd hourly | BTC Power Law (not currently active) |

Note: Heartbeat (`common/heartbeat.py`) has been replaced by the daemon. Heartbeat plist still exists as fallback.

## What's Built But NOT Running

| System | Location | Why Not Running |
|--------|----------|-----------------|
| REFLECT meta-evaluation | `modules/reflect_engine.py` | CLI only, not wired to daemon |
| Journal + Memory engines | `modules/journal_engine.py`, `memory_engine.py` | CLI only |
| 22 strategies | `strategies/` | Only power_law_btc active |
| Quoting engine | `quoting_engine/` | Not relevant to current use case |

## Phase 2: Daemon Switch (NEXT)

See `docs/plans/PHASE_2_DAEMON_SWITCH.md` for detailed checklist.

**Goal:** Replace simplified heartbeat with full daemon orchestration.
- All 19 iterators active in ordered execution
- Start in WATCH tier, graduate to REBALANCE after 24h validation
- Daemon writes thesis updates automatically (closes the stale-thesis gap)
- Heartbeat becomes fallback, daemon becomes primary

## Package Map (read relevant CLAUDE.md before working)

| Package | CLAUDE.md | Files | Role |
|---------|-----------|-------|------|
| `common/` | `common/CLAUDE.md` | 31 | Shared utilities, heartbeat, thesis, conviction, context harness, market snapshots |
| `cli/` | `cli/CLAUDE.md` | 33+ | Commands, telegram bot, AI agent, agent tools, MCP server |
| `cli/daemon/` | `cli/daemon/CLAUDE.md` | 25 | Full daemon: clock, context, 19 iterators, 3 tiers |
| `modules/` | `modules/CLAUDE.md` | 41 | 7 engines (REFLECT, GUARD, RADAR, PULSE, JOURNAL, MEMORY, APEX) + utilities |
| `parent/` | `parent/CLAUDE.md` | 7 | Exchange layer: hl_proxy (17 importers), risk manager |
| `openclaw/` | `openclaw/CLAUDE.md` | 10 | Agent workspace: AGENT.md, SOUL.md, TOOLS.md |

## Session Workflow for Claude Code

```
1. Read docs/plans/MASTER_PLAN.md (this file)
2. Read docs/SYSTEM_ARCHITECTURE_v3.md (latest architecture)
3. Check which phase is current (see table above)
4. Read the phase-specific plan (docs/plans/PHASE_N_*.md)
5. Read the relevant package CLAUDE.md for the work
6. Do the work, run tests, commit
7. If architecture changed: update SYSTEM_ARCHITECTURE_v3.md (or create v4)
8. Run /alignment at end of session to sync docs
```

## Critical Rules (from CLAUDE.md + learnings)

1. **NEVER touch `~/.openclaw/`** — Chris's entire AI agent ecosystem
2. **Thesis files are the shared contract** — Chris writes conviction via Opus, daemon reads and executes
3. **Archive, never replace** — old plans and architecture docs stay for track record
4. **Coin name normalization** — xyz clearinghouse returns `xyz:BRENTOIL`, native returns `BTC`. Always handle both forms.
5. **No fixed stops on thesis trades** — invalidation-based exits, conviction sizing
6. **LONG or NEUTRAL only on oil** — never short
7. **Always add specific files to git** — never `git add -A`
8. **HL API rate limits** — 300ms delays between sequential calls
9. **Module-level constants evaluated at import time** — use lazy resolution for disk reads

## Key Learnings

### From oil trade loss (2026-04-02):
- Heartbeat was blind 21h (wallets.json missing)
- Thesis frozen 3 days (no write path)
- OpenClaw agent had no auth profile
- 636 consecutive failures with no notification
- Infrastructure/plumbing failures, not strategy failures

### From v2/v3 build (2026-04-02):
- Interface-first approach more productive than daemon-first
- Rich AI context (positions + technicals + thesis) makes cheap models useful
- Dual-mode tool calling lets free models use tools via text parsing
- Approval gates via Telegram buttons = secure write operations
- Per-section CLAUDE.md files must stay current or sessions start confused
