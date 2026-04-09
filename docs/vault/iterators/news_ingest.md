---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: news_ingest
class_name: NewsIngestIterator
source_file: cli/daemon/iterators/news_ingest.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/news_ingest.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: news_ingest

**Class**: `NewsIngestIterator` in [`cli/daemon/iterators/news_ingest.py`](../../cli/daemon/iterators/news_ingest.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/news_ingest.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

NewsIngestIterator — polls RSS feeds + iCal calendars, writes catalysts.

Spec: docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md
Parent: docs/plans/OIL_BOT_PATTERN_SYSTEM.md

This iterator is additive and read-only (no trades). It is safe in all tiers.
Kill switch: data/config/news_ingest.json → enabled: false.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/news_ingest.json` → [[config-news_ingest]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
