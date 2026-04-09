---
kind: config_file
last_regenerated: 2026-04-09 14:08
path: data/config/oil_botpattern_patternlib.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `oil_botpattern_patternlib.json`

**Path**: [`data/config/oil_botpattern_patternlib.json`](../../data/config/oil_botpattern_patternlib.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "_comment": "Sub-system 6 L3 — pattern library growth for oil_botpattern bot classifier. Ships with enabled=false. Watches data/research/bot_patterns.jsonl, detects novel (classification, direction, confidence_band, signals) signatures, and writes candidates to bot_pattern_candidates.jsonl after min_occurrences repetitions. Chris promotes candidates into the live catalog via /patternpromote <id>. Library growth is purely observational — it does NOT modify sub-system 4's classification behavior in this wedge.",
  "enabled": false,

  "tick_interval_s": 600,
  "min_occurrences": 3,
  "confidence_band_precision": 0.1,
  "window_days": 30,

  "bot_patterns_jsonl":  "data/research/bot_patterns.jsonl",
  "catalog_json":        "data/research/bot_pattern_catalog.json",
  "candidates_jsonl":    "data/research/bot_pattern_candidates.jsonl",
  "state_json":          "data/strategy/oil_botpattern_patternlib_state.json"
}

```

## See also

- Likely consumer: [[oil_botpattern_patternlib]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
