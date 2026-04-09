---
kind: plan
last_regenerated: 2026-04-09 16:36
plan_file: docs/plans/TIMER_LOOP_AUDIT.md
status: findings only. No code changes in this phase. Fixes queue into Phase D
tags:
  - plan
---
# Plan: TIMER_LOOP_AUDIT

**Source**: [`docs/plans/TIMER_LOOP_AUDIT.md`](../../docs/plans/TIMER_LOOP_AUDIT.md)

**Status (detected)**: findings only. No code changes in this phase. Fixes queue into Phase D

## Preview

```
# Timer & Loop Audit — 2026-04-09

**Phase:** C of SYSTEM_REVIEW_HARDENING_PLAN.md
**Scope:** every loop, timer, and scheduled job that touches the trading system.
**Emphasis per user:** *"track and check timer and loops for when processes run,
how they run, sequencing, is it common sense... processes that interweave and
not just waterfall code structure alone."*
**Status:** findings only. No code changes in this phase. Fixes queue into Phase D
(`COHESION_HARDENING_LIST.md`).

---

## 1. Execution model summary

The system has **three independent processes** running concurrently under launchd,
each with its own loop cadence, plus **two additional out-of-process writers** that
can touch the same on-disk state.

### 1.1 Processes under launchd

| Label | Entry point | Cadence | KeepAlive |
|-------|-------------|---------|-----------|
| `com.hyperliquid.daemon`    | `.venv/bin/python -m cli.main daemon start --tier watch --mainnet --tick 120` | continuous loop, 120 s tick | `KeepAlive=true` |
| `com.hyperliquid.telegram`  | `.venv/bin/python -m cli.telegram_bot` | continuous polling (separate process; command handlers fire on user input) | `KeepAlive=true` |
| `com.hyperliquid.heartbeat` | `.venv/bin/python scripts/run_heartbeat.py` | **launchd-driven 120 s `StartInterval` one-shot** — launchd respawns the script every 120 s | `KeepAlive=false` |

These three launchd jobs share a single filesystem tree under
`/Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/` and a single SQLite database
at `data/memory/memory.db`. **There is no lock coordination between the three
processes.** They rely on atomic-rename discipline, SQLite's own lock, and
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
