---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: catalyst_deleverage
class_name: CatalystDeleverageIterator
source_file: cli/daemon/iterators/catalyst_deleverage.py
tiers:
  - rebalance
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: catalyst_deleverage

**Class**: `CatalystDeleverageIterator` in [`cli/daemon/iterators/catalyst_deleverage.py`](../../cli/daemon/iterators/catalyst_deleverage.py)

**Registered in tiers**: `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Automatically reduces position leverage/size ahead of high-volatility catalysts.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
