---
kind: iterator
last_regenerated: 2026-04-09 16:36
iterator_name: funding_tracker
class_name: FundingTrackerIterator
source_file: cli/daemon/iterators/funding_tracker.py
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
# Iterator: funding_tracker

**Class**: `FundingTrackerIterator` in [`cli/daemon/iterators/funding_tracker.py`](../../cli/daemon/iterators/funding_tracker.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

FundingTrackerIterator -- tracks cumulative funding costs for open positions.

HyperLiquid perpetual futures charge/receive funding hourly.  For leveraged
positions this is a significant hidden cost that erodes PnL.  This iterator
estimates each payment on a throttled schedule and persists a running tally
to ``data/daemon/funding_tracker.jsonl``.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
