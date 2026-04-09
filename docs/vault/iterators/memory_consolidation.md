---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: memory_consolidation
class_name: MemoryConsolidationIterator
source_file: cli/daemon/iterators/memory_consolidation.py
tiers:
  - watch
  - rebalance
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: memory_consolidation

**Class**: `MemoryConsolidationIterator` in [`cli/daemon/iterators/memory_consolidation.py`](../../cli/daemon/iterators/memory_consolidation.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Memory consolidation iterator — periodic compression of old events.

Runs inside the daemon tick loop. Consolidates old memory events into
bounded summaries so the AI gets accumulated knowledge without unbounded
context growth.

Runs infrequently (once per hour by default) to avoid wasting cycles.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
