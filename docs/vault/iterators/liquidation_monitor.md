---
kind: iterator
last_regenerated: 2026-04-09 16:36
iterator_name: liquidation_monitor
class_name: LiquidationMonitorIterator
source_file: cli/daemon/iterators/liquidation_monitor.py
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
# Iterator: liquidation_monitor

**Class**: `LiquidationMonitorIterator` in [`cli/daemon/iterators/liquidation_monitor.py`](../../cli/daemon/iterators/liquidation_monitor.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Per-position liquidation cushion monitor with tiered alerts.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
