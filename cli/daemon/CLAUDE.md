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
- `oil_botpattern_tune` — sub-system 6 L1 of the Oil Bot-Pattern Strategy. Bounded
  auto-tune wrapped around sub-system 5. Watches closed `oil_botpattern` trades +
  the per-decision journal, nudges a whitelist of five params in
  `oil_botpattern.json` within hard YAML bounds (max ±5% per nudge, 24h rate
  limit, min sample 5). Zero structural changes — structural tuning lives in L2.
  Kill switch: `data/config/oil_botpattern_tune.json`. Audit trail at
  `data/strategy/oil_botpattern_tune_audit.jsonl`. Registered REBALANCE +
  OPPORTUNISTIC only. Spec:
  `agent-cli/docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md`.
- `oil_botpattern_reflect` — sub-system 6 L2. Runs once per 7 days. Reads the
  closed-trade + decision journals, detects structural patterns (gate overblock,
  instrument dead, thesis_conflict_frequent, funding_exit_expensive), writes
  `StructuralProposal` records to
  `data/strategy/oil_botpattern_proposals.jsonl`, and fires a Telegram warning
  alert with new proposal IDs. **NEVER auto-applies** — every proposal requires a
  `/selftuneapprove <id>` tap. Kill switch:
  `data/config/oil_botpattern_reflect.json`. Registered REBALANCE + OPPORTUNISTIC
  only. Same spec.
- `oil_botpattern_patternlib` — sub-system 6 L3. Pattern library growth. Detects
  novel `(classification, direction, confidence_band, signals)` signatures in
  `data/research/bot_patterns.jsonl`, tallies over a 30-day rolling window, emits
  `PatternCandidate` records to
  `data/research/bot_pattern_candidates.jsonl` once a signature crosses
  `min_occurrences`. Review via `/patterncatalog`, promote via
  `/patternpromote <id>`. Kill switch: `data/config/oil_botpattern_patternlib.json`.
  Read-only; all tiers including WATCH.
- `oil_botpattern_shadow` — sub-system 6 L4. Counterfactual shadow evaluation.
  For each approved L2 proposal, re-runs the affected gate against the last 30
  days of decisions and computes `ShadowEval`. **Look-back counterfactual, NOT
  a forward paper executor.** Writes
  `data/strategy/oil_botpattern_shadow_evals.jsonl`. Review via `/shadoweval [id]`.
  Kill switch: `data/config/oil_botpattern_shadow.json`. Registered REBALANCE +
  OPPORTUNISTIC only.
- `oil_botpattern` adaptive evaluator — live thesis-testing evaluator plumbed
  into the shadow-mode iterator. Exit-only v1 today. Writes
  `data/strategy/adapt_log.jsonl`; query via `/adaptlog`. Shadow-only by design.
- `entry_critic` — Trade Entry Critic. Deterministic grading on every new entry
  with lesson recall + suggestions. Command surface: `/critique`. Kill switch:
  `data/config/entry_critic.json`.
- `action_queue` — User-action queue (daily sweep). Maintains the list of
  operator rituals (memory restore drill quarterly, `/brutalreviewai` weekly,
  thesis refresh checks, feedback aging, etc.) with cadence + last-done
  timestamps + Telegram nudges. Command surface: `/nudge`.
- `memory_backup` — Hourly atomic snapshots of `data/memory/memory.db` with
  24h/7d/4w retention under `data/memory/backups/`. Closes the memory.db SPOF.
  Kill switch: `data/config/memory_backup.json` (`interval_hours: 1`). Restore
  drill runbook: `docs/wiki/operations/memory-restore-drill.md`.
- `liquidation_monitor` — tiered cushion alerts on every open position
  (audit F6). Alert-only; the ruin floor is still exchange_protection's
  mandatory stops. Registered all tiers.
- `brent_rollover_monitor` — T-7/T-3/T-1 alerts before each Brent contract roll
  (catalyst C7). Registered all tiers.
- `protection_audit` — read-only verifier that every open position has a sane
  exchange-side SL (catalyst C1').
- `funding_tracker` — cumulative funding cost tracker (catalyst C2).

## Gotchas

- Single-instance: pacman kill pattern (SIGTERM → sleep → SIGKILL)
- Risk gate states: OPEN / COOLDOWN / CLOSED — see risk-manager.md
- HWM auto-resets when flat (no positions) to prevent phantom drawdowns
- total_equity = perps (native + xyz) + spot USDC
