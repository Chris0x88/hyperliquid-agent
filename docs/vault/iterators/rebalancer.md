---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: rebalancer
class_name: RebalancerIterator
source_file: cli/daemon/iterators/rebalancer.py
tiers:
  - rebalance
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: rebalancer

**Class**: `RebalancerIterator` in [`cli/daemon/iterators/rebalancer.py`](../../cli/daemon/iterators/rebalancer.py)

**Registered in tiers**: `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

RebalancerIterator — runs BaseStrategy.on_tick() for each roster slot.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
