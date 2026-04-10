---
kind: iterator
last_regenerated: 2026-04-09 16:36
iterator_name: risk
class_name: RiskIterator
source_file: cli/daemon/iterators/risk.py
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
# Iterator: risk

**Class**: `RiskIterator` in [`cli/daemon/iterators/risk.py`](../../cli/daemon/iterators/risk.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

RiskIterator — wraps parent/risk_manager.py to set risk gate.

Uses the composable ProtectionChain (Freqtrade + LEAN pattern) to run
multiple independent risk checks. Worst gate wins, all reasons consolidated
into a single alert per tick (no spam).

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
