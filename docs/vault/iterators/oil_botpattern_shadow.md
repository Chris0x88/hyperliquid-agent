---
kind: iterator
last_regenerated: 2026-04-09 16:36
iterator_name: oil_botpattern_shadow
class_name: OilBotPatternShadowIterator
source_file: cli/daemon/iterators/oil_botpattern_shadow.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/oil_botpattern_shadow.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: oil_botpattern_shadow

**Class**: `OilBotPatternShadowIterator` in [`cli/daemon/iterators/oil_botpattern_shadow.py`](../../cli/daemon/iterators/oil_botpattern_shadow.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/oil_botpattern_shadow.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

OilBotPatternShadowIterator — sub-system 6 layer L4 counterfactual eval.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md §L4

Scans data/strategy/oil_botpattern_proposals.jsonl for L2 proposals
with status="approved" and no `shadow_eval` field yet. For each one,
runs the counterfactual replay in modules.oil_botpattern_shadow against
the recent decision + closed-trade window, writes a ShadowEval record
to oil_botpattern_shadow_evals.jsonl, and attaches a `shadow_eval`
summary to the proposal record via atomic rewrite.

Kill switch: data/config/oil_botpattern_shadow.json → enabled: false.
Ships enabled=false. Never modifies any config file.

Registered in REBALANCE + OPPORTUNISTIC tiers. Not in WATCH — no
value when no trades are closing.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/oil_botpattern_shadow.json` → [[config-oil_botpattern_shadow]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
