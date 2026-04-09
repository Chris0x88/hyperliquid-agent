---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: oil_botpattern_reflect
class_name: OilBotPatternReflectIterator
source_file: cli/daemon/iterators/oil_botpattern_reflect.py
tiers:
  - rebalance
  - opportunistic
kill_switch: data/config/oil_botpattern_reflect.json
daemon_registered: true
tags:
  - iterator
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: oil_botpattern_reflect

**Class**: `OilBotPatternReflectIterator` in [`cli/daemon/iterators/oil_botpattern_reflect.py`](../../cli/daemon/iterators/oil_botpattern_reflect.py)

**Registered in tiers**: `rebalance`, `opportunistic`

**Kill switch config**: `data/config/oil_botpattern_reflect.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

OilBotPatternReflectIterator — sub-system 6 layer L2 weekly proposals.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Runs WEEKLY (first tick where now - last_run_at ≥ min_run_interval_days).
Reads the closed-trade stream + decision journal, runs the L2 detection
rules, appends new StructuralProposal records to a proposals JSONL, and
fires a Telegram warning alert listing the new proposal IDs.

L2 NEVER auto-applies. All proposals start `status="pending"`. Chris
reviews via /selftuneproposals and taps /selftuneapprove <id> or
/selftunereject <id>. The approval/rejection handlers live in
cli/telegram_bot.py, not this iterator.

Kill switch: data/config/oil_botpattern_reflect.json → enabled: false.
Ships with enabled=false.

Registered in REBALANCE + OPPORTUNISTIC tiers only. NOT in WATCH.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/oil_botpattern_reflect.json` → [[config-oil_botpattern_reflect]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
