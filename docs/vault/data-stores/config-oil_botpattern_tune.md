---
kind: config_file
last_regenerated: 2026-04-09 14:08
path: data/config/oil_botpattern_tune.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `oil_botpattern_tune.json`

**Path**: [`data/config/oil_botpattern_tune.json`](../../data/config/oil_botpattern_tune.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "_comment": "Sub-system 6 L1 — bounded auto-tune for oil_botpattern. Ships with enabled=false. Nudges tunable params in oil_botpattern.json within hard bounds, after each closed oil_botpattern trade. Structural changes forbidden. See docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md.",
  "enabled": false,

  "tick_interval_s": 300,
  "window_size": 20,
  "min_sample": 5,
  "rel_step_max": 0.05,
  "min_rate_limit_hours": 24,

  "bounds": {
    "long_min_edge":                    {"min": 0.35, "max": 0.70, "type": "float"},
    "short_min_edge":                   {"min": 0.55, "max": 0.85, "type": "float"},
    "funding_warn_pct":                 {"min": 0.30, "max": 1.00, "type": "float"},
    "funding_exit_pct":                 {"min": 1.00, "max": 2.50, "type": "float"},
    "short_blocking_catalyst_severity": {"min": 3,    "max": 5,    "type": "int"}
  },

  "strategy_config_path":   "data/config/oil_botpattern.json",
  "main_journal_jsonl":     "data/research/journal.jsonl",
  "decision_journal_jsonl": "data/strategy/oil_botpattern_journal.jsonl",
  "audit_jsonl":            "data/strategy/oil_botpattern_tune_audit.jsonl",
  "state_json":             "data/strategy/oil_botpattern_tune_state.json"
}

```

## See also

- Likely consumer: [[oil_botpattern_tune]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
