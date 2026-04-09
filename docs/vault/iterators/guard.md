---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: guard
class_name: GuardIterator
source_file: cli/daemon/iterators/guard.py
tiers:
  - rebalance
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: guard

**Class**: `GuardIterator` in [`cli/daemon/iterators/guard.py`](../../cli/daemon/iterators/guard.py)

**Registered in tiers**: `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

GuardIterator — per-position trailing stops with exchange-level SL sync.

Wraps modules/guard_bridge.py to:
  1. Evaluate Guard (trailing stop engine) on each tick
  2. Sync exchange-level SL trigger orders to match the Guard's current floor
  3. Queue close orders when Guard signals CLOSE

This is the second line of defense after ExchangeProtectionIterator.
ExchangeProtection sets a static SL at entry - X%; Guard RATCHETS the SL
upward as profit grows (trailing stop), and syncs that tighter SL to the
exchange.  Together they ensure the exchange always has a protective order.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
