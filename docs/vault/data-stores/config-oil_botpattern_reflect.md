---
kind: config_file
last_regenerated: 2026-04-09 16:05
path: data/config/oil_botpattern_reflect.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `oil_botpattern_reflect.json`

**Path**: [`data/config/oil_botpattern_reflect.json`](../../data/config/oil_botpattern_reflect.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "_comment": "Sub-system 6 L2 — weekly reflect proposals for oil_botpattern. Ships with enabled=false. Writes StructuralProposal records to proposals_jsonl and emits a Telegram alert. NEVER auto-applies proposals — Chris reviews via /selftuneproposals and taps /selftuneapprove <id>. See docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md.",
  "enabled": false,

  "window_days": 7,
  "min_sample_per_rule": 5,
  "min_run_interval_days": 7,

  "main_journal_jsonl":     "data/research/journal.jsonl",
  "decision_journal_jsonl": "data/strategy/oil_botpattern_journal.jsonl",
  "strategy_config_path":   "data/config/oil_botpattern.json",
  "proposals_jsonl":        "data/strategy/oil_botpattern_proposals.jsonl",
  "state_json":             "data/strategy/oil_botpattern_reflect_state.json",
  "audit_jsonl":            "data/strategy/oil_botpattern_tune_audit.jsonl"
}

```

## See also

- Likely consumer: [[oil_botpattern_reflect]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
