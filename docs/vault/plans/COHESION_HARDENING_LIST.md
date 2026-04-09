---
kind: plan
last_regenerated: 2026-04-09 16:36
plan_file: docs/plans/COHESION_HARDENING_LIST.md
status: unknown
tags:
  - plan
---
# Plan: COHESION_HARDENING_LIST

**Source**: [`docs/plans/COHESION_HARDENING_LIST.md`](../../docs/plans/COHESION_HARDENING_LIST.md)

**Status (detected)**: unknown

## Preview

```
# Cohesion Hardening List — 2026-04-09

> **Phase D output** of `SYSTEM_REVIEW_HARDENING_PLAN.md` §7.
> **Derived from:** `BATTLE_TEST_LEDGER.md` (Phase B) +
> `TIMER_LOOP_AUDIT.md` (Phase C).
> **Cut-off:** HEAD `959022d` (Phase C commit).

## What this is

A prioritized hardening backlog. Every item is a concrete fix with a
score, a source pointer, and an acceptance criterion. **Chris works from
this list top-down.**

## Scoring rubric

```
Priority = (Impact × Likelihood) − Effort
  Impact     1 cosmetic · 2 degrades function · 3 can damage capital or trading thesis
  Likelihood 1 unusual sequence · 2 possible in normal ops · 3 will happen next time the code runs
  Effort     1 <1h · 2 half-day · 3 multi-session

  P0  score ≥ 5  → must fix before promoting any sub-system kill switch
  P1  score 3–4 → fix before battle-testing
  P2  score 1–2 → fix when convenient
  P3  score < 1 → note only
```

---

## P0 — must fix before promoting any sub-system kill switch
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
