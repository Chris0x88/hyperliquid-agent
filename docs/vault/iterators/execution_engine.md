---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: execution_engine
class_name: ExecutionEngineIterator
source_file: cli/daemon/iterators/execution_engine.py
tiers:
  - rebalance
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: execution_engine

**Class**: `ExecutionEngineIterator` in [`cli/daemon/iterators/execution_engine.py`](../../cli/daemon/iterators/execution_engine.py)

**Registered in tiers**: `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Conviction-based adaptive execution engine.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
