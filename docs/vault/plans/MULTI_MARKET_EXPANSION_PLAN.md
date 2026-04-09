---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/MULTI_MARKET_EXPANSION_PLAN.md
status: : Proposed. Wedge 1 ready to start after the current Oil Bot
tags:
  - plan
---
# Plan: MULTI_MARKET_EXPANSION_PLAN

**Source**: [`docs/plans/MULTI_MARKET_EXPANSION_PLAN.md`](../../docs/plans/MULTI_MARKET_EXPANSION_PLAN.md)

**Status (detected)**: : Proposed. Wedge 1 ready to start after the current Oil Bot

## Preview

```
# Multi-Market Expansion Plan

> **Goal**: decouple the trading core from oil-shaped assumptions so any
> HyperLiquid market can be promoted from "tracked" to "thesis-driven" via
> configuration, not code edits.
>
> **Status**: Proposed. Wedge 1 ready to start after the current Oil Bot
> Pattern System sub-system 6 completes.

---

## Why this is needed

The codebase is currently shaped around oil + BTC because that's where Chris's
edge began. Specifically, these assumptions are baked in:

| Assumption | Where it lives | Generalisation challenge |
|---|---|---|
| `LONG or NEUTRAL only on oil` | `common/conviction_engine.py:check_oil_direction_guard()` + CLAUDE.md rule #4 | Other markets have different direction bias |
| Approved markets list `BTC, BRENTOIL, CL, GOLD, SILVER` | CLAUDE.md rule #2; risk_caps.json; thesis directory naming | Hardcoded list is the choke point |
| `xyz:` prefix handling | Recurring footgun across the codebase | Already partly generalised via `_coin_matches()` |
| BRENTOIL roll buffer | `conviction_engine.is_near_roll_window()` (3rd–12th business day) | Roll calendars differ per instrument family |
| Catalyst severity rules | `data/config/news_rules.yaml` regex patterns are oil-flavoured | Each market needs its own catalyst dictionary |
| Supply ledger | `modules/supply_ledger.py` is shaped around physical oil disruptions | Different markets need different signal types |
| oil_botpattern subsystem | The whole subsystem is named, scoped, and gated for oil | Generalises to "any market with cascade-prone bot patterns" |
| Heatmap defaults | `data/config/heatmap.json` defaults to `["BRENTOIL"]` | Easy fix — already configurable |
| Tier system + auto-watchlist | Auto-watchlist tracks any open position but doesn't promote it to thesis-driven | This is the hook the expansion plugs into |

The fact that auto-watchlist already tracks any position is the architectural
crack to expand through: the system *can* see other markets, it just can't
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
