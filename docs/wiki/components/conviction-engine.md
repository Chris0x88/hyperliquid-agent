# Conviction Engine

Two-layer system where AI writes conviction and the daemon reads it to size positions. Modeled after Druckenmiller's "70-80% conviction, go for the jugular" philosophy.

## Layer 1: ThesisState (AI Writer)

Defined in `common/thesis.py`. Each market gets a `ThesisState` dataclass persisted to `data/thesis/{market_slug}_state.json`. Fields include:

- **market** -- e.g. `xyz:BRENTOIL`, `BTC-PERP`
- **direction** -- `long`, `short`, or `flat`
- **conviction** -- 0.0 to 1.0
- **thesis_summary** -- human-readable reasoning
- **evidence_for / evidence_against** -- timestamped `Evidence` entries with source and weight
- **invalidation_conditions** -- conditions (not price levels) that would kill the thesis
- **take_profit_price** -- thesis-based TP target (e.g. gold at $10k)
- **recommended_leverage**, **recommended_size_pct**, **weekend_leverage_cap**

Claude Code (or the AI agent via `update_thesis` tool) writes these files. The daemon never writes to them.

## Staleness Protection

`ThesisState.effective_conviction()` applies tiered tapering:

| Age | Behavior |
|-----|----------|
| < 24h | Full conviction. |
| 24h+ | `needs_review` flag -- Telegram reminder sent. |
| 7-14 days | Linear taper from stated conviction down to 0.3. |
| 14+ days | Clamped to 0.3 (defensive). |

Additionally, `ThesisEngineIterator` (in `cli/daemon/iterators/thesis_engine.py`) applies its own clamp: >72h = conviction halved in-memory before the daemon sees it.

## Layer 2: ExecutionEngine (Daemon Reader)

Defined in `cli/daemon/iterators/execution_engine.py`. Active in REBALANCE and OPPORTUNISTIC tiers. Each tick it:

1. Reads `ctx.thesis_states` (populated by ThesisEngineIterator)
2. Maps conviction to target position size via bands
3. Checks authority (only acts on assets delegated to "agent")
4. Applies time-aware leverage caps (weekend: 50% reduction, thin session: 7x cap)
5. Generates `OrderIntent`s if position delta exceeds 5% of target

### Conviction Bands

| Conviction | Target Size (% equity) | Max Leverage | Band |
|-----------|----------------------|-------------|------|
| 0.8-1.0 | 20% | 15x | full |
| 0.5-0.8 | 12% | 10x | standard |
| 0.2-0.5 | 6% | 5x | cautious |
| 0.0-0.2 | 0% | 0x | exit |

Configurable via `ConvictionBands` in `common/heartbeat_config.py` with finer-grained interpolation bands (defensive/small/medium/large/max).

## Authority System

Defined in `common/authority.py`. Per-asset delegation controls who manages each position:

- **agent** -- bot manages entries, exits, sizing. Full conviction engine.
- **manual** (default) -- user trades. Bot is safety-net only (ensures SL/TP exist).
- **off** -- not watched at all.

Telegram commands: `/delegate <ASSET>`, `/reclaim <ASSET>`, `/authority`. Config stored in `data/authority.json`.

## Kill Switch

Set `conviction_bands.enabled = false` in `data/config/conviction_bands.json` to disable all conviction-driven execution. The system reverts to monitoring-only mode.

## Ruin Prevention (Unconditional)

Hardcoded in ExecutionEngine, cannot be overridden by thesis:
- **25% drawdown** -- halt all new entries
- **40% drawdown** -- close ALL positions immediately
