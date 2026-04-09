---
kind: plan
last_regenerated: 2026-04-09 14:08
plan_file: docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md
status: APPROVED 2026-04-09 with revisions. Building now.
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_05_STRATEGY_ENGINE

**Source**: [`docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md`](../../docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md)

**Status (detected)**: APPROVED 2026-04-09 with revisions. Building now.

## Preview

```
# Sub-system 5 — Oil Bot-Pattern Strategy Engine

**Slot in `OIL_BOT_PATTERN_SYSTEM.md`:** row 5. **The ONLY sub-system in
this stack that places trades.** Highest blast radius.

**Status:** APPROVED 2026-04-09 with revisions. Building now.

## REVISIONS after Chris feedback 2026-04-09

The first draft of this plan had per-instrument equity caps and fixed
leverage caps. Chris rejected that framing. The goal is to **compound
wealth as fast as possible without tanking the account** — which means
position size must scale nonlinearly with edge, not be clipped flat.

The revised design:

1. **No equity caps, no leverage caps.** Sizing is conviction-driven
   via a configurable `sizing_ladder` in `oil_botpattern.json`. Higher
   edge → larger notional AND higher leverage. Lower edge → smaller +
   less leverage. This is Druckenmiller-style conviction sizing, per
   `feedback_sizing_and_risk.md`. The ladder is a *norm*, not a cap.

2. **Circuit breakers replace caps.** Instead of per-position equity
   caps, the strategy has drawdown brakes that pause new entries when
   realised/unrealised loss crosses daily / weekly / monthly
   thresholds. This is the "don't tank the account" floor. Defaults:
   3% daily, 8% weekly, 15% monthly — all tunable in config. When a
   brake trips: daily auto-resets at UTC rollover, weekly/monthly
   require manual unpause.

```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
