# Sub-system 3 — Stop / Liquidity Heatmap

**Slot in `OIL_BOT_PATTERN_SYSTEM.md`:** row 3. Pure HL API. Independent of #1/#2.

## What it is

A read-only iterator that polls Hyperliquid market data for oil instruments
(BRENTOIL on xyz dex, CL native if/when promoted) and writes two structured
streams that downstream sub-systems #4 (bot-pattern classifier) and #5
(strategy engine) consume:

1. **`data/heatmap/zones.jsonl`** — append-only snapshots of liquidity zones.
   Each line = one cluster of resting orders within `cluster_bps` of mid,
   ranked by aggregate notional. Used to identify magnet levels and likely
   stop-hunt targets.

2. **`data/heatmap/cascades.jsonl`** — append-only liquidation cascade events.
   Each line = a window in which liquidations + OI delta exceed thresholds,
   tagged with side and severity. Used to detect bot-driven overextensions.

The iterator NEVER places trades. The kill switch is
`data/config/heatmap.json → enabled: false`.

## Why this slot

- **Smallest external surface** — Hyperliquid info API only. No new RSS, no
  scraping, no LLM. Lowest risk to ship after #1/#2.
- **Independent** — does not consume #1 or #2. Can run in parallel without
  blocking the strategy chain.
- **Mechanical and testable** — pure transforms over orderbook + recent fills.

## Inputs (Hyperliquid `info` API only)

| Endpoint | Coin | Use |
|---|---|---|
| `l2Book` | `xyz:BRENTOIL`, optionally `CL` | Resting bid/ask depth → zones |
| `meta` / `metaAndAssetCtxs` | both dexes | Mid price + open interest |
| `userFills` is NOT used (account-scoped). Cascades use **OI delta + funding spike** as a public proxy. |

If a CL native order book lookup fails (CL is `tracked but unsupported` until
sub-system 5 ships), the iterator logs and skips that instrument silently —
BRENTOIL still runs.

## Outputs

### `zones.jsonl`
```json
{
  "id": "BRENTOIL_2026-04-09T22:00:00Z_b1",
  "instrument": "BRENTOIL",
  "snapshot_at": "2026-04-09T22:00:00Z",
  "mid": 67.42,
  "side": "bid",
  "price_low": 67.10,
  "price_high": 67.18,
  "centroid": 67.14,
  "distance_bps": 41,
  "notional_usd": 482000.0,
  "level_count": 7,
  "rank": 1
}
```

### `cascades.jsonl`
```json
{
  "id": "BRENTOIL_2026-04-09T22:03:11Z",
  "instrument": "BRENTOIL",
  "detected_at": "2026-04-09T22:03:11Z",
  "window_s": 180,
  "side": "long",
  "oi_delta_pct": -3.4,
  "funding_jump_bps": 18,
  "severity": 2,
  "notes": "OI dropped 3.4% in 180s with funding spike — likely long cascade"
}
```

`severity` is 1..4. 4 = ≥7% OI drop in 60s.

## Kill switch + config

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

CL is omitted by default; flip on once sub-system 5 promotes it.

## Coexistence + safety

- **Read-only.** No order placement. No mutation of any other sub-system's
  state files. Cannot interact with the existing thesis path.
- **No direction-rule change.** The "LONG or NEUTRAL only on oil" rule is
  unchanged at this stage. Sub-system 5 is the only place where that
  relaxation is gated, per the SYSTEM doc §4.
- **No CL trading.** Heatmap may write CL data when enabled, but no trade
  is ever placed — sub-system 5 is the gatekeeper.

## What's deliberately NOT in this sub-system

- Bot-pattern classification → sub-system 4
- Order placement → sub-system 5
- Self-tuning of thresholds → sub-system 6
- Lesson generation → already shipped in the lesson layer

Heatmap writes raw data. Downstream sub-systems decide what to do with it.

## Spec links

- `OIL_BOT_PATTERN_SYSTEM.md` — overall architecture
- `OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP_PLAN.md` — wedge-by-wedge build plan
