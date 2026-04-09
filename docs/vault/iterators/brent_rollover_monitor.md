---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: brent_rollover_monitor
class_name: BrentRolloverMonitorIterator
source_file: cli/daemon/iterators/brent_rollover_monitor.py
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
# Iterator: brent_rollover_monitor

**Class**: `BrentRolloverMonitorIterator` in [`cli/daemon/iterators/brent_rollover_monitor.py`](../../cli/daemon/iterators/brent_rollover_monitor.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Watches the Brent futures roll calendar and alerts before each roll.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
