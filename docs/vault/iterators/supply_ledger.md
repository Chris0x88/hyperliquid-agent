---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: supply_ledger
class_name: SupplyLedgerIterator
source_file: cli/daemon/iterators/supply_ledger.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/supply_ledger.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: supply_ledger

**Class**: `SupplyLedgerIterator` in [`cli/daemon/iterators/supply_ledger.py`](../../cli/daemon/iterators/supply_ledger.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/supply_ledger.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

SupplyLedgerIterator — sub-system 2 of the Oil Bot-Pattern Strategy.

Watches data/news/catalysts.jsonl (produced by news_ingest) for new
physical_damage / shipping_attack / chokepoint_blockade catalysts,
auto-extracts Disruption records, and periodically recomputes SupplyState.

Read-only: never places trades. Safe in all tiers.
Kill switch: data/config/supply_ledger.json → enabled: false

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/supply_ledger.json` → [[config-supply_ledger]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
