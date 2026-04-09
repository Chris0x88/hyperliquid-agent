---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: thesis_engine
class_name: ThesisEngineIterator
source_file: cli/daemon/iterators/thesis_engine.py
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
# Iterator: thesis_engine

**Class**: `ThesisEngineIterator` in [`cli/daemon/iterators/thesis_engine.py`](../../cli/daemon/iterators/thesis_engine.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Reads AI-authored ThesisState files from disk into TickContext.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
