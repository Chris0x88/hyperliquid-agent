# System Architecture

The HyperLiquid Bot serves three roles: **copilot** (AI chat via Telegram), **research agent** (autonomous market analysis), and **risk manager** (stop enforcement, drawdown protection, position sizing).

## System Diagram

```mermaid
graph TB
    subgraph HUMAN["Chris + Claude Code"]
        CC["Claude Code (Opus)\nWrites thesis files"]
        TG["Telegram\nCommands + AI chat"]
    end

    subgraph DAEMON["Daemon (clock.py)"]
        TICK["Tick Engine ~120s"]
        THESIS_READ["ThesisEngine\nReads thesis files"]
        EXEC["ExecutionEngine\nConviction sizing"]
        RISK["RiskIterator\nProtection chain"]
    end

    subgraph BOT["Telegram Bot"]
        COMMANDS["Command handlers\nsee cmd_* in telegram_bot.py"]
        AGENT["AI Agent\nOpenRouter + tools"]
        MENU["Interactive menu\nmn: callback routing"]
    end

    subgraph EXCHANGE["HyperLiquid"]
        MAIN["Main account\nOil, Gold, Silver (xyz perps)"]
        VAULT["Vault\nBTC Power Law"]
    end

    VR["Vault Rebalancer\nlaunchd hourly"]
    HB["Heartbeat\nlaunchd 2min"]
    THESIS_F["data/thesis/*.json"]

    CC -->|writes| THESIS_F
    TG <--> COMMANDS
    TG <--> AGENT
    THESIS_F --> THESIS_READ
    THESIS_READ --> EXEC
    EXEC --> EXCHANGE
    RISK --> DAEMON
    BOT -->|via hl_proxy| EXCHANGE
    VR --> VAULT
    HB -->|monitors + SL enforcement| EXCHANGE
```

## Data Flow: Thesis to Execution

1. **Chris + Claude Code** analyze markets and write `ThesisState` files to `data/thesis/` with conviction scores (0.0-1.0), direction, TP/SL levels, and evidence.
2. **ThesisEngineIterator** reads thesis files every 60s into the daemon's `TickContext`. Stale theses (>72h) get conviction clamped to 50%.
3. **ExecutionEngine** maps conviction to position size via Druckenmiller bands, respecting authority delegation (agent/manual/off per asset).
4. **RiskManager** enforces hard limits: drawdown gates, circuit breakers, ruin prevention. Worst gate wins.
5. **Telegram Bot** provides a real-time dashboard and AI chat. WRITE actions (trades, SL/TP) require explicit approval via inline keyboard.

## Key Packages

| Package | Purpose |
|---------|---------|
| `common/` | Shared libraries: thesis, market_snapshot, context_harness, authority, watchlist, tools, renderer |
| `cli/` | Telegram bot, AI agent, agent tools, interactive menu, MCP server |
| `cli/daemon/` | Tick engine, iterators (see `iterators/` directory), tiers, state persistence |
| `modules/` | Candle cache, strategy modules |
| `parent/` | Exchange gateway (`hl_proxy.py`), risk manager, position tracker |
| `openclaw/` | Agent personality (AGENT.md, SOUL.md), auth profiles |
| `plugins/` | Power Law bot (vault rebalancer strategy) |
| `scripts/` | Standalone daemons (vault rebalancer) |

## What's Running vs Dormant

**Running in production:**
- Telegram bot (polling, commands, AI agent)
- Daemon in WATCH tier (monitoring, thesis reads, alerts -- not executing trades)
- Heartbeat (2-min launchd, stop enforcement)
- Vault rebalancer (hourly launchd)

**Built but dormant:**
- Daemon REBALANCE/OPPORTUNISTIC tiers (execution_engine, profit_lock, radar, pulse)
- Full autonomous trading loop (requires authority delegation to "agent" per asset)
