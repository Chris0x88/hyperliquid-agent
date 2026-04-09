---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: liquidity
class_name: LiquidityIterator
source_file: cli/daemon/iterators/liquidity.py
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
# Iterator: liquidity

**Class**: `LiquidityIterator` in [`cli/daemon/iterators/liquidity.py`](../../cli/daemon/iterators/liquidity.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Adjusts risk parameters based on time-of-day liquidity regime.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
