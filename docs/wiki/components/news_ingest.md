# news_ingest iterator

**Runs in:** WATCH, REBALANCE, OPPORTUNISTIC (all tiers — read-only, safe everywhere)
**Source:** `cli/daemon/iterators/news_ingest.py`
**Pure logic:** `modules/news_engine.py`
**Bridge:** `modules/catalyst_bridge.py`
**Spec:** `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md`
**Implementation plan:** `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md`

## Purpose

Polls public RSS feeds and iCal calendars, deduplicates headlines, tags them
against a YAML-defined rule library, extracts structured `Catalyst` records,
and feeds high-severity catalysts to the existing `CatalystDeleverageIterator`
via a dedicated external file.

Sub-system 1 of the Oil Bot-Pattern Strategy (see `OIL_BOT_PATTERN_SYSTEM.md`
for the broader architecture).

## Inputs

- `data/config/news_feeds.yaml` — feed registry (URL, poll interval, enabled)
- `data/config/news_rules.yaml` — rule library (11 categories as of V1)
- `data/config/news_ingest.json` — runtime config (kill switch, thresholds)

## Outputs

- `data/news/headlines.jsonl` — append-only raw headline log
- `data/news/catalysts.jsonl` — append-only structured catalyst log
- `data/daemon/external_catalyst_events.json` — CatalystEvents fan-out for the
  existing `CatalystDeleverageIterator` to pick up via its tick prologue
- Telegram alerts for severity ≥ 4 catalysts (deduped by `Catalyst.id`)

## Telegram commands

- `/news` — last 10 catalysts by severity (deterministic, NOT AI)
- `/catalysts` — upcoming catalysts in next 7 days (deterministic, NOT AI)

## Kill switch

Edit `data/config/news_ingest.json` → `"enabled": false`. On the next tick the
iterator no-ops: no polling, no writes, no alerts. The existing
`CatalystDeleverageIterator` continues reading its hand-curated state file
unchanged.

## Out of scope

- Sentiment scoring (sub-system 4 — bot-pattern classifier)
- Price-impact prediction (sub-system 5 — strategy engine)
- Supply disruption ledger (sub-system 2 — separate brainstorm)
- Twitter / X feeds (deferred)
- LLM-based headline summarisation (deferred)

## Known limitations

- V1 dedup is per-source only. Same event from Reuters AND AP will produce two
  separate `Catalyst` records. Cross-source clustering is handled by
  sub-system 4 during signal scoring.
- V1 severity/direction is pure keyword-based. Fine-tuning via journal replay
  is sub-system 6's job.
- iCal sources are only enabled if their URLs are verified at implementation
  time; placeholder entries remain `enabled: false` until validated.
