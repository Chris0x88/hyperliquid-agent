<p align="center">
  <img src="docs/banner2.png" alt="HyperLiquid Agent" width="100%" />
</p>

<h1 align="center">HyperLiquid Agent</h1>

<h3 align="center">Autonomous Trading Daemon for Hyperliquid</h3>

<p align="center">
  Open source. No fees. No telemetry. Your keys, your rules.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License" />
  <img src="https://img.shields.io/badge/OpenClaw-ready-ff6b35" alt="OpenClaw Ready" />
</p>

---

A monitoring and rebalancing daemon for [Hyperliquid](https://hyperliquid.xyz) perps. Start in watch-only mode, graduate to automated rebalancing when you're ready. Designed to work **alongside** your normal HyperLiquid account — not replace it.

**The idea:** Set up your account at [app.hyperliquid.xyz](https://app.hyperliquid.xyz/), create an API wallet for the bot, and let the daemon monitor and trade on your behalf. You stay in control. The bot uses a restricted API key that can trade but never withdraw.

---

## What This Is (And Isn't)

**This is** a focused trading daemon that:
- Monitors your positions, PnL, and risk in real time
- Rebalances based on deterministic strategies (Bitcoin Power Law is the flagship)
- Scans for opportunities and guards your positions with trailing stops
- Exposes everything via MCP tools so your AI agent can query and act

**This is not** a black box. Every decision the daemon makes is deterministic — no LLM in the loop. If you use an AI agent (OpenClaw, Claude Code), it acts like a human running CLI commands. The daemon runs the math; the agent runs the daemon.

---

## How It's Built

We frankensteined this together from several sources and made it work:

| Component | Origin | What We Did |
|-----------|--------|-------------|
| **Strategy engine + CLI** | Forked from [Nunchi's agent-cli](https://github.com/Nunchi-trade/agent-cli) | Stripped all fees, telemetry, and external dependencies. Kept the strategy framework and pure-logic modules. |
| **Bitcoin Power Law plugin** | Built from scratch | Index-fund-style BTC rebalancer based on the Power Law floor/ceiling model. The flagship strategy. |
| **Key management** | [Open Wallet Standard](https://github.com/OpenWalletStandard) + macOS Keychain | OWS vault (AES-256-GCM, Rust core) as primary backend, Keychain as fast fallback. Dual-write to both. |
| **Historical data system** | Built from scratch | SQLite candle cache, HL API fetcher with rate limiting, backtest engine, technical analysis. |
| **Oil strategies** | Built from scratch | Brent squeeze, liquidation sweep, war regime — experimental, thesis-driven. |
| **Daemon layer** | Inspired by [Hummingbot](https://hummingbot.org/) clock architecture | Tick-based iterator loop. Simpler than Hummingbot — no Cython, no event bus. |
| **Agent skills** | [Agent Skills](https://agentskills.io) standard | 6 skills for AI agent integration (onboard, radar, pulse, guard, reflect, apex). |
| **MCP tools** | [Model Context Protocol](https://modelcontextprotocol.io) | 16+ tools for AI agents to query data, run strategies, check status. |

See [ATTRIBUTION.md](ATTRIBUTION.md) for full credits.

---

## Security First: Use an API Wallet

> **Never give this tool your main HyperLiquid private key.**

HyperLiquid has a purpose-built system for bot trading called **API wallets** (agent wallets). You should always use one:

| | Main Key | API Wallet |
|-|----------|-----------|
| **Can trade** | Yes | Yes |
| **Can withdraw** | Yes | **No** |
| **Revocable** | No — it's your key forever | Yes — deregister instantly from web UI |
| **Nonce isolation** | Shared with web UI | Separate — no conflicts with manual trading |
| **If leaked** | Attacker drains everything | Attacker can only trade (no withdrawals) |

**How to create one:**
1. Log in at [app.hyperliquid.xyz](https://app.hyperliquid.xyz/)
2. Go to **Portfolio → API Wallets → Generate**
3. Name it (e.g., "agent-bot")
4. Copy the private key — **you'll only see it once**

This is the key you give to the agent. Your main key stays in your browser wallet, untouched.

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/Chris0x88/hyperliquid-agent.git
cd hyperliquid-agent && pip install -e .

# 2. Import your API wallet key (NOT your main key)
hl keys import --backend ows

# 3. Verify
hl account

# 4. Start the daemon in watch mode (no trading, just monitoring)
hl daemon start --tier watch

# 5. When ready, upgrade to rebalancing
hl daemon start --tier rebalance
```

**First time?** The daemon defaults to testnet. Add `--mainnet` when you're ready for real money.

---

## The Daemon

The daemon is a tick-based loop (inspired by Hummingbot's clock architecture) that runs registered iterators in dependency order. Each tier activates more capabilities:

### Tiers

| Tier | What It Does | Who It's For |
|------|-------------|--------------|
| **`watch`** | Monitors positions, PnL, risk levels. Alerts on thresholds. No trading. | Beginners. Start here. |
| **`rebalance`** | Monitors + auto-rebalances per your strategy + guards positions with trailing stops. | Intermediate. Set and forget. |
| **`opportunistic`** | All of the above + scans for opportunities via Radar/Pulse. Acts within strict capital/leverage limits. | Advanced. Full autonomous. |

```bash
hl daemon start --tier watch           # start monitoring
hl daemon tier rebalance               # upgrade at runtime
hl daemon status                       # check what's happening
hl daemon once                         # single tick (for cron/agents)
```

### Multi-Strategy Roster

The daemon can run multiple strategies simultaneously. Each strategy has its own instrument and tick interval.

```bash
hl daemon strategies                              # what's running?
hl daemon add power_law_btc -i BTC-PERP -t 3600  # hourly BTC rebalance
hl daemon add trend_follower -i ETH-PERP -t 60   # minutely ETH trend
hl daemon pause power_law_btc                     # pause without removing
hl daemon remove trend_follower                   # drop it
```

### Opportunistic Tier Limits

When running in `opportunistic` mode, all entries are strictly bounded:
- Capital limit per opportunity (default 5% of account)
- Leverage limit (default 3x)
- Position size limits (configurable)
- All signals are deterministic — no LLM decisions

---

## Featured Strategy: Bitcoin Power Law

The flagship strategy. Based on the Bitcoin Power Law model — the idea that BTC price follows a power-law corridor over long timeframes.

- Calculates a "floor" and "ceiling" from the model
- When BTC is near the floor: increase leverage (accumulate)
- When BTC is near the ceiling: decrease leverage (take profit)
- Rebalances hourly by default

```bash
hl daemon add power_law_btc -i BTC-PERP -t 3600
hl daemon start --tier rebalance
```

Or follow the same strategy via vault:
**[Copy Vault on Hyperliquid →](https://app.hyperliquid.xyz/vaults/0x9da9a9aef5a968277b5ea66c6a0df7add49d98da)**

---

## Historical Data & Analytics

Built-in historical data system with SQLite cache, HL API fetcher, and technical analysis.

```bash
# Fetch and cache candles
hl data fetch --coin BTC --interval 1h --days 90

# Run a backtest
hl backtest run -s power_law_btc -c BTC -d 90 --capital 10000

# Check what's cached
hl data stats

# Export to CSV
hl data export --coin BTC --interval 1h --output btc_candles.csv
```

**For AI agents** — all of this is exposed via MCP tools:
- `get_candles` — query cached OHLCV data (auto-fetches if not cached)
- `analyze` — technical analysis snapshot (EMA, RSI, trend, volume)
- `backtest` — run a strategy backtest, get metrics
- `fetch_data` — explicitly populate the cache
- `price_at` — point lookup at a timestamp

---

## Key Management

Multi-backend key storage with automatic fallback:

| Backend | Security | Platform | How |
|---------|----------|----------|-----|
| **OWS Vault** (primary) | AES-256-GCM, mlock'd memory, Rust core | All | `hl keys import --backend ows` |
| **macOS Keychain** (fallback) | System-level encryption | macOS | Auto-detected |
| **Encrypted Keystore** | geth-compatible scrypt KDF | All | `hl keys import --backend keystore` |

Keys are dual-written to OWS + Keychain (on macOS) for redundancy.

```bash
hl keys import              # import a key (prompts for backend)
hl keys list                # show all stored keys
hl keys migrate --from keystore --to ows --address 0x...
```

---

## More Strategies

22 strategies are included. Most are hidden by default to keep things simple.

```bash
hl strategies               # show featured (power_law_btc)
hl strategies --all         # show featured + standard (oil, momentum, arb)
hl strategies --advanced    # show everything (MM suite, LLM agent, etc.)
```

Every strategy works with `hl run <name>` for direct execution, or via the daemon roster for managed execution.

**Standard strategies** (oil thesis, momentum, arbitrage):
`brent_oil_squeeze`, `oil_war_regime`, `oil_liq_sweep`, `mean_reversion`, `trend_follower`, `funding_arb`

**Advanced strategies** (market making, institutional, LLM):
`engine_mm`, `avellaneda_mm`, `regime_mm`, `simple_mm`, `grid_mm`, `liquidation_mm`, `momentum_breakout`, `aggressive_taker`, `hedge_agent`, `rfq_agent`, `claude_agent`, `basis_arb`, `simplified_ensemble`, `funding_momentum`, `oi_divergence`

### Write Your Own

```python
from sdk.strategy_sdk.base import BaseStrategy
from common.models import MarketSnapshot, StrategyDecision

class MyStrategy(BaseStrategy):
    def on_tick(self, snapshot, context=None):
        # Your logic here
        return [StrategyDecision(action="place_order", ...)]
```

```bash
hl run my_module:MyStrategy -i ETH-PERP --tick 10
```

---

## AI Agent Integration

### OpenClaw / Claude Code

Pre-configured with `openclaw.json`, workspace files, 6 agent skills, and MCP tools. Point your agent at this repo and it can onboard itself.

```bash
hl mcp serve                # start MCP server (stdio)
hl mcp serve --transport sse  # SSE transport
```

### MCP Tools

| Category | Tools |
|----------|-------|
| **Data** | `get_candles`, `fetch_data`, `analyze`, `backtest`, `price_at`, `cache_stats` |
| **Trading** | `trade`, `run_strategy`, `apex_run` |
| **Monitoring** | `account`, `status`, `radar_run`, `reflect_run` |
| **System** | `strategies`, `setup_check`, `wallet_list`, `wallet_auto` |
| **Intelligence** | `agent_memory`, `trade_journal`, `judge_report` |

### Agent Skills

| Skill | Purpose |
|-------|---------|
| **Onboard** | Walk through setup from zero to first trade |
| **Radar** | Screen all HL perps for opportunities |
| **Pulse** | Detect sudden capital inflow |
| **Guard** | Trailing stop management |
| **REFLECT** | Performance review and parameter tuning |
| **APEX** | Full autonomous orchestration (legacy, use daemon instead) |

---

## Sub-Accounts (Advanced)

For separate budgets per strategy:
1. Create sub-account at [app.hyperliquid.xyz](https://app.hyperliquid.xyz/)
2. Transfer funds to the sub-account
3. Create a dedicated API wallet for the sub-account
4. Import: `hl keys import --backend ows`

Sub-account volume counts toward your master account fee tier. HyperLiquid allows 2 named API wallets per sub-account.

---

## Commands Reference

```bash
# Daemon (primary interface)
hl daemon start [--tier watch|rebalance|opportunistic] [--tick 60] [--mock] [--mainnet]
hl daemon stop | status | once
hl daemon tier [watch|rebalance|opportunistic]
hl daemon strategies | add | remove | pause | resume

# Direct strategy execution (power users)
hl run <strategy> -i <instrument> [--tick N] [--mock] [--mainnet]

# Monitoring
hl status [--watch]
hl account

# Data & Backtesting
hl data fetch | stats | export
hl backtest run -s <strategy> -c <coin> -d <days>

# Key management
hl keys import | list | migrate
hl wallet auto [--save-env]

# Scanning
hl radar once | run
hl pulse once | run
hl guard run -i <instrument>
hl reflect run [--since DATE]

# Infrastructure
hl setup check
hl mcp serve
hl strategies [--all] [--advanced]
hl markets
hl journal
```

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## Heritage

Forked from [Nunchi's agent-cli](https://github.com/Nunchi-trade/agent-cli) — credit to their team for the strategy engine and CLI framework. We stripped all fees, telemetry, and external dependencies, then built on top: the daemon layer, Bitcoin Power Law strategy, OWS key management, historical data system, oil research strategies, and expanded AI agent tooling.

This is an independent project taking things in its own direction.

See [ATTRIBUTION.md](ATTRIBUTION.md) for full credits.

---

<p align="center">
  <sub>MIT License &bull; Chris Imgraben</sub>
</p>
