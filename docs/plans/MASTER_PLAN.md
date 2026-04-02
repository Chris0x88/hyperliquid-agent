# HyperLiquid Trading System — Master Build Plan

> **Start every Claude Code session by reading this file + `docs/SYSTEM_ARCHITECTURE.md` + the relevant package `CLAUDE.md`.**

## What This System Is

A Financial Assistant + Trading Research Agent + Risk Manager. One product, three roles:
1. **Portfolio copilot** — Chris brings the thesis (petroleum engineering edge), system executes with discipline
2. **Research agent** — Proactively hunts for trades, challenges thesis, learns from outcomes
3. **Risk manager** — Autonomous stops, leverage management, ruin prevention. Chris delegates this entirely.

## The Architecture (read `docs/SYSTEM_ARCHITECTURE.md` for full diagrams)

```
CHRIS + CLAUDE CODE (Opus) ──writes──► data/thesis/*.json
                                           │
DAEMON (19 iterators, every tick) ──reads───┘──executes──► HyperLiquid
    │
    └──writes──► journal, signals, snapshots, learnings
                     │
REFLECT (meta-eval) ──reads───┘──evaluates──► playbook, adjustments
                     │
OPENCLAW AGENT ──reads───┘──discusses──► Chris via Telegram
                     │
COMMANDS BOT ──reads───┘──instant responses──► Chris via Telegram
```

## Current Phase: PHASE 2 (Daemon Switch + Immediate Fixes)

See `docs/plans/PHASE_2_DAEMON_SWITCH.md` for detailed checklist.

## Phase Overview

| Phase | Goal | Status |
|-------|------|--------|
| **Phase 1: Foundation** | Document everything, per-package CLAUDE.md, save learnings | DONE |
| **Phase 2: Daemon Switch** | Wire up the real workhorse, add MCP tools, failure alerting | NEXT |
| **Phase 3: REFLECT Loop** | Wire meta-evaluation, journal, playbook, weekly reports | Planned |
| **Phase 4: Self-Improving** | Auto-tuning, catalyst calendar, system health monitoring | Future |

## Critical Rules (from CLAUDE.md + learnings)

1. **NEVER touch `~/.openclaw/`** — that's Chris's entire AI agent ecosystem, not just this project
2. **Thesis files are the shared contract** — Chris writes conviction via Opus, daemon reads and executes
3. **OpenClaw agent is cheap model** — it reads and discusses, it's NOT the primary thesis writer
4. **Daemon safety** — always start in WATCH tier first, never go straight to REBALANCE on mainnet
5. **No fixed stops on thesis trades** — use invalidation-based exits, conviction sizing
6. **LONG or NEUTRAL only on oil** — never short
7. **Always add specific files to git** — never `git add -A`

## Session Workflow for Claude Code

```
1. Read docs/plans/MASTER_PLAN.md (this file)
2. Read docs/SYSTEM_ARCHITECTURE.md (system map)
3. Check which phase is current (see table above)
4. Read the phase-specific plan (docs/plans/PHASE_N_*.md)
5. Read the relevant package CLAUDE.md for the work
6. Do the work, run tests, commit
7. Update the phase plan with what was done
8. Update MASTER_PLAN.md if phase status changes
```

## Key Learnings (from this session, 2026-04-02)

1. **Heartbeat was blind for 21h** because `~/.hl-agent/wallets.json` didn't exist. Always verify infrastructure before assuming code works.
2. **Thesis was frozen for 3 days** because there was no write path — the scheduled task collected data but never wrote conviction updates. The feedback loop must be closed.
3. **OpenClaw agent had no auth profile** — it received messages but couldn't call any LLM. Always sync auth-profiles.json from the default agent.
4. **The daemon (19 iterators) is the real workhorse** — the heartbeat is a simplified stopgap missing 12 iterators of capability.
5. **REFLECT + Journal + Playbook are fully built** but only accessible via CLI, not wired into any automated loop.
6. **Three Telegram interfaces serve different purposes** — Commands Bot (instant, zero AI), OpenClaw Agent (AI chat), Alert Board (one-way heartbeat alerts). They're separate by design.
7. **HL API rate limits at ~3+ requests/second** — add 300ms delays between sequential calls.
8. **Module-level constants evaluated at import time** — use lazy resolution for anything that reads from disk (wallets, config).
