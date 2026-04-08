# bot_classifier iterator

**Runs in:** WATCH, REBALANCE, OPPORTUNISTIC (all tiers — read-only, safe)
**Source:** `cli/daemon/iterators/bot_classifier.py`
**Pure logic:** `modules/bot_classifier.py`
**Spec:** `docs/plans/OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md`

## Purpose

Sub-system 4 of the Oil Bot-Pattern Strategy. Periodically classifies the
recent move on each configured oil instrument as one of:

- `bot_driven_overextension` — likely shake-out / cascade-driven move
  with no fundamental support
- `informed_move` — move backed by a high-severity catalyst or supply
  disruption
- `mixed` — both bot-driven and informed signals present
- `unclear` — neither dominates; insufficient evidence

Each record carries a confidence score (0..1), the contributing signals
as plain text, and the price + window context that downstream
sub-systems #5 (strategy engine) and #6 (self-tune harness) consume.

The iterator NEVER places trades. **Heuristic-only — no ML, no LLM.**
Layer L5 (ML overlay) is explicitly deferred per `OIL_BOT_PATTERN_SYSTEM.md` §6.

## Inputs

| Source | Field |
|---|---|
| `data/news/catalysts.jsonl` (sub-system 1) | High-severity catalysts in last 24h |
| `data/supply/state.json` (sub-system 2) | Active disruption count + freshness |
| `data/heatmap/cascades.jsonl` (sub-system 3) | Cascades in last 30 min |
| `modules/candle_cache.py` | OHLCV for the lookback window (price change + ATR proxy) |

The iterator does **not** make any new external API calls. It reuses the
existing candle cache and on-disk outputs of #1/#2/#3.

## Outputs

`data/research/bot_patterns.jsonl` (append-only):

```json
{
  "id": "BRENTOIL_2026-04-09T22:30:00+00:00",
  "instrument": "BRENTOIL",
  "detected_at": "2026-04-09T22:30:00+00:00",
  "lookback_minutes": 60,
  "classification": "bot_driven_overextension",
  "confidence": 0.78,
  "direction": "down",
  "price_at_detection": 67.42,
  "price_change_pct": -1.6,
  "signals": ["cascade_long_sev3 (OI -4.2%)", "no_high_sev_catalyst_in_24h",
              "no_fresh_supply_upgrade_72h", "price_move_1.6%_exceeds_1.5x_atr"],
  "notes": "4 bot signals dominate | direction=down move=-1.60%"
}
```

## Heuristic (v1, the only version)

Score each side (base 0.5, +0.1 per signal, capped 0.9):

**Bot-driven signals:**
1. Matching cascade in last `cascade_window_min` (default 30 min)
2. No high-sev catalyst (≥ `catalyst_floor`, default 4) in last 24h
3. No fresh supply disruption upgrade in last 72h
4. Recent price move exceeds N × ATR (default 1.5)

**Informed-move signals:**
1. High-sev catalyst within 24h matching direction
2. Fresh supply state with active disruptions matching up-direction
3. Active chokepoint matching up-direction

**Resolution:**
- Both ≥ 0.65 within 0.1 → `mixed` (capped at 0.65)
- Bot > Informed + 0.1 → `bot_driven_overextension`
- Informed > Bot + 0.1 → `informed_move`
- Otherwise → `unclear` (confidence 0.5)

Moves below `min_price_move_pct_for_classification` (default 0.5%) are
auto-classified as `unclear` to skip noise.

## Configuration

`data/config/bot_classifier.json`:

```json
{
  "enabled": true,
  "instruments": ["BRENTOIL"],
  "poll_interval_s": 300,
  "lookback_minutes": 60,
  "cascade_window_min": 30,
  "catalyst_floor": 4,
  "supply_freshness_hours": 72,
  "atr_mult_for_big_move": 1.5,
  "min_price_move_pct_for_classification": 0.5,
  "patterns_jsonl": "data/research/bot_patterns.jsonl"
}
```

**Kill switch:** flip `enabled` to `false` and the iterator no-ops on the next tick.

## Telegram surface

`/botpatterns [SYMBOL] [N]` — deterministic command (no AI). Default
BRENTOIL, last 10. Renders the most recent classifications with their
signals, direction, and confidence.

## Coexistence

- **Read-only.** No order placement. No mutation of any other sub-system's
  state files. Cannot interact with the existing thesis path.
- **No direction-rule change.** The "LONG or NEUTRAL only on oil" rule
  remains in force at this layer. The §4 relaxation in `OIL_BOT_PATTERN_SYSTEM.md`
  is gated to sub-system 5 only.
- **No CL trading.** Classifier may write CL classifications when enabled,
  but no trade is ever placed.

## Tests

- `tests/test_bot_classifier.py` — pure logic (13 tests)
- `tests/test_bot_classifier_iterator.py` — iterator wiring (8 tests)
- `tests/test_telegram_botpatterns_command.py` — Telegram surface (7 tests)

## Alerts

The iterator emits an `Alert(severity="info")` when a fresh
`bot_driven_overextension` classification crosses confidence ≥ 0.75.
This is the signal sub-system 5 will care about most.
