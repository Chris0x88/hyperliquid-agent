---
kind: config_file
last_regenerated: 2026-04-09 16:05
path: data/config/oil_botpattern_shadow.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `oil_botpattern_shadow.json`

**Path**: [`data/config/oil_botpattern_shadow.json`](../../data/config/oil_botpattern_shadow.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "_comment": "Sub-system 6 L4 — counterfactual shadow evaluation for oil_botpattern structural proposals. Ships with enabled=false. For each approved L2 proposal without a shadow_eval yet, re-runs the recent decision window with the PROPOSED params using the pure gate chain and writes a ShadowEval record comparing divergences. Never applies anything — this is evaluation only.",
  "enabled": false,

  "tick_interval_s": 3600,
  "min_sample": 10,
  "window_days": 30,

  "proposals_jsonl":       "data/strategy/oil_botpattern_proposals.jsonl",
  "strategy_config_path":  "data/config/oil_botpattern.json",
  "main_journal_jsonl":    "data/research/journal.jsonl",
  "decision_journal_jsonl":"data/strategy/oil_botpattern_journal.jsonl",
  "shadow_evals_jsonl":    "data/strategy/oil_botpattern_shadow_evals.jsonl",
  "state_json":            "data/strategy/oil_botpattern_shadow_state.json"
}

```

## See also

- Likely consumer: [[oil_botpattern_shadow]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
