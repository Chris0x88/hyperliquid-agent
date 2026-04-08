# heatmap iterator

**Runs in:** WATCH, REBALANCE, OPPORTUNISTIC (all tiers — read-only, safe)
**Source:** `cli/daemon/iterators/heatmap.py`
**Pure logic:** `modules/heatmap.py`
**Spec:** `docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md`
**Plan:** `docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP_PLAN.md`

## Purpose

Sub-system 3 of the Oil Bot-Pattern Strategy. Polls Hyperliquid market data
for configured oil instruments and writes two structured streams that later
sub-systems (#4 bot-pattern classifier, #5 strategy engine) consume:

1. **Liquidity zones** — clusters of resting bid/ask depth that act as
   magnet levels and likely stop-hunt targets. Written to
   `data/heatmap/zones.jsonl`.
2. **Liquidation cascades** — windows where open interest drops sharply
   while funding spikes, indicating bot-driven overextensions. Written to
   `data/heatmap/cascades.jsonl`.

The iterator NEVER places trades. Pure HL info API only — no external deps.

## Inputs

| Endpoint | Use |
|---|---|
| `l2Book` (per coin) | Resting bid/ask depth → cluster into zones |
| `metaAndAssetCtxs` (with `dex='xyz'` for BRENTOIL) | Open interest + funding rate → cascade detection |

CL native is supported in code but not enabled by default — sub-system 5 is
the gatekeeper for any CL trading.

## Outputs

`data/heatmap/zones.jsonl` (append-only):

```json
{"id": "BRENTOIL_2026-04-09T22:00:00Z_b1", "instrument": "BRENTOIL",
 "snapshot_at": "...", "mid": 67.42, "side": "bid",
 "price_low": 67.10, "price_high": 67.18, "centroid": 67.14,
 "distance_bps": 41, "notional_usd": 482000, "level_count": 7, "rank": 1}
```

`data/heatmap/cascades.jsonl` (append-only):

```json
{"id": "BRENTOIL_2026-04-09T22:03:11Z", "instrument": "BRENTOIL",
 "detected_at": "...", "window_s": 180, "side": "long",
 "oi_delta_pct": -3.4, "funding_jump_bps": 18, "severity": 2,
 "notes": "OI dropped 3.4% in 180s — likely long cascade"}
```

Severity 1..4. ≥3 emits an `Alert` to the daemon context.

## Configuration

`data/config/heatmap.json`:

```json
{
  "enabled": true,
  "instruments": ["BRENTOIL"],
  "poll_interval_s": 60,
  "cluster_bps": 8,
  "max_distance_bps": 200,
  "max_zones_per_side": 5,
  "min_zone_notional_usd": 50000,
  "cascade_window_s": 180,
  "cascade_oi_delta_pct": 1.5,
  "cascade_funding_jump_bps": 10,
  "zones_jsonl": "data/heatmap/zones.jsonl",
  "cascades_jsonl": "data/heatmap/cascades.jsonl"
}
```

**Kill switch:** flip `enabled` to `false` and the iterator no-ops on the
next tick.

## Telegram surface

`/heatmap [SYMBOL]` — deterministic command (no AI). Reads the latest
snapshot from `zones.jsonl` and the most recent cascades from
`cascades.jsonl`, formats top bid/ask walls and recent cascade events.
Defaults to `BRENTOIL`.

## Coexistence

- **Read-only.** No order placement. No mutation of any other sub-system's
  state files. Cannot interact with the existing thesis path.
- **No direction-rule change.** The "LONG or NEUTRAL only on oil" rule
  remains in force at sub-system 3. The relaxation in `OIL_BOT_PATTERN_SYSTEM.md`
  §4 is gated to sub-system 5 only.
- **No CL trading.** Heatmap may write CL data when enabled, but no trade
  is ever placed.

## Tests

- `tests/test_heatmap.py` — pure logic (clustering, cascade detection, JSONL)
- `tests/test_heatmap_iterator.py` — iterator wiring with mocked HTTP
- `tests/test_telegram_heatmap_command.py` — `/heatmap` command output

## Coin name normalization

The iterator handles the `xyz:` prefix gotcha (CLAUDE.md "Coin name
normalization"): when matching instrument symbols against
`metaAndAssetCtxs.universe[].name`, both the prefixed and bare forms are
checked. This is the recurring source of silent funding/OI lookup failures
for xyz perps.
