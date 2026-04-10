---
kind: iterator
last_regenerated: 2026-04-09 16:36
iterator_name: radar
class_name: RadarIterator
source_file: cli/daemon/iterators/radar.py
tiers:
  - watch
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-opportunistic
---
# Iterator: radar

**Class**: `RadarIterator` in [`cli/daemon/iterators/radar.py`](../../cli/daemon/iterators/radar.py)

**Registered in tiers**: `watch`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

RadarIterator — wraps modules/radar_engine.py for opportunity scanning.

Persists opportunities to data/research/signals.jsonl for AI agent access and historical review.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
