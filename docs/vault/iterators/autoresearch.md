---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: autoresearch
class_name: AutoresearchIterator
source_file: cli/daemon/iterators/autoresearch.py
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
# Iterator: autoresearch

**Class**: `AutoresearchIterator` in [`cli/daemon/iterators/autoresearch.py`](../../cli/daemon/iterators/autoresearch.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Runs periodic execution quality evaluations and writes learnings for the AI to read.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
