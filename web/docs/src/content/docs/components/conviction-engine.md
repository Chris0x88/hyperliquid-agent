---
title: Conviction Engine
description: Druckenmiller-style thesis system — AI writes conviction, the daemon reads it to size positions, enforce stops, and manage risk.
---

## Design Philosophy

Position sizing scales directly with thesis strength. When conviction is high, size aggressively. When conviction decays, the system enforces its own humility by auto-tapering exposure. Stale theses clamp automatically — no manual intervention required.

---

## Layer 1: ThesisState (Human / AI Writes)

Defined in `common/thesis.py`. Each market gets a `ThesisState` persisted as JSON to `data/thesis/`.

### Thesis Files

| File | Market |
|------|--------|
| `data/thesis/xyz_brentoil_state.json` | Brent crude oil (xyz perp) |
| `data/thesis/btc_perp_state.json` | Bitcoin |
| `data/thesis/gold_state.json` | Gold |
| `data/thesis/silver_state.json` | Silver |

### ThesisState Fields

| Field | Type | Purpose |
|-------|------|---------|
| `market` | string | Market identifier, e.g. `xyz:BRENTOIL`, `BTC-PERP` |
| `direction` | string | `long`, `short`, or `flat` |
| `conviction` | float | 0.0 to 1.0 — raw conviction strength |
| `thesis_summary` | string | Human-readable reasoning for the position |
| `evidence_for` | list | Timestamped `Evidence` entries (source, text, weight) supporting the thesis |
| `evidence_against` | list | Timestamped `Evidence` entries opposing the thesis |
| `invalidation_conditions` | list | Conditions (not price levels) that would kill the thesis |
| `take_profit_price` | float | Thesis-based take-profit target |
| `recommended_leverage` | float | Maximum leverage for this thesis |
| `tactical_notes` | string | Short-term tactical context (entry zones, catalysts) |
| `updated_at` | datetime | Last update timestamp (drives staleness) |

Claude Code sessions (you) or the AI agent via the `update_thesis` tool write these files. The daemon never writes them — it only reads.

---

## Staleness Protection

`ThesisState.effective_conviction()` applies tiered tapering based on `updated_at`:

| Age | Behavior |
|-----|----------|
| < 24 hours | Full stated conviction |
| 24h - 72h | `needs_review` flag set. Telegram reminder sent |
| 7 - 14 days (`is_stale`) | Linear taper from stated conviction down to 0.3 |
| 14+ days (`is_very_stale`) | Clamped to 0.3 (defensive floor) |

The `ThesisEngineIterator` applies an additional in-memory clamp: older than 72h means conviction is halved before the execution engine sees it.

Thesis files are designed to be valid for months or years for structural views. The staleness system does not delete them — it reduces their influence on sizing until they are refreshed.

---

## Layer 2: ExecutionEngine (Daemon Reads)

Defined in `cli/daemon/iterators/execution_engine.py`. Active in REBALANCE and OPPORTUNISTIC tiers only.

Each tick:

1. Reads `ctx.thesis_states` (populated by ThesisEngineIterator)
2. Maps effective conviction to target position size via bands
3. Checks authority (only acts on assets delegated to `agent`)
4. Applies time-aware leverage caps
5. Generates `OrderIntent`s if position delta exceeds 5% of target

### Conviction Bands

| Conviction | Target Size (% equity) | Max Leverage | Band |
|-----------|----------------------|-------------|------|
| 0.8 - 1.0 | 20% | 15x | full |
| 0.5 - 0.8 | 12% | 10x | standard |
| 0.2 - 0.5 | 6% | 5x | cautious |
| 0.0 - 0.2 | 0% | 0x | exit |

### Time-Aware Caps

| Condition | Effect |
|-----------|--------|
| Weekend | 50% leverage reduction (thin liquidity) |
| Asia open on oil | 7x max leverage (thin session) |
| Normal hours | Full bands apply |

---

## Ruin Prevention (Unconditional)

Hardcoded in ExecutionEngine. Cannot be overridden by any thesis file or configuration:

- **25% drawdown** from session high: halt all new entries
- **40% drawdown**: close ALL positions immediately

---

## Exchange Protection (Mandatory SL/TP)

The `exchange_protection` iterator (REBALANCE+ only) enforces that every position has both a stop-loss and take-profit order on the exchange. See [Protection & Monitoring](/components/heartbeat/) for details.

- **Stop-loss:** ATR-based (computed by `market_structure` iterator)
- **Take-profit:** From thesis `take_profit_price`, or mechanical 5x ATR if no thesis target
- **No exceptions.** Every position must have both.

---

## Kill Switches

Two ways to shut down conviction-driven execution:

1. **Set `direction` to `"flat"`** in the thesis file — the execution engine treats flat as an exit signal
2. **Set `conviction` to `0`** in the thesis file — maps to the exit band (0% target size)

There is no separate `conviction_bands.json` configuration file. The bands are defined in the ExecutionEngine source code. To disable all autonomous execution, downgrade the daemon tier to WATCH.
