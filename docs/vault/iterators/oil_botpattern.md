---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: oil_botpattern
class_name: BotPatternStrategyIterator
source_file: cli/daemon/iterators/oil_botpattern.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/oil_botpattern.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: oil_botpattern

**Class**: `BotPatternStrategyIterator` in [`cli/daemon/iterators/oil_botpattern.py`](../../cli/daemon/iterators/oil_botpattern.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/oil_botpattern.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

BotPatternStrategyIterator — sub-system 5 of the Oil Bot-Pattern Strategy.

THE ONLY PLACE in the codebase where shorting BRENTOIL/CL is legal.
Behind a chain of hard gates plus two master kill switches.

Reads outputs of sub-systems 1-4 + existing thesis + funding tracker
from disk, runs the gate chain, computes conviction sizing, and emits
OrderIntents tagged strategy_name="oil_botpattern" with
intended_hold_hours in meta. Coexists with the existing thesis_engine
path per OIL_BOT_PATTERN_SYSTEM.md §5.

Every position immediately enters the existing exchange_protection
SL+TP chain via preferred_*_atr_mult in the OrderIntent meta.

Kill switches:
- data/config/oil_botpattern.json → enabled: false  (whole iterator)
- data/config/oil_botpattern.json → short_legs_enabled: false  (shorts only)

Registered in REBALANCE + OPPORTUNISTIC tiers only. NOT in WATCH.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/oil_botpattern.json` → [[config-oil_botpattern]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
