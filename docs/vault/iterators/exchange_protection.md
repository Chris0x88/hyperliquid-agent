---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: exchange_protection
class_name: ExchangeProtectionIterator
source_file: cli/daemon/iterators/exchange_protection.py
tiers:
  - rebalance
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: exchange_protection

**Class**: `ExchangeProtectionIterator` in [`cli/daemon/iterators/exchange_protection.py`](../../cli/daemon/iterators/exchange_protection.py)

**Registered in tiers**: `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Ruin prevention: maintains exchange-level SL just above liquidation price.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
