# Oil Bot-Pattern Strategy — System Overview

> **Status:** Approved 2026-04-09. Sub-system 1 enters detailed spec.
> **Scope:** A new oil-trading subsystem that exploits bot-driven mispricing
> on CL (WTI) and BRENTOIL on Hyperliquid, by combining scraped news,
> tracked physical supply disruptions, orderbook stop-cluster detection,
> and bot-pattern classification into a fixed strategy with a bounded
> self-improvement harness.
> **Author:** Brainstormed with Chris (petroleum-engineer edge holder).
> **Build order is enforced:** sub-systems ship one at a time with kill switches.
> No sub-system that has not yet shipped is allowed to be referenced as a
> live dependency.

---

## 1. Origin and rationale

The triggering observation (Chris, 2026-04-09):

> Markets are dumb. ~80% of trades are bots reacting to known information,
> not forecasting. Ahead of major scheduled catalysts (e.g. Trump's 8 PM
> Iran deadline), oil drifted up to the minute, then violently
> over-corrected ~20% on the no-deal-yet-then-deal pattern, despite
> Russian/Iranian refinery damage and Middle East supply disruptions
> remaining offline. A petroleum engineer trying to forecast the
> fundamental gets killed by bots that don't read the supply ledger.
> The arbitrage: be early on the obvious thing, then fade the bot
> overcorrection when it lands.

The strategy's job is to encode that arbitrage as a fixed, testable,
risk-bounded system that runs without daily human intervention.

## 2. What this system is NOT

- **Not** a replacement for the existing BRENTOIL thesis path. The
  Druckenmiller-style conviction engine and `data/thesis/xyz_brentoil_state.json`
  remain the sole writers for BRENTOIL positions held > 24h.
- **Not** an online ML system. The data is too sparse (low-hundreds of
  trades/year) for gradient learning to beat classical heuristics with
  bounded auto-tune. ML may be added at L5 once ≥100 closed trades exist
  to train against; until then it is fairy dust.
- **Not** a news-summarisation product. News ingestion publishes
  catalysts to existing infrastructure; it does not editorialise.
- **Not** a multi-asset engine. CL and BRENTOIL only. Anything else
  (NATGAS, equities, memecoins) is explicitly out of scope and remains
  blocked by the existing approved-markets list.

## 3. Decomposition

Six sub-systems. Built in order. Each ships behind its own kill switch
(`data/config/<sub>.json` `enabled` flag). Each is independently testable
in mock mode before going live.

```
 ① News & catalyst ingestion (RSS) ─────┐
                                        ├─▶ ④ Bot-pattern classifier ─▶ ⑤ Strategy ─▶ ⑥ Self-tune
 ② Supply disruption ledger ────────────┤                                    (CL+BRENT)    harness
                                        │
 ③ Stop / liquidity heatmap ────────────┘                                                  (L0-L4)
```

| # | Sub-system | Inputs | Outputs | Why this slot |
|---|---|---|---|---|
| 1 | News & catalyst ingestion | RSS feeds, iCal calendars | `data/news/headlines.jsonl`, `data/news/catalysts.jsonl`, appended `catalyst_events.json` | Foundation. Smallest ship. Feeds the existing CatalystDeleverage iterator on day 1. |
| 2 | Supply disruption ledger | #1 headlines (auto), Telegram `/disrupt` (manual), scheduled scrapers | `data/supply/disruptions.jsonl`, `physical_offline_total` series, chokepoint status | Encodes Chris's petroleum-engineering edge as structured data. The "we know more than the bots" piece. |
| 3 | Stop / liquidity heatmap | HL L2 orderbook, OI, recent liquidations, funding | `data/heatmap/zones.jsonl`, `data/heatmap/cascades.jsonl` | Pure HL API. No external deps. Independent of #1/#2. |
| 4 | Bot-pattern classifier | #1 catalysts, #2 supply state, #3 zones, candles, OI | `data/research/bot_patterns.jsonl` (signals with confidence) | Needs all three input streams to label moves as bot-driven vs informed. |
| 5 | Strategy engine | All four above | OrderIntents tagged `strategy_id="oil_botpattern"` | Only piece that places trades. Coexists with existing BRENTOIL thesis path per §5. |
| 6 | Self-tune harness | Strategy journal, parameter bounds | Auto-tuned params, weekly Telegram digest of structural proposals | Wraps #5. Has nothing to tune until #5 is alive. |

## 4. Markets and direction rule

**Markets:** CL (WTI), BRENTOIL. Both. The strategy must encode the
WTI↔Brent spread relationship: WTI is (historically) landlocked-driven
by Cushing storage and US refinery cracks; Brent carries more of the
geopolitical premium and tanker-route risk. The two correlate ~80% but
diverge on supply-side specifics. The strategy engine reads BOTH price
series and decides which to enter based on (a) which side of the spread
has cleaner setup, (b) HL depth at decision time, (c) which fundamental
input from sub-system 2 is most relevant.

**Promotion of CL:** CL is currently `tracked but unsupported` per
`CLAUDE.md`. Sub-system 5 promotes it to a real, thesis-eligible market
when it ships. Until then, sub-systems 1-4 may write CL signals but no
trade is placed.

**Direction rule (CRITICAL CHANGE FROM EXISTING POLICY):** The
long-standing rule "LONG or NEUTRAL only on oil — never short" is
**scoped-relaxed** for this strategy and this strategy only:

- Sub-system 5 may open SHORT positions on CL or BRENTOIL **only when**
  ALL of these hold:
  - Sub-system 4 (bot-pattern classifier) tags the current move as
    `bot_driven_overextension` with confidence ≥ 0.7
  - Sub-system 1 has no active high-severity (≥4) bullish catalyst
    pending in the next 24h
  - Sub-system 2 has no recent (≤72h) supply-disruption upgrade that
    would make a short trade fight the fundamental
  - Position size ≤ 50% of the long-side budget for the same instrument
  - Time-in-trade hard cap: 24h (no overnight shorts past one session)
  - Daily realised loss cap on the short layer: 1.5% of equity
- All other oil shorting remains forbidden across the rest of the system.
- The relaxation lives in `data/config/oil_botpattern.json` as
  `short_legs_enabled: true` with the guardrails above as field defaults.
  Setting `short_legs_enabled: false` is the kill switch.

When sub-system 5 ships, `CLAUDE.md` and the relevant memory files MUST
be updated to reflect the scoped relaxation. **Do not update them now;
update at sub-system 5 ship time.**

## 5. Coexistence rule (writer-conflict resolution)

The new strategy is **additive-only with tier ownership** so it cannot
corrupt the existing BRENTOIL thesis path:

- Existing `thesis_engine` + `data/thesis/xyz_brentoil_state.json` remain
  the SOLE writers for BRENTOIL positions held > 24h.
- New strategy writes only **tactical positions** (intraday + first 24h
  hold). Every order carries `strategy_id="oil_botpattern"` and
  `intended_hold_hours <= 24`.
- Per-instrument budget cap lives in `data/config/risk_caps.json` under
  `oil_botpattern.{BRENTOIL,CL}.max_pct_equity`. Default 8%.
- Conflict resolution:
  - Same direction → bot-pattern stacks on top up to its own cap.
  - Opposite direction → existing long-horizon thesis WINS. Bot-pattern
    is locked out of that instrument until either (a) the thesis turns
    flat or (b) 24h elapse, whichever first.
  - No thesis (i.e. CL): bot-pattern is the only writer.
- All positions, regardless of strategy, continue to obey the global
  CLAUDE.md rule "every position MUST have both SL and TP on exchange"
  via `exchange_protection`. No exceptions, no special path.

## 6. Self-improvement harness (the "tired of directing" answer)

Six layers, escalating in autonomy. The bottom three run silently. The
top three are batched into a once-weekly Telegram digest so Chris can
review in one sitting instead of being pinged in real time.

| Layer | What it does | Cadence | Human in loop |
|---|---|---|---|
| **L0 — Hard contracts** | Tests fail before bad code ships. Verification before completion. SL+TP enforced. JSON schemas on every data file. | Per commit / per tick | None — automatic |
| **L1 — Bounded auto-tune** | Strategy params have hard min/max in YAML. Journal-replay nudges them within bounds after every closed trade. Audit-logged. | Per closed trade | None — automatic |
| **L2 — Reflect proposals** | Existing autoresearch reflect loop reads journal weekly, posts STRUCTURAL changes (new patterns, new bounds, new market) to Telegram. | Weekly digest | Chris — one tap promote/reject |
| **L3 — Pattern library growth** | Classifier auto-adds new bot-pattern signatures to versioned catalog. Catalog grows freely; live signal set requires one tap to promote. | Per new pattern | Chris — one tap |
| **L4 — Shadow trading** | Every L2/L3 proposal runs in shadow (paper) mode for ≥ N closed trades before being eligible for promotion. The system collects its own evidence. | Per proposal | None — automatic |
| **L5 — ML overlay (deferred)** | A small model on top of L4 evidence. ONLY after ≥100 closed trades. Until then: not implemented. | Deferred | Chris — model gating |

The contract: **The system is allowed to LEARN automatically. The system
is not allowed to CHANGE STRUCTURE without one human tap.** Crossing
that line is how trading systems blow up overnight. This contract is
non-negotiable across all six sub-systems.

## 7. Build-order constraint

Each sub-system MUST ship with these gates BEFORE the next is started:

1. Code committed and tests passing
2. Mock-mode end-to-end run produces expected outputs
3. Live-mode dry-run for ≥ 24h with kill switch verified working
4. Wiki page updated under `agent-cli/docs/wiki/components/`
5. CLAUDE.md updated if any new rules or surfaces were added
6. Build-log entry under `agent-cli/docs/wiki/build-log.md`

Skipping a gate to chase the next sub-system is the failure mode this
plan exists to prevent.

## 8. Open per-sub-system specs

Each sub-system gets its own spec file under `agent-cli/docs/plans/`:

- `OIL_BOT_PATTERN_01_NEWS_INGESTION.md` — drafted 2026-04-09 (sub-system 1)
- `OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md` — TBD (next brainstorm)
- `OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md` — TBD
- `OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md` — TBD
- `OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md` — TBD
- `OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md` — TBD

## 9. Things deliberately deferred

- Twitter/X scraping (revisit only if RSS misses too much)
- LLM-based headline summarisation (sparse value, real cost)
- Sub-account isolation for the new strategy (only one xyz subaccount available; budget caps suffice)
- Online ML model (L5; ≥100 closed trades required before re-evaluation)
- Promoting CL to the existing thesis_engine path (separate decision; this strategy treats CL as its own writer)
