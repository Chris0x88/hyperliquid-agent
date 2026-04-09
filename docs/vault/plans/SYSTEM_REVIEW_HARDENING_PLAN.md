---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/SYSTEM_REVIEW_HARDENING_PLAN.md
status: Ready to execute — **start in a fresh session**, not this one.
tags:
  - plan
---
# Plan: SYSTEM_REVIEW_HARDENING_PLAN

**Source**: [`docs/plans/SYSTEM_REVIEW_HARDENING_PLAN.md`](../../docs/plans/SYSTEM_REVIEW_HARDENING_PLAN.md)

**Status (detected)**: Ready to execute — **start in a fresh session**, not this one.

## Preview

```
# System Review & Hardening Plan

**Authored:** 2026-04-09 evening (Brisbane)
**Status:** Ready to execute — **start in a fresh session**, not this one.
**Purpose:** Bring the repo, docs, `MASTER_PLAN.md`, and the obsidian vault
back into alignment with reality after the massive 2026-04-09 shipping
burst, and then conduct a full system review of everything that's **built
but not yet battle-tested** — with a focus on **timers, loops, sequencing,
and common-sense cadence**.

> **Read the whole document before starting.** It is deliberately long
> because the work is big and the next session must not start guessing.
> Every phase has an acceptance criterion. Every phase has a known-gotcha
> list.

---

## 0. TL;DR for the next session

1. **68 commits, 452 files, +54,884 lines** landed on 2026-04-09 since
   the last `alignment:` commit (`514e0bf`). `MASTER_PLAN.md` and
   `NORTH_STAR.md` were rewritten mid-day (13:04 local) but another
   ~5 commits and a sizeable uncommitted delta followed — both are
   **partially stale**.
2. **Guardian is shut off.** All three hooks disabled in
   `agent-cli/.claude/settings.json`. Do NOT re-enable without
   user authorization. See `memory/feedback_guardian_subagent_dispatch.md`.
3. **Six sub-systems of the Oil Bot Pattern Strategy shipped** — sub-systems
   1–5 + sub-system 6 L1+L2+L3+L4 — all behind kill switches at `enabled: false`.
   **Zero of these have been battle-tested on a live trade.**
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
