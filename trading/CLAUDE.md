# trading/ — Per-Market Systems + Shared Trading Infrastructure

Market-specific trading systems and shared position management. Each market gets its own sub-package. Shared infra lives at root.

## Shared Infrastructure (root level)

| File | Purpose |
|------|---------|
| `heartbeat.py` | Position management — dip-add, trim, SL/TP enforcement (1700 lines) |
| `heartbeat_config.py` | Heartbeat configuration + conviction bands |
| `heartbeat_state.py` | ATR, position state tracking |
| `consolidation.py` | Candle consolidation, ladder order calculation |
| `conviction_engine.py` | Conviction band sizing system |

## Per-Market Systems

| Package | Purpose |
|---------|---------|
| `oil/` | Oil bot-pattern strategy — engine, tune, reflect, shadow, patternlib, paper, adaptive |
| `thesis/` | Thesis management — challenger (mechanical), updater (Haiku-powered) |

## Adding a New Market

Create a new subdirectory: `trading/btc/`, `trading/gold/`, etc. Each market system can import shared engines from `engines/` and use the shared infra at this level.

## Gotchas

- heartbeat.py is the trade execution brain — changes here affect live positions
- Oil bot-pattern has kill switches — check `data/config/` before enabling
- thesis/ works per-market (each market has its own thesis file in `data/thesis/`)
- conviction_engine.py drives sizing across all markets
