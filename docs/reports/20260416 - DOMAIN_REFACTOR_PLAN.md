# Domain Refactor Plan

## Context

The codebase (571 files, ~145k LOC) works but is opaque. The directory structure doesn't match how humans or agents think about the system. When Chris says "go work on the oil strategy," an agent has to search 5 directories. Every session burns context just orienting. The fix: restructure into domain packages that match mental models, so "go work on X" maps to one directory.

## Target Structure

```
agent-cli/
├── exchange/           ← MERGED parent/ + execution/
├── engines/            ← FROM modules/ — shared building blocks, sub-packaged by function
│   ├── analysis/       #   radar, pulse, technicals, context_engine
│   ├── protection/     #   guard, trailing_stop, entry_critic, reconciliation
│   ├── learning/       #   reflect, journal, lesson, memory, lab, architect, feedback
│   └── data/           #   candle_cache, heatmap, supply_ledger, bot_classifier
├── daemon/             ← PROMOTED from cli/daemon/ to top-level
│   └── iterators/
├── trading/            ← Per-market systems + shared trading infra
│   ├── heartbeat.py    #   position management (1700 lines, from common/)
│   ├── conviction_engine.py  # sizing/bands (from common/)
│   ├── thesis/         #   challenger, updater (from modules/)
│   └── oil/            #   oil_botpattern system (from modules/)
│                       #   Future: btc/, gold/, sp500/ etc.
├── agent/              ← AI runtime, tools, context pipeline
│   └── prompts/        #   AGENT.md, SOUL.md (from agent/)
├── telegram/           ← TG-specific: api, menu, approval, handler
│   └── commands/       #   extracted command files
├── common/             ← SLIMMED: markets, calendar, config, credentials, memory, models,
│                       #   renderer.py (interface ABC), venue_adapter.py (exchange ABC)
├── cli/                ← SLIMMED: main.py, commands/, engine, adapter, config
├── strategies/         ← UNTOUCHED (existing MM/HFT algos)
├── sdk/                ← UNTOUCHED
├── web/                ← UNTOUCHED
├── data/               ← UNTOUCHED
├── docs/               ← UNTOUCHED
└── tests/              ← FLAT, just update imports
```

### Mental Model Test — "Go work on X"

| You say... | Agent reads... |
|------------|---------------|
| "Fix the oil strategy" | `trading/oil/CLAUDE.md` |
| "Thesis system is broken" | `trading/thesis/CLAUDE.md` |
| "Radar not scanning" | `engines/analysis/CLAUDE.md` |
| "Fix Telegram commands" | `telegram/CLAUDE.md` |
| "Agent is misbehaving" | `agent/CLAUDE.md` |
| "Daemon iterator issue" | `daemon/CLAUDE.md` |
| "Exchange API problem" | `exchange/CLAUDE.md` |
| "Add a gold trading system" | Create `trading/gold/` |
| "Position management bug" | `trading/` (heartbeat.py) |

## Key Architecture Decisions

1. **`engines/` uses sub-packages by function** — not 50 flat files. analysis/, protection/, learning/, data/ match how you think about what they do.

2. **`trading/` = per-market systems + shared trading infra.** Generic engines (radar, pulse, guard) live in `engines/`. Market-specific systems (oil_botpattern, future btc/, gold/) live in `trading/`. Shared trading infra (heartbeat, conviction_engine, thesis/) lives at `trading/` root. This scales: adding a new market = create a new subdir.

3. **`telegram/` is ONE interface, not THE interface.** The `Renderer` ABC stays in `common/renderer.py`. Generic tool functions stay in `agent/tool_functions.py`. `telegram_hl.py` (pure exchange data helpers) moves to `common/` or `exchange/`, NOT telegram/. Only TG-specific code (api, menu, approval, handler, inline keyboards) goes in `telegram/`. When a second interface arrives, it creates its own top-level dir and implements the same Renderer ABC.

4. **4 commands already use Renderer pattern** (status, price, orders, health). These are interface-agnostic. The remaining ~70 cmd_* functions still use `(token, chat_id)`. Migrating them is a separate task from this refactor — we move them as-is and note the tech debt.

## Key Facts Driving the Order

- Dependency graph is **acyclic**: nothing imports from telegram. Engines don't import from agent/telegram.
- Iterators NEVER import from each other — they communicate via TickContext.
- Iterator registration is hardcoded in `cli/commands/daemon.py` (41 explicit imports).
- All `__init__.py` files are empty — no existing re-exports to maintain.

## Migration Strategy (applies to ALL phases)

1. **Move files** to new location (`git mv`)
2. **Update imports** in moved files (internal references)
3. **Create re-export shim** at old path: `old/module.py` or `old/__init__.py` does `from new.module import *`
4. **Run tests** — should pass via shims
5. **Update all consumers** (production code + tests) to use new paths
6. **Delete shims** — run tests again
7. **Commit**

Re-export shims are deleted at the END of each phase. They do NOT accumulate across phases.

---

## Phase 1: Create `exchange/` (merge parent/ + execution/)

**Risk: LOW.** Both packages are small (14 files), clean, well-bounded.

### Files to Move

| From | To |
|------|----|
| `parent/hl_proxy.py` | `exchange/hl_proxy.py` |
| `parent/house_risk.py` | `exchange/house_risk.py` |
| `parent/position_tracker.py` | `exchange/position_tracker.py` |
| `parent/risk_manager.py` | `exchange/risk_manager.py` |
| `parent/sdk_patches.py` | `exchange/sdk_patches.py` |
| `parent/store.py` | `exchange/store.py` |
| `execution/order_book.py` | `exchange/order_book.py` |
| `execution/order_types.py` | `exchange/order_types.py` |
| `execution/parent_order.py` | `exchange/parent_order.py` |
| `execution/portfolio_risk.py` | `exchange/portfolio_risk.py` |
| `execution/routing.py` | `exchange/routing.py` |
| `execution/twap.py` | `exchange/twap.py` |

**Import updates:** ~61 occurrences across ~48 files
**New:** `exchange/__init__.py`, `exchange/CLAUDE.md`
**Delete after:** `parent/` and `execution/` directories

---

## Phase 2: Create `engines/` with sub-packages (extract from modules/)

**Risk: LOW-MEDIUM.** Engines are pure computation, zero I/O. Organized into 4 functional sub-packages.

### Sub-package: `engines/analysis/`
| From modules/ | To |
|---------------|----|
| `radar_engine.py` | `engines/analysis/radar_engine.py` |
| `radar_config.py` | `engines/analysis/radar_config.py` |
| `radar_state.py` | `engines/analysis/radar_state.py` |
| `radar_guard.py` | `engines/analysis/radar_guard.py` |
| `radar_technicals.py` | `engines/analysis/radar_technicals.py` |
| `pulse_engine.py` | `engines/analysis/pulse_engine.py` |
| `pulse_config.py` | `engines/analysis/pulse_config.py` |
| `pulse_state.py` | `engines/analysis/pulse_state.py` |
| `pulse_guard.py` | `engines/analysis/pulse_guard.py` |
| `context_engine.py` | `engines/analysis/context_engine.py` |
| `apex_engine.py` | `engines/analysis/apex_engine.py` |
| `apex_config.py` | `engines/analysis/apex_config.py` |
| `apex_state.py` | `engines/analysis/apex_state.py` |

### Sub-package: `engines/protection/`
| From modules/ | To |
|---------------|----|
| `guard_bridge.py` | `engines/protection/guard_bridge.py` |
| `guard_config.py` | `engines/protection/guard_config.py` |
| `guard_state.py` | `engines/protection/guard_state.py` |
| `strategy_guard.py` | `engines/protection/strategy_guard.py` |
| `trailing_stop.py` | `engines/protection/trailing_stop.py` |
| `entry_critic.py` | `engines/protection/entry_critic.py` |
| `reconciliation.py` | `engines/protection/reconciliation.py` |
| `judge_engine.py` | `engines/protection/judge_engine.py` |
| `judge_guard.py` | `engines/protection/judge_guard.py` |

### Sub-package: `engines/learning/`
| From modules/ | To |
|---------------|----|
| `reflect_engine.py` | `engines/learning/reflect_engine.py` |
| `reflect_adapter.py` | `engines/learning/reflect_adapter.py` |
| `reflect_convergence.py` | `engines/learning/reflect_convergence.py` |
| `reflect_reporter.py` | `engines/learning/reflect_reporter.py` |
| `journal_engine.py` | `engines/learning/journal_engine.py` |
| `journal_guard.py` | `engines/learning/journal_guard.py` |
| `lesson_engine.py` | `engines/learning/lesson_engine.py` |
| `memory_engine.py` | `engines/learning/memory_engine.py` |
| `memory_guard.py` | `engines/learning/memory_guard.py` |
| `lab_engine.py` | `engines/learning/lab_engine.py` |
| `architect_engine.py` | `engines/learning/architect_engine.py` |
| `feedback_store.py` | `engines/learning/feedback_store.py` |
| `backtest_engine.py` | `engines/learning/backtest_engine.py` |
| `backtest_reporter.py` | `engines/learning/backtest_reporter.py` |
| `action_queue.py` | `engines/learning/action_queue.py` |
| `news_engine.py` | `engines/learning/news_engine.py` |
| `obsidian_reader.py` | `engines/learning/obsidian_reader.py` |
| `obsidian_writer.py` | `engines/learning/obsidian_writer.py` |
| `archiver.py` | `engines/learning/archiver.py` |

### Sub-package: `engines/data/`
| From modules/ | To |
|---------------|----|
| `candle_cache.py` | `engines/data/candle_cache.py` |
| `data_fetcher.py` | `engines/data/data_fetcher.py` |
| `heatmap.py` | `engines/data/heatmap.py` |
| `bot_classifier.py` | `engines/data/bot_classifier.py` |
| `supply_ledger.py` | `engines/data/supply_ledger.py` |
| `rotation.py` | `engines/data/rotation.py` |
| `wallet_manager.py` | `engines/data/wallet_manager.py` |
| `smart_money/` | `engines/data/smart_money/` |
| `catalyst_bridge.py` | `engines/data/catalyst_bridge.py` |

**What stays in modules/ (until Phase 4):**
`oil_botpattern*.py` (7 files), `thesis_challenger.py`, `thesis_updater.py`

**Import updates:** ~120 occurrences across ~55 files
**New:** `engines/__init__.py`, `engines/analysis/__init__.py`, `engines/protection/__init__.py`, `engines/learning/__init__.py`, `engines/data/__init__.py`, `engines/CLAUDE.md`

---

## Phase 3: Promote `daemon/` to Top-Level

**Risk: MEDIUM.** Production daemon running on real money. Pure path rename (`cli.daemon.*` -> `daemon.*`).

### Files to Move

Entire `cli/daemon/` promotes to `agent-cli/daemon/`:
- `clock.py`, `config.py`, `context.py`, `roster.py`, `state.py`, `tiers.py`, `calendar_tags.py`
- `iterators/` (42 files — all move as-is)
- `CLAUDE.md`

### Critical Path
1. Update `cli/commands/daemon.py` FIRST — it has 41 hardcoded `from cli.daemon.iterators.*` imports
2. Update all 42 iterator files (each has `from cli.daemon.context import TickContext`)
3. Update `context.py` itself (imports `from parent.*` which is now `from exchange.*` after Phase 1)
4. Update ~35 test files
5. Verify daemon launchd plist startup path still works

**Import updates:** ~99 occurrences across ~77 files
**Update existing:** `daemon/CLAUDE.md` (fix paths)

---

## Phase 4: Create `trading/` (per-market systems + shared trading infra)

**Risk: MEDIUM.** heartbeat.py (1700 lines) is the trade execution brain, but its consumer count is low.

### Shared trading infrastructure (at `trading/` root)

| From | To |
|------|----|
| `common/heartbeat.py` | `trading/heartbeat.py` |
| `common/heartbeat_config.py` | `trading/heartbeat_config.py` |
| `common/heartbeat_state.py` | `trading/heartbeat_state.py` |
| `common/consolidation.py` | `trading/consolidation.py` |
| `common/conviction_engine.py` | `trading/conviction_engine.py` |

### Sub-package: `trading/thesis/`

| From | To |
|------|----|
| `modules/thesis_challenger.py` | `trading/thesis/challenger.py` |
| `modules/thesis_updater.py` | `trading/thesis/updater.py` |

### Sub-package: `trading/oil/`

| From | To |
|------|----|
| `modules/oil_botpattern.py` | `trading/oil/engine.py` |
| `modules/oil_botpattern_adaptive.py` | `trading/oil/adaptive.py` |
| `modules/oil_botpattern_paper.py` | `trading/oil/paper.py` |
| `modules/oil_botpattern_patternlib.py` | `trading/oil/patternlib.py` |
| `modules/oil_botpattern_reflect.py` | `trading/oil/reflect.py` |
| `modules/oil_botpattern_shadow.py` | `trading/oil/shadow.py` |
| `modules/oil_botpattern_tune.py` | `trading/oil/tune.py` |

**After this phase:** `modules/` is EMPTY — delete it.

**Note:** `common/event_watcher.py` imports `common.consolidation`. Update to `trading.consolidation`.

**Import updates:** ~50 occurrences across ~35 files
**New:** `trading/__init__.py`, `trading/thesis/__init__.py`, `trading/oil/__init__.py`, `trading/CLAUDE.md`

### Future market systems

Adding a new market = create a new subdir:
```
trading/
├── btc/         # Future BTC-specific system
├── gold/        # Future gold-specific system
└── sp500/       # Future SP500-specific system
```

Each market system can use any engine from `engines/` and the shared infra at `trading/` root.

---

## Phase 5: Create `agent/` Package

**Risk: LOW-MEDIUM.** Very few external consumers (~7 import sites).

### Files to Move

| From | To |
|------|----|
| `agent/AGENT.md` | `agent/prompts/AGENT.md` |
| `agent/SOUL.md` | `agent/prompts/SOUL.md` |
| `agent/reference/` | `agent/prompts/reference/` |
| `cli/agent_tools.py` | `agent/tools.py` |
| `cli/agent_runtime.py` | `agent/runtime.py` |
| `cli/trade_evaluator.py` | `agent/trade_evaluator.py` |
| `common/tools.py` | `agent/tool_functions.py` |
| `common/context_harness.py` | `agent/context_harness.py` |
| `common/tool_renderers.py` | `agent/tool_renderers.py` |
| `common/code_tool_parser.py` | `agent/code_tool_parser.py` |

**What stays in common/ (interface ABCs):**
- `common/renderer.py` — the Renderer ABC. Telegram implements it, future interfaces will too.
- `common/venue_adapter.py` — exchange abstraction ABC.

**Import updates:** ~7 occurrences across ~6 files
**New:** `agent/__init__.py`, `agent/CLAUDE.md`

---

## Phase 6: Create `telegram/` Package

**Risk: LOW-MEDIUM.** Most isolated cluster — nothing outside cli/ imports from it.

### Files to Move

| From | To |
|------|----|
| `cli/telegram_bot.py` | `telegram/bot.py` |
| `cli/telegram_agent.py` | `telegram/agent.py` |
| `cli/telegram_api.py` | `telegram/api.py` |
| `cli/telegram_menu.py` | `telegram/menu.py` |
| `cli/telegram_approval.py` | `telegram/approval.py` |
| `cli/telegram_handler.py` | `telegram/handler.py` |
| `cli/telegram_commands/` | `telegram/commands/` (13 files) |

### What does NOT go in telegram/

- `cli/telegram_hl.py` → `common/exchange_helpers.py` (pure exchange data helpers, interface-agnostic — used by commands that could work on any interface)

### Interface notes

- 4 commands already use `Renderer` ABC (status, price, orders, health) — these are portable
- ~70 commands still use `(token, chat_id)` — they move as-is, migration to Renderer is separate work
- When a second interface arrives, create another top-level dir (e.g. `discord/`, `web_chat/`) implementing the same `common/renderer.Renderer` ABC

### What Stays in cli/ After All Phases

```
cli/
├── main.py              # Typer CLI entry point
├── config.py            # TradingConfig
├── engine.py            # TradingEngine
├── hl_adapter.py        # DirectHLProxy
├── display.py           # Terminal display (ANSI)
├── order_manager.py     # Order management
├── strategy_registry.py # Strategy registry
├── multi_wallet_engine.py
├── keystore.py
├── risk_monitor.py
├── chart_engine.py
├── daily_report.py
├── research.py
├── mcp_server.py
├── x402_config.py
├── commands/            # 27 Typer subcommand files
└── api/                 # Status reader
```

~14 files + 27-file commands/ subdirectory. Pure CLI tooling.

**Import updates:** ~40 occurrences across ~20 files
**New:** `telegram/__init__.py`, `telegram/CLAUDE.md`

---

## Phase 7: Cleanup

1. Delete empty `modules/` directory
2. Delete all remaining re-export shims
3. Update root `CLAUDE.md` routing table
4. Write/update all per-package `CLAUDE.md` files with correct paths
5. Update `docs/wiki/` references pointing to old paths
6. Update learning paths in `docs/wiki/learning-paths/`
7. Final full test run
8. Commit: `refactor: domain restructure complete — cleanup shims and docs`

---

## Verification

After EACH phase:
```bash
cd agent-cli && .venv/bin/python -m pytest tests/ -x -q
```

After Phase 3 specifically (daemon move):
```bash
# Verify daemon can start
.venv/bin/python -m cli.main daemon start --tier watch --mainnet --tick 120
# Check it runs for a few ticks, then Ctrl-C
```

After all phases:
```bash
# Full test suite (must be 3161+ passed, 0 failed)
.venv/bin/python -m pytest tests/ -q
# Verify telegram bot starts
# Verify daemon starts
# Verify web dashboard loads
```

## Summary

| Phase | Package | Files | Import Updates | Risk |
|-------|---------|-------|----------------|------|
| 1 | `exchange/` | 14 | ~61 in ~48 files | LOW |
| 2 | `engines/` (4 sub-packages) | ~50 | ~120 in ~55 files | LOW-MED |
| 3 | `daemon/` | ~50 | ~99 in ~77 files | MEDIUM |
| 4 | `trading/` (oil/, thesis/) | 14 | ~50 in ~35 files | MEDIUM |
| 5 | `agent/` | 10 | ~7 in ~6 files | LOW-MED |
| 6 | `telegram/` | 21 | ~40 in ~20 files | LOW-MED |
| 7 | Cleanup | 0 | docs only | LOW |

**One phase per session. Tests green after every phase. Commit between each.**
