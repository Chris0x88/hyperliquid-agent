---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: profit_lock
class_name: ProfitLockIterator
source_file: cli/daemon/iterators/profit_lock.py
tiers:
  - rebalance
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: profit_lock

**Class**: `ProfitLockIterator` in [`cli/daemon/iterators/profit_lock.py`](../../cli/daemon/iterators/profit_lock.py)

**Registered in tiers**: `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Tracks profits and takes partial profits to protect capital.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
