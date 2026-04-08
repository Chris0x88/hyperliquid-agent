# Sub-system 4 — Bot-Pattern Classifier

**Slot in `OIL_BOT_PATTERN_SYSTEM.md`:** row 4. First sub-system that
consumes multiple input streams. Read-only.

## What it is

A read-only iterator that periodically (default every 300s) scores each
configured oil instrument's recent move and emits a classification record:

- `bot_driven_overextension` — likely shake-out / cascade-driven move
  with no fundamental support
- `informed_move` — move backed by a high-severity catalyst or supply
  disruption
- `mixed` — both bot-driven and informed signals present
- `unclear` — neither signal dominates; insufficient evidence

Each record includes a `confidence` score (0..1), the contributing
signals as plain-text evidence strings, and the price + window context
needed for downstream sub-systems #5 (strategy engine) and #6
(self-tune harness) to consume.

The iterator NEVER places trades. Heuristic-only — **no ML, no LLM**.
Layer L5 (ML overlay) is explicitly deferred per `OIL_BOT_PATTERN_SYSTEM.md`
§6. Kill switch: `data/config/bot_classifier.json → enabled: false`.

## Why this slot

- It's the first sub-system that **needs** multiple streams. #1 catalysts,
  #2 supply state, and #3 cascades are all live, so #4 has real data to
  work with from day 1.
- It's **deterministic and testable**. The classification is a pure
  function of the recent windows of #1/#2/#3 + price/OI deltas. Same
  inputs → same outputs.
- It's the gate for sub-system #5. The strategy engine reads
  `bot_patterns.jsonl` to decide when the scoped short-leg relaxation
  on oil is allowed.

## Inputs

| Source | Field |
|---|---|
| `data/news/catalysts.jsonl` (sub-system 1) | High-severity catalysts in the last 24h |
| `data/supply/state.json` (sub-system 2) | Active disruption count + freshness |
| `data/heatmap/cascades.jsonl` (sub-system 3) | Cascades in the last 30 min |
| `data/heatmap/zones.jsonl` (sub-system 3) | Latest zone snapshot per instrument |
| `modules/candle_cache.py` (existing) | OHLCV for the lookback window |
| HL `metaAndAssetCtxs` | Current OI + funding (via injectable HTTP, like sub-system 3) |

The classifier does **not** make any new external API calls beyond what
sub-system 3 already pulls. It reuses the existing candle cache and
config-driven HTTP injection.

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
  "signals": [
    "cascade_long_sev3 (OI -4.2% in 180s)",
    "no_high_sev_catalyst_in_24h",
    "no_fresh_supply_upgrade_72h",
    "price_move_exceeds_atr"
  ],
  "notes": "long cascade with clean fundamentals — likely bot shake"
}
```

## Heuristic (v1, the only version planned for now)

The classifier is intentionally simple. Score each side; the higher
score wins.

**Bot-driven signals (+0.1 each, base 0.5):**
1. Cascade in last `cascade_window_min` (default 30min) — and direction
   matches the move
2. No high-severity (≥ `catalyst_floor`, default 4) catalyst in last 24h
3. No fresh supply disruption upgrade in last 72h
4. Recent price move exceeds N × ATR (default 1.5)

**Informed-move signals (+0.1 each, base 0.5):**
1. High-severity catalyst in last 24h matching direction
2. Fresh supply disruption upgrade matching direction
3. Active chokepoint that didn't exist a week ago

**Resolution:**
- If `bot_score > informed_score + 0.1`: `bot_driven_overextension`,
  confidence = `bot_score`
- If `informed_score > bot_score + 0.1`: `informed_move`,
  confidence = `informed_score`
- If both ≥ 0.65 and within 0.1 of each other: `mixed`,
  confidence = min(bot, informed)
- Otherwise: `unclear`, confidence = 0.5

Confidence is capped at 0.9 for clean classifications and 0.65 for `mixed`.

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

`min_price_move_pct_for_classification` is the floor — moves below this
get `unclear` classification regardless of other signals (no point
classifying noise).

## Telegram surface

`/botpatterns [SYMBOL] [N]` — deterministic. Default: BRENTOIL, last 10.
Reads `bot_patterns.jsonl` and renders the most recent classifications
with their signals and confidence.

## Coexistence

- **Read-only.** No order placement. No mutation of any other sub-system's
  state files.
- **No direction-rule change at this layer.** The "LONG or NEUTRAL only on
  oil" rule remains in force at sub-system 4. The §4 relaxation in the
  SYSTEM doc stays gated to sub-system 5.
- **No CL trading.** Classifier may write CL classifications when enabled,
  but no trade is ever placed — sub-system 5 is the gatekeeper.

## What's deliberately NOT in this sub-system

- ML model — deferred to L5 in §6 of the SYSTEM doc
- Order placement — sub-system 5
- Self-tuning of thresholds — sub-system 6
- Pattern library growth (L3) — sub-system 6
- New external HTTP fetches (catalysts/zones already on disk via #1/#3)

## 🔮 DEFERRED ENHANCEMENT — ML + LLM assistance (revisit)

**Status:** parked. Comeback target: after ≥100 closed trades exist in
the journal so there's real ground-truth labelling material.

The v1 classifier here is intentionally a hand-coded heuristic so we
ship something deterministic, testable, and explainable. The path
forward, when we come back to this, has two layers:

1. **ML overlay (Layer L5 in SYSTEM doc §6)** — a small model trained
   on `bot_patterns.jsonl` joined with `journal.jsonl` outcomes. Goal:
   replace the score-summing rule in `_resolve()` with a learned
   probability calibrated against actual P&L outcomes. Constraint per
   §6: ONLY after ≥100 closed trades, gated behind a Chris-tap promote.
   Until then we collect labelled data via L4 shadow trading.

2. **LLM assistance** — at the *signal contribution* layer, not the
   classification layer. Two concrete uses:
   - Catalyst direction inference: today the catalyst's `direction`
     field is whatever sub-system 1 wrote. An LLM pass over the headline
     body could fill in or correct ambiguous direction tags before they
     reach the classifier. This is a pre-processing improvement on
     sub-system 1, surfaced here because it changes what the classifier
     sees.
   - Plain-language signal explanation: today `signals` is a list of
     short tags. An LLM could write a one-sentence narrative for each
     classification ("BTC ripped through the ask wall while OPEC was
     silent and OI dropped 4%—classic shake"). Lives BESIDE the
     classification, never inside it. Read-only narrative for `/botpatterns`
     and lessons-corpus consumption.

**Both layers must respect the existing rules:**
- Slash commands stay deterministic. Any LLM-touched output gets
  routed through the `ai` suffix path or lives in a separate
  `/botpatternsai` command. The pure `/botpatterns` command must stay
  AI-free.
- Classification confidence is still the ground truth that sub-system 5
  gates on. ML can replace the rule that produces it, but the contract
  (a `BotPattern` record with `confidence` 0..1 and `classification` ∈
  CLASSIFICATIONS) is fixed.
- Kill switches per layer: if the ML model goes rogue, flip a config
  flag and fall back to the heuristic. If the LLM narrative goes
  rogue, drop the narrative field — classification keeps working.

**Why we're not doing it now:** zero labelled data, no model would be
better than the heuristic, and shipping the rule-based version
unblocks sub-system 5 (which only needs the `confidence ≥ 0.7` signal,
not the mechanism that produced it).

When we come back: write a fresh plan doc, don't edit this one.


## Spec links

- `OIL_BOT_PATTERN_SYSTEM.md` — overall architecture
- `OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md` — sub-system 3 outputs consumed here
- `OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md` — sub-system 2 outputs consumed here
- `OIL_BOT_PATTERN_01_NEWS_INGESTION.md` — sub-system 1 outputs consumed here
