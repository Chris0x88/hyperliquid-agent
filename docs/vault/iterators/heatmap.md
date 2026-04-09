---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: heatmap
class_name: HeatmapIterator
source_file: cli/daemon/iterators/heatmap.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/heatmap.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: heatmap

**Class**: `HeatmapIterator` in [`cli/daemon/iterators/heatmap.py`](../../cli/daemon/iterators/heatmap.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/heatmap.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

HeatmapIterator — sub-system 3 of the Oil Bot-Pattern Strategy.

Polls Hyperliquid l2Book + meta for configured oil instruments, clusters
liquidity into zones, and detects liquidation cascades from OI/funding deltas.

Read-only: never places trades. Safe in all tiers.
Kill switch: data/config/heatmap.json → enabled: false

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/heatmap.json` → [[config-heatmap]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
