---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: account_collector
class_name: AccountCollectorIterator
source_file: cli/daemon/iterators/account_collector.py
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
# Iterator: account_collector

**Class**: `AccountCollectorIterator` in [`cli/daemon/iterators/account_collector.py`](../../cli/daemon/iterators/account_collector.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Collects timestamped account snapshots and tracks high water mark + drawdown.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
