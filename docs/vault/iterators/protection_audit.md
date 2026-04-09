---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: protection_audit
class_name: ProtectionAuditIterator
source_file: cli/daemon/iterators/protection_audit.py
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
# Iterator: protection_audit

**Class**: `ProtectionAuditIterator` in [`cli/daemon/iterators/protection_audit.py`](../../cli/daemon/iterators/protection_audit.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Read-only verifier that every open position has a sane exchange stop.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
