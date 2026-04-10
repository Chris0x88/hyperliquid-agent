---
kind: plan
last_regenerated: 2026-04-09 16:36
plan_file: docs/plans/MASTER_PLAN.md
status: unknown
tags:
  - plan
---
# Plan: MASTER_PLAN

**Source**: [`docs/plans/MASTER_PLAN.md`](../../docs/plans/MASTER_PLAN.md)

**Status (detected)**: unknown

## Preview

```
# HyperLiquid Trading System — Master Plan

> **Read this + the relevant package `CLAUDE.md` at the start of every session.**
> **Vision:** `docs/plans/NORTH_STAR.md` (mandatory before any strategy/scope work)
> **System knowledge:** `docs/wiki/` · **Build history:** `docs/wiki/build-log.md`
> **Past plans:** `docs/plans/archive/` (append-only snapshots)

---

## What this system is

A personal trading instrument for one petroleum engineer (Chris) that
trades **with the dumb-bot reality** — anticipating obvious moves, fading
bot overshoot — instead of betting on the market being a fair discounting
mechanism. The user has the ideas. The system has the discipline. Markets
are 80% bots reacting to current news; the system turns Chris's
petroleum-engineering edge into structured signals the bots cannot read.

**Read `NORTH_STAR.md` for the founding insight, the L0–L5 self-improvement
contract, the authority model, and the historical-oracles vision.**

---

## Current Reality (always reflects HEAD)

| | |
|---|---|
| **Production tier** | WATCH (mainnet, launchd-managed) |
| **Authority model** | Per-asset via `common/authority.py` (`agent` / `manual` / `off`); default `manual`; persisted in `data/authority.json` |
| **Tradeable thesis markets** | BTC, BRENTOIL, GOLD, SILVER. **Active edge: oil + BTC.** GOLD + SILVER theses have been stale since early April — conviction engine auto-clamps them (safe), not being traded. Refresh or formally park. |
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
