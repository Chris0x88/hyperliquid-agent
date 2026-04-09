---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md
status: unknown
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN

**Source**: [`docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md`](../../docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md)

**Status (detected)**: unknown

## Preview

```
# Sub-System 1 — News & Catalyst Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md` (committed in `7ac7bea`)
**Parent:** `docs/plans/OIL_BOT_PATTERN_SYSTEM.md`

**Goal:** Build a daemon iterator that polls public RSS feeds and iCal calendars, tags headlines against a rule library, and publishes structured `Catalyst` records so the existing `CatalystDeleverageIterator` can act on them without any change to its trading behaviour.

**Architecture:** Three layers. (1) `modules/news_engine.py` is pure logic — feed parsing, dedup, rule-based tagging, catalyst extraction — with no I/O. (2) `cli/daemon/iterators/news_ingest.py` is the daemon integration layer that polls feeds on a tick, throttles per-source, and writes results to JSONL files. (3) `modules/catalyst_bridge.py` fans Catalysts out to one CatalystEvent per instrument and writes them to a new `data/daemon/external_catalyst_events.json` file that the existing `CatalystDeleverageIterator` reads on each tick via a new additive method. All new files are additive. Existing files get additive-only edits.

**Tech Stack:** Python 3.13, pytest, PyYAML (already in deps), feedparser (new — requires approval at Phase 0), icalendar (new — requires approval at Phase 0). Existing daemon tick engine (`cli/daemon/clock.py`).

---

## Ship gates (from parent spec §7)

Each item must be checked by the end of Phase 8 before sub-system 2 is allowed to start:

- [ ] All 19 tests from spec §9 passing
- [ ] Mock-mode end-to-end run produces expected outputs against fixture feeds
- [ ] Live-mode dry-run for ≥ 24h with `severity_floor: 5`; Telegram alerts fire on real catalysts and do not duplicate; no severity-3/4 entries reach `external_catalyst_events.json`
- [ ] Promote `severity_floor` from `5` to `3` (config edit only)
- [ ] `docs/wiki/components/news_ingest.md` created
- [ ] `CLAUDE.md` daemon iterator list updated
- [ ] `docs/wiki/build-log.md` entry added
- [ ] `/news` and `/catalysts` smoke-tested via Telegram on mainnet

---

```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
