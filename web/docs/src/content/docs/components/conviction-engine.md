---
title: Conviction Engine
description: Two-layer thesis system with Druckenmiller-style sizing — AI writes conviction, daemon reads it to size positions.
---

## Design Philosophy

Modeled after Druckenmiller's "when you have 70-80% conviction, go for the jugular" approach. Position sizing scales directly with thesis strength. The system enforces its own humility — stale theses auto-clamp.

---

## Layer 1: ThesisState (You / AI Write)

Defined in `common/thesis.py`. Each market gets a `ThesisState` persisted to `data/thesis/{market}_state.json`.

Key fields:

| Field | Purpose |
|-------|---------|
| `market` | e.g. `xyz:BRENTOIL`, `BTC-PERP` |
| `direction` | `long`, `short`, or `flat` |
| `conviction` | 0.0 to 1.0 |
| `thesis_summary` | Human-readable reasoning |
| `evidence_for` / `evidence_against` | Timestamped Evidence entries with source and weight |
| `invalidation_conditions` | Conditions (not price levels) that kill the thesis |
| `take_profit_price` | Thesis-based TP target |
| `recommended_leverage` | Max leverage for this thesis |

Claude Code sessions (you) or the AI agent via `update_thesis` tool write these files. The daemon never writes them.

---

## Staleness Protection

`ThesisState.effective_conviction()` applies tiered tapering automatically:

| Age | Behavior |
|-----|----------|
| < 24h | Full stated conviction |
| 24h–72h | `needs_review` flag, Telegram reminder sent |
| 7–14 days | Linear taper from stated conviction down to 0.3 |
| 14+ days | Clamped to 0.3 (defensive floor) |

The `ThesisEngineIterator` applies an additional in-memory clamp: older than 72h = conviction halved before the execution engine sees it.

---

## Layer 2: ExecutionEngine (Daemon Reads)

Defined in `cli/daemon/iterators/execution_engine.py`. Active in REBALANCE and OPPORTUNISTIC tiers.

Each tick:
1. Reads `ctx.thesis_states` (populated by ThesisEngineIterator)
2. Maps conviction to target position size via bands
3. Checks authority (only acts on assets delegated to `agent`)
4. Applies time-aware leverage caps
5. Generates `OrderIntent`s if position delta exceeds 5% of target

### Conviction Bands

| Conviction | Target Size (% equity) | Max Leverage | Band |
|-----------|----------------------|-------------|------|
| 0.8–1.0 | 20% | 15x | full |
| 0.5–0.8 | 12% | 10x | standard |
| 0.2–0.5 | 6% | 5x | cautious |
| 0.0–0.2 | 0% | 0x | exit |

### Time-Aware Caps

- **Weekend:** 50% leverage reduction (thin liquidity)
- **Thin session (Asia open on oil):** 7x max leverage
- Normal hours: full bands apply

---

## Ruin Prevention (Unconditional)

Hardcoded in ExecutionEngine. Cannot be overridden by any thesis file:

- **25% drawdown from session high** → halt all new entries
- **40% drawdown** → close ALL positions immediately

---

## Kill Switch

Set `conviction_bands.enabled = false` in `data/config/conviction_bands.json` to disable all conviction-driven execution. The system reverts to monitoring-only mode regardless of tier.
