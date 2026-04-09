---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: market_structure
class_name: MarketStructureIterator
source_file: cli/daemon/iterators/market_structure_iter.py
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
# Iterator: market_structure

**Class**: `MarketStructureIterator` in [`cli/daemon/iterators/market_structure_iter.py`](../../cli/daemon/iterators/market_structure_iter.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Computes MarketSnapshot for each tracked market and injects into TickContext.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
