# Learning Path: Oil Bot-Pattern Strategy

Understanding the 6-subsystem oil trading strategy end-to-end. This is the only place in the codebase where shorting BRENTOIL/CL is legal.

---

## Reading order

### 1. `docs/plans/OIL_BOT_PATTERN_SYSTEM.md` -- Overview spec

**Start here for the big picture.** Defines the 6 sub-systems, their data contracts, the gate chain, and the activation ladder. Everything below implements this spec.

---

### 2. Sub-system 1: `cli/daemon/iterators/news_ingest.py` -- RSS -> catalysts

Polls RSS feeds and iCal calendars for oil-relevant events. Outputs structured catalyst records consumed by downstream sub-systems.

| Item | Value |
|------|-------|
| Config | `data/config/news_ingest.json` |
| Kill switch | `enabled` field in config |
| Output | Catalyst records fed to `catalyst_deleverage` iterator |
| Spec | `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md` |
| Safe in | All tiers (read-only) |

---

### 3. Sub-system 2: `cli/daemon/iterators/supply_ledger.py` -- Disruption tracking

Consumes catalysts from sub-system 1 plus manual `/disrupt` Telegram entries. Aggregates active physical oil supply disruptions into a ledger.

| Item | Value |
|------|-------|
| Config | `data/config/supply_ledger.json` |
| Kill switch | `enabled` field in config |
| Output | `data/supply/state.json` -- active disruption state |
| Spec | `docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md` |
| Safe in | All tiers (read-only) |

---

### 4. Sub-system 3: `cli/daemon/iterators/heatmap.py` -- Liquidity zones + cascades

Polls HyperLiquid `l2Book` + `metaAndAssetCtxs` for configured oil instruments. Clusters resting order depth into liquidity zones and detects liquidation cascades from OI/funding deltas.

| Item | Value |
|------|-------|
| Config | `data/config/heatmap.json` |
| Kill switch | `enabled` field in config |
| Output | `data/heatmap/zones.jsonl` (liquidity zones), `data/heatmap/cascades.jsonl` (cascade events) |
| Spec | `docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md` |
| Safe in | All tiers (read-only, no external deps) |

---

### 5. Sub-system 4: `cli/daemon/iterators/bot_classifier.py` -- Move classification

First sub-system that fuses multiple input streams. Combines catalysts (#1), supply state (#2), cascades (#3), and the candle cache to classify recent moves as bot-driven, informed, mixed, or unclear.

Heuristic only -- NO ML, NO LLM. ML+LLM enhancement (L5) is parked until >=100 closed trades.

| Item | Value |
|------|-------|
| Config | `data/config/bot_classifier.json` |
| Kill switch | `enabled` field in config |
| Output | `data/research/bot_patterns.jsonl` |
| Spec | `docs/plans/OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md` |
| Safe in | All tiers (read-only) |

---

### 6. Sub-system 5: `cli/daemon/iterators/oil_botpattern.py` -- THE STRATEGY ENGINE

**The core.** This is the ONLY place oil shorts are legal, behind a chain of hard gates and TWO master kill switches (`enabled` + `short_legs_enabled`).

Key mechanics:
- **Gate chain**: every trade must pass all gates (classification, supply, heatmap, thesis conflict, drawdown) before an OrderIntent is emitted
- **Conviction sizing**: Druckenmiller-style edge -> notional x leverage ladder
- **Drawdown circuit breakers**: 3% daily / 8% weekly / 15% monthly = ruin floor
- **Funding-cost exit** for longs (no time cap); 24h hard cap on shorts
- **Thesis conflict resolution**: opposite-direction conflicts yield to thesis with 24h lockout
- **Shadow mode**: `decisions_only=true` emits zero OrderIntents (used in WATCH tier)

| Item | Value |
|------|-------|
| Config | `data/config/oil_botpattern.json` |
| Kill switches | `enabled` (master) + `short_legs_enabled` (shorts only). Both ship OFF. |
| Output | `data/strategy/oil_botpattern_journal.jsonl`, `data/strategy/oil_botpattern_state.json` |
| Closed trades also | Appended to `data/research/journal.jsonl` for `lesson_author` pickup |
| Spec | `docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md` |
| Runs in | REBALANCE + OPPORTUNISTIC (also in WATCH but shadow-only) |

---

### 7. Sub-system 6 L1: `cli/daemon/iterators/oil_botpattern_tune.py` -- Bounded auto-tune

Watches closed `oil_botpattern` trades + per-decision journal. Nudges a whitelist of five params in `oil_botpattern.json` within hard YAML bounds.

Guardrails: max +/-5% per nudge, 24h rate limit, minimum 5 sample trades. Zero structural changes (structural tuning is L2).

| Item | Value |
|------|-------|
| Config | `data/config/oil_botpattern_tune.json` |
| Kill switch | `enabled` field (ships OFF) |
| Audit trail | `data/strategy/oil_botpattern_tune_audit.jsonl` |
| Spec | `docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md` |
| Runs in | REBALANCE + OPPORTUNISTIC |

---

### 8. Sub-system 6 L2: `cli/daemon/iterators/oil_botpattern_reflect.py` -- Weekly structural proposals

Runs once per 7 days. Reads closed-trade + decision journals, detects structural patterns (gate overblock, instrument dead, thesis conflict frequency, funding exit cost). Writes `StructuralProposal` records and fires Telegram alerts.

**NEVER auto-applies.** Every proposal requires `/selftuneapprove <id>`.

| Item | Value |
|------|-------|
| Config | `data/config/oil_botpattern_reflect.json` |
| Kill switch | `enabled` field (ships OFF) |
| Output | `data/strategy/oil_botpattern_proposals.jsonl` |
| Telegram commands | `/selftuneapprove <id>` |
| Runs in | REBALANCE + OPPORTUNISTIC |

---

### 9. Sub-system 6 L3: `cli/daemon/iterators/oil_botpattern_patternlib.py` -- Novel pattern detection

Detects novel `(classification, direction, confidence_band, signals)` signatures in `data/research/bot_patterns.jsonl`. Tallies over a 30-day rolling window. Emits `PatternCandidate` records once a signature crosses `min_occurrences`.

| Item | Value |
|------|-------|
| Config | `data/config/oil_botpattern_patternlib.json` |
| Kill switch | `enabled` field (ships OFF) |
| Output | `data/research/bot_pattern_candidates.jsonl` |
| Telegram commands | `/patterncatalog` (review), `/patternpromote <id>` (promote) |
| Runs in | All tiers (read-only observational) |

---

### 10. Sub-system 6 L4: `cli/daemon/iterators/oil_botpattern_shadow.py` -- Counterfactual eval

For each approved L2 proposal, re-runs the affected gate against the last 30 days of decisions. Computes `ShadowEval` -- a look-back counterfactual, NOT a forward paper executor.

| Item | Value |
|------|-------|
| Config | `data/config/oil_botpattern_shadow.json` |
| Kill switch | `enabled` field (ships OFF) |
| Output | `data/strategy/oil_botpattern_shadow_evals.jsonl` |
| Telegram commands | `/shadoweval [id]` |
| Also contains | Adaptive evaluator (exit-only v1), writes `data/strategy/adapt_log.jsonl`, query via `/adaptlog` |
| Runs in | REBALANCE + OPPORTUNISTIC (also WATCH for shadow iterator) |

---

## Data flow diagram

```
RSS feeds / iCal                    Manual /disrupt
       |                                  |
       v                                  v
  [1] news_ingest -----> catalysts -----> [2] supply_ledger
       |                                        |
       |                                        v
       |                                  data/supply/state.json
       |                                        |
       v                                        |
  candle cache                                  |
       |                                        |
       +--------+--------+---------------------+
                |        |        |
                v        v        v
          [3] heatmap    |   [4] bot_classifier
               |         |        |
               v         v        v
          zones.jsonl  cascades  bot_patterns.jsonl
               |         |        |
               +---------+--------+
                         |
                         v
              [5] oil_botpattern (STRATEGY ENGINE)
                    |           |
                    |           +---> OrderIntents -> clock -> exchange
                    |
                    v
              journal.jsonl + state.json
                    |
        +-----------+-----------+
        |           |           |
        v           v           v
  [6-L1] tune  [6-L2] reflect  [6-L3] patternlib
     |               |                    |
     v               v                    v
  nudge params    proposals        pattern candidates
                     |
                     v
              [6-L4] shadow (counterfactual eval)
```

---

## Kill switch locations (all in `data/config/`)

| File | Controls | Ships |
|------|----------|-------|
| `news_ingest.json` | Sub-system 1 | ON |
| `supply_ledger.json` | Sub-system 2 | ON |
| `heatmap.json` | Sub-system 3 | ON |
| `bot_classifier.json` | Sub-system 4 | ON |
| `oil_botpattern.json` | Sub-system 5 master + `short_legs_enabled` | Both OFF |
| `oil_botpattern_tune.json` | Sub-system 6 L1 | OFF |
| `oil_botpattern_reflect.json` | Sub-system 6 L2 | OFF |
| `oil_botpattern_patternlib.json` | Sub-system 6 L3 | OFF |
| `oil_botpattern_shadow.json` | Sub-system 6 L4 | OFF |

---

## Telegram commands

| Command | Purpose |
|---------|---------|
| `/disrupt` | Manually add a supply disruption (feeds sub-system 2) |
| `/selftuneapprove <id>` | Approve an L2 structural proposal |
| `/patterncatalog` | Review L3 pattern candidates |
| `/patternpromote <id>` | Promote an L3 pattern candidate |
| `/shadoweval [id]` | View L4 counterfactual evaluations |
| `/adaptlog` | View adaptive evaluator log |

---

## Tier behavior

| Tier | Sub-systems 1-4 | Sub-system 5 | Sub-system 6 |
|------|-----------------|--------------|---------------|
| WATCH | Run (read-only) | Runs in shadow mode (zero OrderIntents) | L1/L2/L4 registered; L3 active (read-only) |
| REBALANCE | Run | Live execution (if kill switches ON) | All layers active |
| OPPORTUNISTIC | Run | Live execution (if kill switches ON) | All layers active |
