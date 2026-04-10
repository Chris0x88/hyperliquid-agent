---
kind: config_file
last_regenerated: 2026-04-09 16:36
path: data/config/oil_botpattern.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `oil_botpattern.json`

**Path**: [`data/config/oil_botpattern.json`](../../data/config/oil_botpattern.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "_comment": "Sub-system 5 of the Oil Bot-Pattern Strategy. BOTH kill switches ship OFF. Enable manually after review. decisions_only=true puts the iterator in SHADOW MODE: it runs the full gate chain, logs decisions, maintains paper positions with Telegram notices and a running shadow balance, but NEVER emits OrderIntents. This is the activation rung between WATCH-with-everything-off and REBALANCE-with-real-money. See docs/wiki/operations/sub_system_5_activation.md.",
  "enabled": true,
  "short_legs_enabled": false,
  "short_legs_grace_period_s": 3600,
  "decisions_only": true,
  "shadow_seed_balance_usd": 100000.0,
  "shadow_sl_pct": 2.0,
  "shadow_tp_pct": 5.0,
  "instruments": [
    "BRENTOIL",
    "CL"
  ],
  "tick_interval_s": 60,
  "long_min_edge": 0.5,
  "short_min_edge": 0.7,
  "short_blocking_catalyst_severity": 4,
  "short_blocking_supply_freshness_hours": 72,
  "short_max_hold_hours": 24,
  "short_daily_loss_cap_pct": 1.5,
  "sizing_ladder": [
    {
      "min_edge": 0.5,
      "base_pct": 0.02,
      "leverage": 2.0
    },
    {
      "min_edge": 0.6,
      "base_pct": 0.05,
      "leverage": 3.0
    },
    {
      "min_edge": 0.7,
      "base_pct": 0.1,
      "leverage": 5.0
    },
    {
      "min_edge": 0.8,
      "base_pct": 0.18,
      "leverage": 7.0
    },
    {
      "min_edge": 0.9,
      "base_pct": 0.28,
      "leverage": 10.0
    }
  ],
  "drawdown_brakes": {
    "daily_max_loss_pct": 3.0,
    "weekly_max_loss_pct": 8.0,
    "monthly_max_loss_pct": 15.0
  },
  "funding_warn_pct": 0.5,
  "funding_exit_pct": 1.5,
  "preferred_sl_atr_mult": 0.8,
  "preferred_tp_atr_mult": 2.0,
  "patterns_jsonl": "data/research/bot_patterns.jsonl",
  "zones_jsonl": "data/heatmap/zones.jsonl",
  "cascades_jsonl": "data/heatmap/cascades.jsonl",
  "supply_state_json": "data/supply/state.json",
  "catalysts_jsonl": "data/news/catalysts.jsonl",
  "risk_caps_json": "data/config/risk_caps.json",
  "thesis_state_path": "data/thesis/xyz_brentoil_state.json",
  "funding_tracker_jsonl": "data/daemon/funding_tracker.jsonl",
  "main_journal_jsonl": "data/research/journal.jsonl",
  "decision_journal_jsonl": "data/strategy/oil_botpattern_journal.jsonl",
  "state_json": "data/strategy/oil_botpattern_state.json",
  "shadow_positions_json": "data/strategy/oil_botpattern_shadow_positions.json",
  "shadow_trades_jsonl": "data/strategy/oil_botpattern_shadow_trades.jsonl",
  "shadow_balance_json": "data/strategy/oil_botpattern_shadow_balance.json",
  "adaptive_expected_reach_hours": 48.0,
  "adaptive_heartbeat_minutes": 15.0,
  "adaptive_log_jsonl": "data/strategy/oil_botpattern_adaptive_log.jsonl",
  "adaptive": {
    "stale_time_progress": 1.0,
    "stale_price_progress": 0.3,
    "slow_velocity_ratio": 0.25,
    "slow_velocity_time_floor": 0.5,
    "breakeven_at_progress": 0.5,
    "tighten_at_progress": 0.8,
    "tighten_buffer_pct": 0.5,
    "scale_out_at_progress": 2.0,
    "adverse_catalyst_severity": 4,
    "catalyst_lookback_hours": 24.0,
    "drift_
... [truncated]
```

## See also

- Likely consumer: [[oil_botpattern]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
