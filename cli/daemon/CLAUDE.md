# cli/daemon/ — Daemon Architecture (Running in Production)

Hummingbot-style tick engine with tiered iterator execution. Running on mainnet in WATCH tier via launchd.

## Key Files

| File | Purpose |
|------|---------|
| `clock.py` | Main tick loop, HealthWindow error budget, circuit breaker |
| `context.py` | `TickContext` hub node, `OrderState` lifecycle tracking |
| `config.py` | `DaemonConfig` — tier, tick_interval, mock, mainnet |
| `tiers.py` | Maps tiers → iterator sets (WATCH / REBALANCE / OPPORTUNISTIC) |
| `state.py` | `StateStore` — PID management, persistent state |
| `iterators/` | All daemon iterators — one file per iterator |

**Deep dive:** [docs/wiki/components/daemon.md](../../docs/wiki/components/daemon.md) | [docs/wiki/components/risk-manager.md](../../docs/wiki/components/risk-manager.md)

## Launch

```bash
# Via launchd (production):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist

# Direct (testing):
hl daemon start --tier watch --mainnet --tick 120
hl daemon start --tier watch --mock --max-ticks 10  # safest test
```

## Known Iterators

> Full inventory lives in `iterators/` — grep `class .*Iterator` for the live set.
> Only iterators with external-facing contracts, kill switches, or recent ship
> context are called out here.

- `news_ingest` — sub-system 1 of the Oil Bot-Pattern Strategy. Polls RSS/iCal
  feeds and feeds structured catalysts to `catalyst_deleverage`. Kill switch:
  `data/config/news_ingest.json`. Spec: `agent-cli/docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md`.
- `supply_ledger` — sub-system 2 of the Oil Bot-Pattern Strategy. Consumes
  `news_ingest` catalysts + manual `/disrupt` Telegram entries, aggregates active
  physical oil disruptions into `data/supply/state.json`. Kill switch:
  `data/config/supply_ledger.json`. Spec: `agent-cli/docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md`.
- `heatmap` — sub-system 3 of the Oil Bot-Pattern Strategy. Polls HL `l2Book` +
  `metaAndAssetCtxs` for configured oil instruments; clusters resting depth into
  liquidity zones (`data/heatmap/zones.jsonl`) and detects liquidation cascades
  from OI/funding deltas (`data/heatmap/cascades.jsonl`). Read-only, no external
  deps. Kill switch: `data/config/heatmap.json`. Spec:
  `agent-cli/docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md`.
- `bot_classifier` — sub-system 4 of the Oil Bot-Pattern Strategy. First sub-system
  that consumes multiple input streams: combines #1 catalysts, #2 supply state,
  #3 cascades, and the candle cache to classify recent moves as bot-driven,
  informed, mixed, or unclear. Heuristic only — NO ML, NO LLM (L5 deferred per
  SYSTEM doc §6). Writes `data/research/bot_patterns.jsonl`. Read-only. Kill switch:
  `data/config/bot_classifier.json`. Spec:
  `agent-cli/docs/plans/OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md`.
- `oil_botpattern` — sub-system 5 of the Oil Bot-Pattern Strategy. **THE ONLY
  PLACE in the codebase where shorting BRENTOIL/CL is legal**, behind a chain of
  hard gates and TWO master kill switches (`enabled` + `short_legs_enabled`).
  Conviction sizing (Druckenmiller-style edge → notional × leverage ladder) with
  drawdown circuit breakers (3% daily / 8% weekly / 15% monthly) as the ruin floor.
  Funding-cost exit for longs (no time cap); 24h hard cap on shorts. Coexists
  with the existing thesis_engine path per SYSTEM doc §5 — opposite-direction
  conflicts yield to thesis with 24h lockout. Runs in REBALANCE + OPPORTUNISTIC
  only (NOT WATCH). Writes `data/strategy/oil_botpattern_{journal.jsonl,state.json}`.
  Closed positions also append to `data/research/journal.jsonl` so `lesson_author`
  auto-picks them up. Both kill switches ship OFF by default. Kill switch:
  `data/config/oil_botpattern.json`. Spec:
  `agent-cli/docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md`.
- `lesson_author` — Trade Lesson Layer (wedge 5). Detects closed positions and
  writes lesson candidate files for agent-authored post-mortems. Output feeds
  the FTS5 lessons table in `common/memory.py`. See build-log 2026-04-09 for context.

## Gotchas

- Single-instance: pacman kill pattern (SIGTERM → sleep → SIGKILL)
- Risk gate states: OPEN / COOLDOWN / CLOSED — see risk-manager.md
- HWM auto-resets when flat (no positions) to prevent phantom drawdowns
- total_equity = perps (native + xyz) + spot USDC
