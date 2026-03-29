<p align="center">
  <img src="docs/banner2.png" alt="HyperLiquid Agent" width="100%" />
</p>

<h1 align="center">HyperLiquid Agent</h1>

<h3 align="center">Your AI trading co-pilot for Hyperliquid</h3>

<p align="center">
  Open source. No fees. No telemetry. Your keys, your rules.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License" />
  <img src="https://img.shields.io/badge/Claude_Code-compatible-ff6b35" alt="Claude Code" />
  <img src="https://img.shields.io/badge/Telegram-bot-26A5E4?logo=telegram&logoColor=white" alt="Telegram" />
  <img src="https://img.shields.io/badge/OpenClaw-compatible-FF4500" alt="OpenClaw" />
  <img src="https://img.shields.io/badge/HyperLiquid-trade.xyz-00D4AA" alt="HyperLiquid" />
</p>

---

## What Is This?

An open-source toolkit that lets you run an **AI trading agent** on [Hyperliquid](https://hyperliquid.xyz) — the onchain perpetual futures exchange. It combines a tick-based trading daemon with Claude Code integration, so your AI agent can monitor positions, execute trades, and improve its own codebase over time.

**What makes it different:** This isn't a black-box bot you deploy and pray. It's designed to work *with* you. You bring the thesis and market knowledge. The agent brings discipline, execution speed, and 24/7 monitoring. Three interfaces, each doing what it's best at:

- **Claude Code** (phone or desktop) — your AI trading brain. Deep analysis, code improvement, trade execution, strategy discussions
- **Telegram bot** — instant dashboard. Portfolio, charts, prices, orders. Fixed Python code, zero AI credits
- **OpenClaw** (optional) — AI conversation via Telegram DM for quick questions and market chat

The agent trades autonomously within the boundaries you set, and gets smarter through a recursive research loop.

**Currently trading:** Bitcoin Power Law rebalancing (vault), Brent Oil directional (main account). The system supports any Hyperliquid market including trade.xyz perps (oil, gold, equities, etc.).

---

## 5-Minute Setup

You need: Python 3.10+, a HyperLiquid account, and [Claude Code](https://claude.ai/code).

### Step 1: Clone and Install

```bash
git clone https://github.com/Chris0x88/hyperliquid-agent.git
cd hyperliquid-agent && pip install -e .
```

### Step 2: Create an API Wallet (Critical)

> **Never give this tool your main private key.** Use an API wallet instead.

HyperLiquid API wallets (agent wallets) can trade but **cannot withdraw funds**. If your key leaks, attackers can't steal your money — they can only make trades, and you can revoke the key instantly.

1. Log in at [app.hyperliquid.xyz](https://app.hyperliquid.xyz/)
2. Go to **Portfolio > API Wallets > Generate**
3. Name it (e.g., "agent-bot")
4. Copy the private key — you only see it once

```bash
# Import your API wallet key (encrypted storage)
hl keys import --backend ows
```

For a deeper explanation of API wallet security, see [docs/SECURITY.md](docs/SECURITY.md).

### Step 3: Start the Daemon

```bash
# Watch mode — monitors only, no trading (start here)
hl daemon start --tier watch

# When ready for real trading:
hl daemon start --tier rebalance --mainnet
```

### Step 4: Connect Telegram (Recommended)

Get instant trade alerts and send commands from your phone.

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Store the token securely (macOS):
   ```bash
   security add-generic-password -s hl-agent-telegram -a bot_token -w "YOUR_TOKEN" -U
   ```
3. Message your bot, then run:
   ```bash
   python3 -c "
   import requests
   token = 'YOUR_TOKEN'
   r = requests.get(f'https://api.telegram.org/bot{token}/getUpdates')
   chat_id = r.json()['result'][0]['message']['chat']['id']
   print(f'Chat ID: {chat_id}')
   "
   ```
4. Store the chat ID:
   ```bash
   security add-generic-password -s hl-agent-telegram -a chat_id -w "YOUR_CHAT_ID" -U
   ```

Now start the Telegram bot:

```bash
hl telegram start
```

Your bot responds to `/status`, `/chart oil 72`, `/watchlist`, `/price`, `/pnl`, `/orders`, `/powerlaw`. All instant, all free — fixed Python code hitting the HyperLiquid API directly. Zero AI credits.

### Step 5: Set Up Claude Code as Your AI Trader

This is the real power. Open [Claude Code](https://claude.ai/code) (phone, desktop, or web) and point it at this repo. Claude can:
- Make autonomous trading decisions
- Run on a schedule (hourly check-ins via scheduled tasks)
- Execute trades, manage positions, adjust leverage
- Improve the codebase as it learns from each trade
- Send you alerts via Telegram when something happens

Claude Code is the brain. Telegram is the dashboard. They're separate interfaces — Claude Code doesn't run through Telegram.

### Step 6: Add OpenClaw (Optional — AI Chat via Telegram)

If you want AI conversation in Telegram (not just fixed commands), set up [OpenClaw](https://github.com/openclaw/openclaw) with a separate bot. This gives you a Telegram DM where you can ask questions like "what's the oil thesis?" and get AI responses.

See [docs/openclaw-setup/](docs/openclaw-setup/) for the agent prompt and configuration.

**Note:** OpenClaw and the commands bot run as separate Telegram DMs, not in a group. Multi-bot groups don't work cleanly with Telegram's current architecture (see [docs/TELEGRAM_GROUP_SETUP.md](docs/TELEGRAM_GROUP_SETUP.md) for why).

---

## How It Works

### The Daemon

A tick-based loop (inspired by [Hummingbot's](https://hummingbot.org/) clock architecture) that runs registered iterators in dependency order:

```
Every tick (default 60s):
  Connector  → fetch prices, positions, balances
  Liquidity  → detect time-of-day regime (weekend/after-hours = danger)
  Risk       → check drawdown, circuit breakers, gate state
  Guard      → trailing stops, two-phase profit protection
  Rebalancer → run strategies, convert decisions to orders
  Profit Lock → sweep 25% of realized profits (capital protection)
  Journal    → log tick snapshot for analysis
  Telegram   → send alerts for trades, gate changes, P&L
```

### Three Tiers

| Tier | What It Does | Start Here? |
|------|-------------|-------------|
| **`watch`** | Monitors only. No trading. Sends alerts. | Yes |
| **`rebalance`** | Auto-rebalances + guards positions with trailing stops. | When you trust it |
| **`opportunistic`** | All above + scans for opportunities via Radar/Pulse. | Advanced |

### Liquidity-Aware Risk

The daemon knows when markets are thin and adjusts automatically:

| Regime | When | Size Multiplier | Stop Width |
|--------|------|----------------|------------|
| Normal | Weekday, US/EU hours | 1.0x | 1.0x |
| Low | After-hours (22:00-06:00 UTC) | 0.6x | 1.3x |
| Weekend | Saturday/Sunday | 0.4x | 1.5x |
| Dangerous | Weekend + after-hours | 0.25x | 2.0x |

This matters. Low-liquidity stop hunts are how retail traders get wiped. The daemon reduces exposure automatically.

### Profit Locking

The `ProfitLockIterator` sweeps 25% of realized profits by partially closing profitable positions. This protects your capital base — profits are "locked" even if the trade reverses.

---

## Supported Markets

The agent trades on both native Hyperliquid perps and **trade.xyz builder-deployed perps**:

| Market Type | Examples | Coin Format |
|-------------|----------|-------------|
| Native perps | BTC, ETH, SOL, etc. | `BTC`, `ETH` |
| trade.xyz perps | BRENTOIL, GOLD, NATGAS, SP500, NVDA, etc. | `xyz:BRENTOIL`, `xyz:GOLD` |

The SDK is configured to load all trade.xyz markets automatically. You can trade oil, gold, equities, and commodities alongside crypto.

---

## Featured Strategy: Bitcoin Power Law

The flagship strategy. Based on the Bitcoin Power Law model — BTC price follows a power-law corridor over long timeframes.

- Calculates "floor" and "ceiling" from the model
- Near the floor: increase leverage (accumulate)
- Near the ceiling: decrease leverage (take profit)
- Rebalances hourly by default

```bash
hl daemon add power_law_btc -i BTC-PERP -t 3600
hl daemon start --tier rebalance
```

**Follow via vault:** [HWM Opportunistic MOE on Hyperliquid](https://app.hyperliquid.xyz/vaults/0x9da9a9aef5a968277b5ea66c6a0df7add49d98da)

---

## The Research Loop (How the Agent Improves)

This is not a static bot. The agent learns from every trade:

```
data/research/
  trades/         # Every trade with thesis, outcome, lesson learned
  market_notes/   # Market analysis snapshots
  signals/        # Signal log for future backtesting
  learnings.md    # What worked, what didn't — updated after each trade
```

After each trade closes, the agent reviews: Was the thesis right? Was the entry timing good? Did position sizing protect us? The lesson feeds back into how it analyzes the next trade. Over time, the codebase evolves — the agent proposes improvements, you approve, and we push to GitHub.

---

## How It's Built (Honestly)

We frankensteined this together. Here's what came from where:

| Component | Origin | What We Did |
|-----------|--------|-------------|
| **Strategy engine + CLI** | Forked from [Nunchi's agent-cli](https://github.com/Nunchi-trade/agent-cli) | Stripped all fees, telemetry, external dependencies. Kept the strategy framework. |
| **Bitcoin Power Law** | Built from scratch | Index-fund-style BTC rebalancer. The one strategy we trust to run fully automated. |
| **Daemon layer** | Inspired by [Hummingbot](https://hummingbot.org/) | Tick-based iterator loop. 10 iterators. Simpler than Hummingbot — no Cython, no event bus. |
| **Key management** | [Open Wallet Standard](https://github.com/nicholasgasior/ows) + macOS Keychain | AES-256-GCM encrypted vault + Keychain dual-write. |
| **Telegram** | Built from scratch | Two-way: alerts out, commands in. Secrets in Keychain, not config files. |
| **Profit lock** | Built from scratch | Auto-sweeps 25% of profits. Capital protection on autopilot. |
| **Liquidity guard** | Built from scratch | Time-of-day regime detection. Reduces size on weekends/after-hours. |
| **Historical data** | Built from scratch | SQLite candle cache, HL API fetcher, backtest engine. |
| **MCP tools** | [Model Context Protocol](https://modelcontextprotocol.io) | 16+ tools for AI agent integration. |

---

## What You Should Know (Transparency)

### This is experimental software

We're trading real money with it. But it's new, the codebase is evolving, and we're learning as we go. Use it at your own risk. Start on testnet. Start with `--tier watch`. Graduate slowly.

### Security is a real concern

- **API wallets protect you** — the bot can never withdraw your funds
- **Keys are encrypted** — OWS vault (AES-256-GCM) + macOS Keychain
- **Telegram tokens are in Keychain** — not plaintext config files
- **But:** if someone gets root on your machine, they can access your Keychain. If you're running on a server, consider hardware security modules
- **We never commit secrets** — `data/` is gitignored, pre-commit hooks scan for key patterns

### The AI agent is powerful but imperfect

- Claude Code makes autonomous trading decisions. It can and will make mistakes
- Data manipulation is real in wartime markets — the agent can be fooled by spoofed data
- The agent improves over time but isn't infallible
- Always keep a mental stop on your total account exposure
- The profit lock mechanism is your safety net — it forces partial profit-taking automatically

### trade.xyz markets are different

- BRENTOIL, GOLD, etc. are **builder-deployed perps** — they require isolated margin (no cross)
- They're not in the native Hyperliquid universe — the SDK needs `perp_dexs=["", "xyz"]` to see them
- Liquidity is lower than native perps — spreads are wider, stop hunts are more common
- The contract specs (max leverage, tick size) may differ from what you expect

---

## Commands Reference

```bash
# Daemon
hl daemon start [--tier watch|rebalance|opportunistic] [--tick 60] [--mock] [--mainnet]
hl daemon stop | status | once
hl daemon tier [watch|rebalance|opportunistic]
hl daemon strategies | add | remove | pause | resume

# Direct strategy execution
hl run <strategy> -i <instrument> [--tick N] [--mock] [--mainnet]

# Monitoring
hl status [--watch]
hl account

# Data & Backtesting
hl data fetch | stats | export
hl backtest run -s <strategy> -c <coin> -d <days>

# Key management
hl keys import | list | migrate

# Scanning
hl radar once | run
hl pulse once | run

# Infrastructure
hl setup check
hl mcp serve
hl strategies [--all] [--advanced]
```

### Telegram Commands

Send these to your bot from your phone:

| Command | What It Does |
|---------|-------------|
| `/status` | Portfolio snapshot — positions, P&L, equity |
| `/price` | Current prices for watched instruments |
| `/help` | List available commands |
| *(free text)* | Forwarded to Claude for analysis/execution |

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

### What We're Working On

- Custom index vaults (self-rebalancing baskets — replacing index funds)
- Deeper Hummingbot integration (their connectors are battle-tested)
- More sophisticated entry timing using order flow analysis
- Better backtesting with trade.xyz historical data
- Multi-account orchestration (vault + main + sub-accounts)
- Mobile-first experience via Telegram + Claude Code

### Contributing

This is an independent project. PRs welcome. If you build something interesting, open an issue and let's talk.

---

## Heritage

Forked from [Nunchi's agent-cli](https://github.com/Nunchi-trade/agent-cli). Credit to their team for the strategy engine and CLI framework. We stripped fees and telemetry, then built on top: the daemon, Bitcoin Power Law, key management, trade.xyz support, Telegram integration, profit locking, liquidity-aware risk, and AI agent tooling.

---

<p align="center">
  <sub>MIT License &bull; Built by humans and Claude &bull; Not financial advice</sub>
</p>
