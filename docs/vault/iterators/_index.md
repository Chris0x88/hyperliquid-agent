---
kind: index
last_regenerated: 2026-04-09 14:08
count: 36
tags:
  - index
  - iterators
---

# Iterators Index

_36 iterators auto-generated from `cli/daemon/iterators/`. Last regenerated: 2026-04-09 14:08._

Iterators are the daemon's pluggable processors. Each one runs per tick (~120s cadence). See [[Tier-Ladder]] for which iterators activate in which tier, and [[Authority-Model]] for how per-asset delegation gates trade-touching iterators.

| Iterator | Class | Tiers | Kill Switch | Wired? |
|---|---|---|---|---|
| [[account_collector]] | `AccountCollectorIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[action_queue]] | `ActionQueueIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/action_queue.json` | ✅ |
| [[apex_advisor]] | `ApexAdvisorIterator` | `watch` | _none_ | ✅ |
| [[autoresearch]] | `AutoresearchIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[bot_classifier]] | `BotPatternIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/bot_classifier.json` | ✅ |
| [[brent_rollover_monitor]] | `BrentRolloverMonitorIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[catalyst_deleverage]] | `CatalystDeleverageIterator` | `rebalance`, `opportunistic` | _none_ | ✅ |
| [[connector]] | `ConnectorIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[entry_critic]] | `EntryCriticIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/entry_critic.json` | ✅ |
| [[exchange_protection]] | `ExchangeProtectionIterator` | `rebalance`, `opportunistic` | _none_ | ✅ |
| [[execution_engine]] | `ExecutionEngineIterator` | `rebalance`, `opportunistic` | _none_ | ✅ |
| [[funding_tracker]] | `FundingTrackerIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[guard]] | `GuardIterator` | `rebalance`, `opportunistic` | _none_ | ✅ |
| [[heatmap]] | `HeatmapIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/heatmap.json` | ✅ |
| [[journal]] | `JournalIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[lesson_author]] | `LessonAuthorIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/lesson_author.json` | ✅ |
| [[liquidation_monitor]] | `LiquidationMonitorIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[liquidity]] | `LiquidityIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[market_structure]] | `MarketStructureIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[memory_backup]] | `MemoryBackupIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/memory_backup.json` | ✅ |
| [[memory_consolidation]] | `MemoryConsolidationIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[news_ingest]] | `NewsIngestIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/news_ingest.json` | ✅ |
| [[oil_botpattern]] | `BotPatternStrategyIterator` | `rebalance`, `opportunistic` | `data/config/oil_botpattern.json` | ✅ |
| [[oil_botpattern_patternlib]] | `OilBotPatternPatternLibIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/oil_botpattern_patternlib.json` | ✅ |
| [[oil_botpattern_reflect]] | `OilBotPatternReflectIterator` | `rebalance`, `opportunistic` | `data/config/oil_botpattern_reflect.json` | ✅ |
| [[oil_botpattern_shadow]] | `OilBotPatternShadowIterator` | `rebalance`, `opportunistic` | `data/config/oil_botpattern_shadow.json` | ✅ |
| [[oil_botpattern_tune]] | `OilBotPatternTuneIterator` | `rebalance`, `opportunistic` | `data/config/oil_botpattern_tune.json` | ✅ |
| [[profit_lock]] | `ProfitLockIterator` | `rebalance`, `opportunistic` | _none_ | ✅ |
| [[protection_audit]] | `ProtectionAuditIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[pulse]] | `PulseIterator` | `watch`, `opportunistic` | _none_ | ✅ |
| [[radar]] | `RadarIterator` | `watch`, `opportunistic` | _none_ | ✅ |
| [[rebalancer]] | `RebalancerIterator` | `rebalance`, `opportunistic` | _none_ | ✅ |
| [[risk]] | `RiskIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[supply_ledger]] | `SupplyLedgerIterator` | `watch`, `rebalance`, `opportunistic` | `data/config/supply_ledger.json` | ✅ |
| [[telegram]] | `TelegramIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
| [[thesis_engine]] | `ThesisEngineIterator` | `watch`, `rebalance`, `opportunistic` | _none_ | ✅ |
