---
kind: plan
last_regenerated: 2026-04-09 16:36
plan_file: docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md
status: Approved 2026-04-09. Ready for implementation plan.
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_01_NEWS_INGESTION

**Source**: [`docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md`](../../docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md)

**Status (detected)**: Approved 2026-04-09. Ready for implementation plan.

## Preview

```
# Sub-System 1 — News & Catalyst Ingestion

> **Parent:** `OIL_BOT_PATTERN_SYSTEM.md`
> **Status:** Approved 2026-04-09. Ready for implementation plan.
> **Constraint:** Additive only. Zero destructive changes to existing files.
> **Kill switch:** `data/config/news_ingest.json` → `enabled: false` no-ops the iterator.

---

## 1. Purpose and boundary

**One job:** turn public RSS feeds and iCal calendars into structured
catalyst records that downstream sub-systems consume. Nothing else.

**This sub-system DOES:**
- Poll RSS feeds and iCal calendars on a schedule
- Dedupe incoming headlines
- Tag headlines against a YAML rule library (categories + severity)
- Extract structured `Catalyst` records from tagged headlines
- Append catalysts above the severity threshold to the existing
  `data/daemon/catalyst_events.json` so the existing
  `CatalystDeleverageIterator` consumes them with zero behaviour change
- Emit Telegram alerts on severity ≥ 4 catalysts
- Expose two deterministic Telegram commands (`/news`, `/catalysts`)

**This sub-system does NOT:**
- Score sentiment (no NLP model in V1)
- Predict price direction beyond simple rule-based tagging
- Consume Twitter / X / Truth Social
- Modify thesis files
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
