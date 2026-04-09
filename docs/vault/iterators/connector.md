---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: connector
class_name: ConnectorIterator
source_file: cli/daemon/iterators/connector.py
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
# Iterator: connector

**Class**: `ConnectorIterator` in [`cli/daemon/iterators/connector.py`](../../cli/daemon/iterators/connector.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

ConnectorIterator — fetches market data from HL adapter into TickContext.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
