---
kind: plan
last_regenerated: 2026-04-09 14:08
plan_file: docs/plans/PHASE_4_SELF_IMPROVING.md
status: unknown
tags:
  - plan
---
# Plan: PHASE_4_SELF_IMPROVING

**Source**: [`docs/plans/PHASE_4_SELF_IMPROVING.md`](../../docs/plans/PHASE_4_SELF_IMPROVING.md)

**Status (detected)**: unknown

## Preview

```
# Phase 4: Self-Improving System

> **Status: Future**
> **Depends on: Phase 3 complete (REFLECT wired)**

## Goal

The system learns from outcomes and improves with less human direction. Chris sets the thesis, the system handles everything else and gets better at it over time.

## Components

### 1. REFLECT adapter auto-tunes parameters
- `ReflectAdapter.adapt()` suggests parameter changes based on metrics
- `DirectionalHysteresis` prevents oscillation (require 2 consecutive same-direction)
- `ConvergenceTracker` gates changes (only apply if overall performance improving)
- Guardrails: radar_score [120-280], pulse_confidence [40-95], daily_loss_limit [$50-$5000]

### 2. Playbook-informed filtering
- If a (instrument, signal_source) combo has <40% win rate over 20+ trades, stop taking those entries
- If a combo has >70% win rate, increase conviction multiplier for those signals
- This is emergent strategy — the system discovers what works

### 3. Catalyst deleverage calendar
- Wire `CatalystDeleverage` iterator with event calendar
- Known events: Trump deadlines, OPEC meetings, contract rolls, NFP, CPI
- 6h before event: alert Chris
- 1h before event: auto-reduce leverage by configured %
- Calendar stored in `data/calendar/` (already built)

### 4. System health monitoring
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
