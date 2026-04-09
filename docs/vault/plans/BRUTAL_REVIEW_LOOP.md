---
kind: plan
last_regenerated: 2026-04-09 14:08
plan_file: docs/plans/BRUTAL_REVIEW_LOOP.md
status: : Proposed. Wedge 1 ready to start in parallel with Multi-Market
tags:
  - plan
---
# Plan: BRUTAL_REVIEW_LOOP

**Source**: [`docs/plans/BRUTAL_REVIEW_LOOP.md`](../../docs/plans/BRUTAL_REVIEW_LOOP.md)

**Status (detected)**: : Proposed. Wedge 1 ready to start in parallel with Multi-Market

## Preview

```
# Brutal Review Loop

> **Goal**: a periodic deep-honesty audit system that grades the codebase,
> the trading performance, and the decision quality. Distinct from
> Guardian's continuous shallow drift detection. Produces a brutal,
> specific, actionable report — not a summary.
>
> **Triggered by**: Chris's request 2026-04-09 after the manual deep-dive
> review revealed MASTER_PLAN staleness, lesson corpus pollution, and
> a journal schema mismatch — none of which Guardian had caught because
> they're all "is this still true?" questions, not "is this connected?" questions.
>
> **Status**: Proposed. Wedge 1 ready to start in parallel with Multi-Market
> Wedge 1.

---

## Why Guardian + Alignment are not enough

| Layer | What it catches | What it misses |
|---|---|---|
| **Guardian (continuous, every session)** | Orphans, parallel tracks, telegram-completeness gaps, plan/code reference mismatches, NEW: stale plan claims | Quality of trading decisions, codebase smells, doc-vs-reality drift on freeform claims, compounding technical debt, "is this idea still good?" questions |
| **Alignment (session-bookend ritual)** | Drift in docs vs running processes, daemon state, thesis freshness | Same blind spots as Guardian — both are *structural* checks |
| **Build log** | Records what shipped | Cannot grade what shipped |
| **Tests** | Asserts code does what it's supposed to | Cannot tell you if "what it's supposed to do" is the right thing to do |

The thing the manual 2026-04-09 deep-dive caught that none of the above
would have caught:

1. MASTER_PLAN.md said "lesson layer wiring deferred" when it had shipped.
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
