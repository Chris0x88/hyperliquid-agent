# Software Architecture Assessment — 2026-04-11

> Self-assessment of the HyperLiquid Bot codebase. Mechanically derived from
> file scans, import analysis, and structural audits. Not aspirational — this
> is what exists today.

---

## Executive Summary

The daemon iterator system is **excellent** — Protocol-based, zero direct coupling,
Hummingbot TimeIterator pattern, clean TickContext hub. The problem areas are
**above and below** the daemon: the Telegram/AI layer is monolithic (5,100-line
god file), configuration is fragmented (396 params across 25 files with no
central loader), and knowledge is duplicated across 5+ systems with no single
source of truth.

### Scorecard

| Area | Grade | Notes |
|------|-------|-------|
| Daemon iterator architecture | A | Protocol-based, zero coupling, circuit breakers |
| TickContext state management | A- | 23 fields, clear input/output separation |
| Oil Bot-Pattern sub-systems | B+ | Complex but well-segregated, file-coupled by design |
| Tier system | A | Clean tiers.py, deterministic iterator sets |
| AI agent runtime | B+ | Clean architecture, vendor-agnostic, streaming |
| Telegram bot | D | 5,104-line god file, 53 handlers + 40 infra functions |
| Configuration management | D+ | 396 params, 25 files, 148 independent loaders |
| Knowledge management | C- | 5 systems, heavy duplication, no single truth |
| Test coverage | C | 196 test files but untested coverage unknown |
| AI context navigability | C | 10-20 files to understand any feature end-to-end |

---

## 1. What Works Well (Don't Touch)

### 1.1 Daemon Iterator System

**Pattern**: Hummingbot-style TimeIterator with Protocol duck-typing.

```python
class Iterator(Protocol):
    name: str
    def tick(self, ctx: TickContext) -> None: ...
    def on_start(self, ctx: TickContext) -> None: ...
    def on_stop(self) -> None: ...
```

- 40/40 iterators follow identical interface — zero deviations
- All communication via TickContext hub — no direct iterator-to-iterator calls
- Oil Bot-Pattern sub-systems use file-based coupling (JSONL/JSON) — crash-safe, independently testable
- OrderIntent lifecycle fully tracked: PENDING_APPROVAL → SUBMITTED → ACCEPTED → FILLED/REJECTED/CANCELLED/EXPIRED

**Verdict**: This is the strongest part of the codebase. Protect it.

### 1.2 TickContext Hub

23 fields, all actively used by 2+ iterators:
- `ctx.alerts` (65 uses) — broadcast channel
- `ctx.prices` (38), `ctx.positions` (37) — exchange state
- `ctx.thesis_states` (18) — AI conviction
- `ctx.order_queue` (12) — execution pipeline

Clear separation: `connector` populates inputs, `execution_engine`/`exchange_protection` produce outputs.

### 1.3 Error Handling

Per-iterator circuit breaker + HealthWindow error budget (15-min sliding window, 10 errors max). Auto-downgrade tier on exhaustion. Connector failure skips entire tick.

### 1.4 Agent Runtime

`agent_runtime.py` (563 lines) is clean: vendor-agnostic, streaming SSE, parallel tool execution, accordion context compaction. No API keys baked in. Ported from Claude Code patterns.

---

## 2. Critical Problems

### 2.1 telegram_bot.py — The God File

**5,104 lines. 53 command handlers. 40 infrastructure functions. 9 distinct responsibilities.**

This single file handles:
1. Telegram API operations (tg_send, tg_get_updates)
2. Message routing (HANDLERS dict, 168 entries)
3. Command execution (all 53 cmd_* functions)
4. Interactive menu system (inline buttons, callbacks)
5. HyperLiquid API queries (prices, positions, orders)
6. Write command approval flow (pending actions)
7. Configuration management (watchlist, command menu)
8. Error handling and diagnostics
9. Main polling loop

**Impact on AI**: An AI agent trying to add a new command must understand the
entire 5,100-line file to find the right insertion points across 5 different
surfaces (HANDLERS, _set_telegram_commands, cmd_help, cmd_guide, and the
handler function itself). The CLAUDE.md checklist helps but doesn't fix the
structural problem.

**Proposed split** (no rewrite, just mechanical extraction):

| New File | Extracted From | Lines |
|----------|---------------|-------|
| `cli/telegram_api.py` | tg_send, tg_get_updates, tg_send_buttons, tg_remove_buttons, tg_answer_callback | ~200 |
| `cli/telegram_menu.py` | _build_main_menu, _handle_menu_callback, all mn: callback routing | ~400 |
| `cli/telegram_hl.py` | _hl_post, _get_all_positions, _get_all_orders, _get_account_values, _get_market_oi | ~200 |
| `cli/telegram_approval.py` | _handle_tool_approval, _lock_approval_message, pending action flow | ~200 |

Leaves telegram_bot.py with: command handlers + routing + main loop (~4,100 lines, still large but each handler is self-contained).

### 2.2 Configuration Sprawl

**396 configurable parameters across 25 files. 148 files load config independently.**

There is no central ConfigManager. Each iterator opens its own JSON file:
```python
with open("data/config/oil_botpattern.json") as f:
    config = json.load(f)
```

**Problems**:
- No validation — a typo in a config key silently does nothing
- No hot reload — must restart daemon for changes
- No schema documentation — you must read the code to know what keys exist
- Config files can conflict (e.g., oil_botpattern.json has `instruments` list;
  watchlist.json has its own market list — which is canonical?)
- Web dashboard config editor has no schema either — raw JSON editing

**Proposed improvement** (incremental, not a rewrite):
1. Create `common/config_schema.py` with Pydantic models for each config file
2. Single `load_config(name) -> TypedConfig` function that validates on load
3. Emit warnings for unknown keys
4. Document all parameters in one place (the schema IS the docs)

### 2.3 Knowledge Fragmentation

**5 separate knowledge systems, no single source of truth:**

| System | Files | Lines | Purpose |
|--------|-------|-------|---------|
| docs/wiki/ | 60 | 15,509 | Architecture, components, operations |
| docs/plans/ | 31 | 13,788 | Feature specs, implementation plans |
| CLAUDE.md files | 6 | ~300 | AI routing hints per directory |
| Memory files | 45 | ~2,000 | User preferences, feedback |
| Starlight docs site | 22 | ~4,000 | User-facing documentation |

**Duplication measured**:
- "BRENTOIL" documented in 19+ wiki files + 6 memory files
- "session token" rule in 11 docs + 3 memory files
- Thesis/conviction patterns spread across 109 files
- Tier iterator lists in: tiers.py (canonical), wiki/operations/tiers.md, docs site architecture/tiers.md, daemon CLAUDE.md

**The problem isn't the volume — it's that there's no hierarchy.**
When the codebase changes, which files need updating? There's no answer today.
The wiki says one thing, the docs site says another, the CLAUDE.md says a third.

**Proposed knowledge hierarchy** (single source of truth per concern):

| Concern | Source of Truth | Derived From |
|---------|----------------|--------------|
| Iterator lists | `cli/daemon/tiers.py` | Everything else reads this |
| Config parameters | Pydantic schemas (proposed) | Docs generated from schemas |
| Market definitions | `data/config/markets.yaml` | MarketRegistry in common/markets.py |
| Trading rules | Root `CLAUDE.md` | Wiki + docs site mirror |
| Command reference | `HANDLERS` dict in telegram_bot.py | Docs site generated from dict |
| Architecture decisions | `docs/wiki/decisions/` (14 ADRs) | Docs site summarizes |

---

## 3. Separation of Concerns — What's Swappable

### Current Boundaries (Clean)

```
┌─────────────────────────────────────────┐
│  Interfaces: Telegram Bot, Web Dashboard │  ← Swappable
├─────────────────────────────────────────┤
│  Intelligence: AI Agent, Conviction Eng  │  ← Swappable (vendor, model)
├─────────────────────────────────────────┤
│  Daemon: Clock + 42 Iterators            │  ← Core, stable
├─────────────────────────────────────────┤
│  Shared State: Filesystem (JSON/SQLite)  │  ← Swappable (DB later)
├─────────────────────────────────────────┤
│  Exchange: HyperLiquid API via adapter   │  ← Swappable (other DEX)
└─────────────────────────────────────────┘
```

**Already swappable**:
- AI vendor: Anthropic ↔ OpenRouter ↔ Claude CLI (fallback chain exists)
- Exchange adapter: `cli/hl_adapter.py` wraps all exchange calls
- Data layer: `web/api/readers/` has abstract interfaces (file → DB swap designed in)
- Key management: 5 pluggable backends in `common/credentials.py`

**Tightly coupled (hard to swap)**:
- Telegram bot ↔ command handlers (handlers reference tg_send directly)
- Iterators ↔ file paths (each iterator hardcodes its data/config/ path)
- telegram_agent.py ↔ Anthropic API specifics (session token headers, beta flags)

### Recommended Decoupling (if/when needed)

1. **Renderer ABC** already exists (`common/renderer.py`) — TelegramRenderer, BufferRenderer.
   More commands should use it (only 5 do today via RENDERER_COMMANDS).
2. **Config paths** should come from a registry, not be hardcoded in each iterator.
3. **Alert model** should be unified — today `ctx.alerts.append(Alert(...))` is clean
   inside the daemon, but Telegram commands use raw `tg_send()` with no structure.

---

## 4. AI Navigability — Making the Codebase AI-Friendly

### Current State

To understand any feature end-to-end, an AI needs 10-20 files:
- **Thesis → order**: 10 files (context.py, clock.py, connector.py, thesis_engine.py, market_structure.py, execution_engine.py, exchange_protection.py, rebalancer.py, guard.py, tiers.py)
- **Oil Bot-Pattern**: 20 files (10 iterators + 7 modules + 3 specs)
- **Add a Telegram command**: 5 files minimum (telegram_bot.py is 5,100 lines, plus help, guide, menu, tests)

### Recommended Improvements

1. **CLAUDE.md files should be learning paths, not inventories.**
   Instead of listing files, show: "To understand X, read files A→B→C in this order."
   The daemon CLAUDE.md (149 lines) is already good at this. Others are too sparse.

2. **Create `docs/wiki/learning-paths/` directory** with focused guides:
   - `thesis-to-order.md` — 10-file reading order
   - `adding-a-command.md` — exact checklist with file:line references
   - `oil-botpattern.md` — sub-system walkthrough

3. **Shrink the god files.** telegram_bot.py at 5,100 lines is the biggest barrier.
   After the proposed split, the remaining file is still 4,100 lines but each
   function is self-contained and greppable.

4. **Type the config layer.** Today an AI must read implementation code to know
   what config keys exist. Pydantic schemas would be self-documenting.

---

## 5. Complexity Management — The Beast Problem

### The Numbers

- 42 daemon iterators
- 53 Telegram command handlers
- 31 agent tools
- 396 config parameters
- 25 config files
- 12 kill switches
- 3 tiers
- 6 Oil Bot-Pattern sub-systems (with 4 self-tune layers)

### What's Actually Used in Production

Today the system runs in **WATCH tier** with most kill switches OFF:
- ~37 iterators active (but most do nothing because their kill switches are OFF)
- Core active set: account_collector, connector, market_structure, thesis_engine, protection_audit, liquidation_monitor, funding_tracker, brent_rollover_monitor, telegram
- Everything else is either read-only intelligence or disabled

### Recommended Simplification

1. **Config consolidation**: The 12 kill switches could be a single
   `data/config/feature_flags.json` with one key per feature. Today they're
   scattered across 12 separate config files, each with an `enabled` field.

2. **Iterator grouping**: Instead of 42 flat iterators, group into subsystems:
   - **Core** (always on): account_collector, connector, market_structure, thesis_engine, telegram
   - **Protection** (WATCH+): protection_audit, liquidation_monitor, funding_tracker, exchange_protection
   - **Intelligence** (WATCH+): radar, pulse, news_ingest, supply_ledger, heatmap, bot_classifier
   - **Execution** (REBALANCE+): execution_engine, exchange_protection, guard, rebalancer
   - **Oil Strategy** (REBALANCE+, kill-switched): oil_botpattern + 4 self-tune
   - **Learning** (WATCH+): journal, lesson_author, entry_critic, autoresearch, memory_consolidation

   This is already implicit in the code — making it explicit in a
   `cli/daemon/subsystems.py` would help both humans and AI.

3. **Command categories in code**: The 53 commands in telegram_bot.py have no
   structural grouping. Adding `# === TRADING COMMANDS ===` section markers
   would help, but the real fix is moving more commands to `telegram_commands/`
   modules (13 already live there — the other 40 should follow).

---

## 6. Specific Recommendations (Prioritized)

### P0 — Do Now (High Impact, Low Risk)

1. **Split telegram_bot.py infra** into telegram_api.py, telegram_menu.py,
   telegram_hl.py, telegram_approval.py. Pure mechanical extraction, no
   behavior change. Reduces god file by ~1,000 lines.

2. **Add section markers** to telegram_bot.py for the remaining command
   handlers. Group by: Data, Trading, Intelligence, Strategy, System, Meta.

3. **Create `docs/wiki/learning-paths/`** with 3 focused guides for AI
   context loading.

### P1 — Next Sprint (Medium Impact)

4. **Pydantic config schemas** for the top 5 most-edited configs:
   oil_botpattern.json, markets.yaml, watchlist.json, risk_caps.json,
   escalation_config.json. Validates on load, self-documents.

5. **Move 10 more commands** from telegram_bot.py to telegram_commands/ modules.
   Candidates: cmd_news, cmd_catalysts, cmd_supply, cmd_disruptions,
   cmd_heatmap, cmd_botpatterns, cmd_oilbot, cmd_oilbotjournal, cmd_chart,
   cmd_signals.

6. **Consolidate kill switches** into single `data/config/feature_flags.json`.

### P2 — When Needed (Lower Priority)

7. **Config registry** — single `load_config()` function replacing 148
   independent loaders.

8. **Unified alert bus** — currently alerts go through ctx.alerts in daemon
   and raw tg_send in Telegram commands. Unify to a single pub/sub.

9. **Auto-generate command reference** from HANDLERS dict metadata instead of
   manually maintaining it in 3 places (cmd_help, cmd_guide, docs site).

---

## 7. What NOT To Do

Per the user's explicit direction and the system's novel architecture:

1. **Do NOT revert to agent frameworks** (LangChain, CrewAI, etc.). The
   embedded agent runtime is intentionally minimal and vendor-agnostic.

2. **Do NOT add MCP to the agent**. The agent uses Python function tools.
   MCP is for the OpenClaw ecosystem, not the embedded agent.

3. **Do NOT add external dependencies** (ngrok, Redis, Postgres). The
   file-based data layer is a feature, not a limitation. It enables
   crash safety and zero-dependency deployment.

4. **Do NOT gut modules**. Staged activation + cohesion is the path forward.
   The Oil Bot-Pattern sub-systems are complex but well-segregated.

5. **Do NOT over-engineer the config layer**. Pydantic schemas for validation
   are good. A full config-server architecture is not.

---

## Appendix: File Size Inventory

### Largest Python Files

| File | Lines | Role |
|------|-------|------|
| cli/telegram_bot.py | 5,104 | God file — needs splitting |
| cli/telegram_agent.py | 2,568 | AI adapter — acceptable size |
| cli/agent_tools.py | 1,914 | Tool definitions — acceptable |
| common/heartbeat.py | 1,700 | Monitoring — review for dead code |
| cli/daemon/iterators/oil_botpattern.py | 1,384 | Strategy engine — acceptable for complexity |
| modules/entry_critic.py | 1,111 | Trade grading — could be split |
| common/market_structure.py | 971 | Technicals — acceptable |
| cli/agent_runtime.py | 563 | Core runtime — lean, good |

### Iterator Sizes (Top 15)

| Iterator | Lines |
|----------|-------|
| oil_botpattern.py | 1,384 |
| autoresearch.py | 596 |
| lesson_author.py | 486 |
| protection_audit.py | 445 |
| catalyst_deleverage.py | 416 |
| journal.py | 393 |
| entry_critic.py | 364 |
| oil_botpattern_patternlib.py | 359 |
| bot_classifier.py | 336 |
| account_collector.py | 330 |
| memory_backup.py | 321 |
| execution_engine.py | 308 |
| oil_botpattern_reflect.py | 298 |
| oil_botpattern_shadow.py | 297 |
| All iterators total | 11,048 |

---

*Generated 2026-04-11 by Claude Opus via 4 parallel structural audits.*
