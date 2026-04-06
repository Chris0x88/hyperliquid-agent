<p align="center">
  <img src="docs/banner2.png" alt="HyperLiquid Agent" width="100%" />
</p>

<h1 align="center">HyperLiquid Agent</h1>

<h3 align="center">Your AI trading co-pilot for Hyperliquid</h3>

<p align="center">
  <strong>An AI that defends your account while you sleep.</strong><br/>
  Open source. No fees. No telemetry. Your keys, your rules.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License" />
  <img src="https://img.shields.io/badge/AI-Claude_Opus_4.6-ff6b35" alt="Claude" />
  <img src="https://img.shields.io/badge/Telegram-bot-26A5E4?logo=telegram&logoColor=white" alt="Telegram" />
  <img src="https://img.shields.io/badge/HyperLiquid-perps_+_xyz-00D4AA" alt="HyperLiquid" />
</p>

---

## Why This Exists

Most trading bots are dumb scripts that blow up your account on the first weekend stop hunt.

This is something different: **a 24/7 AI risk manager that actually thinks**. You bring the thesis. It brings the discipline — automatic stops, leverage management, profit locking, and an embedded Claude agent that can analyze markets, execute trades, and improve its own code over time.

It's the bot you'd build for yourself if you had infinite weekends. Now you don't have to.

---

## What You Get

🧠 **Embedded AI Agent** — Claude Opus/Sonnet/Haiku running inside the bot. Reads your codebase, executes tools, manages positions, learns from each trade. Not an API-glued chatbot — a real agent runtime ported from Claude Code with parallel tool calls, streaming, context compaction, and persistent memory.

📱 **Telegram Dashboard** — Instant portfolio, charts, prices, orders, P&L, conviction state, funding rates. Fixed Python commands hit the HyperLiquid API directly. Zero AI credits per command. Free-text messages route to the AI agent.

⚡ **Tick-Based Daemon** — Iterators run on a clock: account state, risk gates, exchange protection (mandatory SL/TP), guard trailing stops, conviction-driven sizing, auto-research, profit lock, journal, REFLECT loop.

🛡️ **Mandatory Stop & Take-Profit** — Every position MUST have both SL and TP on the exchange itself. No exceptions. No "I'll add it later." The daemon enforces this every tick.

📊 **Conviction Engine** — Position sizing scales with thesis strength. Stale thesis files auto-clamp leverage. Kill switch built in.

🔬 **Research Loop** — Trade journal, REFLECT meta-evaluation, dream consolidation, strategy version history. The agent reviews its own trades and proposes improvements.

🔐 **Hardened Key Management** — Open Wallet Standard vault (AES-256-GCM) + macOS Keychain dual-write. API wallets only — the bot literally cannot withdraw your funds.

---

## 5-Minute Setup

You need: Python 3.13, a HyperLiquid account, and a Telegram bot token.

### 1. Clone and Install

```bash
git clone https://github.com/Chris0x88/hyperliquid-agent.git
cd hyperliquid-agent/agent-cli
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. Create an API Wallet (Critical)

> **Never give this tool your main private key.** Use an API wallet.

HyperLiquid API wallets can trade but **cannot withdraw funds**. If your key leaks, attackers can't steal your money — they can only place trades, and you can revoke the key instantly.

1. Log in at [app.hyperliquid.xyz](https://app.hyperliquid.xyz/)
2. **Portfolio → API Wallets → Generate**
3. Name it (e.g., `agent-bot`) and copy the private key
4. Import into the encrypted keystore:

```bash
python -m cli.main keys import
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env — add your Telegram bot token, chat ID, and (optional) OpenRouter key
```

Get a Telegram bot from [@BotFather](https://t.me/BotFather). Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot).

### 4. Start in Watch Mode

```bash
# Monitors only — no trading. Always start here.
python -m cli.main daemon start --tier watch
```

### 5. Launch the Telegram Bot

```bash
python -m cli.telegram_bot
```

Send `/menu` to your bot. You're live.

### 6. Optional: Persistent Daemons (macOS)

```bash
cp plists/com.hyperliquid.telegram.plist.example ~/Library/LaunchAgents/com.hyperliquid.telegram.plist
# Edit the plist — replace $AGENT_DIR with your actual path
launchctl load ~/Library/LaunchAgents/com.hyperliquid.telegram.plist
```

Same pattern for the daemon and heartbeat plists.

---

## How It Works

### The Three Layers

| Layer | What It Does | Where |
|-------|-------------|-------|
| **Daemon** | Tick-based loop. Iterators run in dependency order. Enforces SL/TP, manages risk, executes strategies. | `cli/daemon/iterators/` |
| **Telegram Bot** | Command interface + AI agent host. Routes free text to the embedded agent. | `cli/telegram_bot.py` |
| **AI Agent** | Embedded Claude runtime with parallel tools, streaming, memory, codebase access, self-improvement. | `cli/agent_runtime.py` |

### Daemon Tick Pipeline

```
Every tick (default 60s):
  account_collector  → fetch balance, positions, equity
  exchange_protection → ensure every position has SL+TP on exchange
  guard               → trailing stops, two-phase profit protection
  risk                → drawdown gates, circuit breakers
  conviction          → thesis-driven leverage decisions
  rebalancer          → run strategies, place orders
  profit_lock         → sweep 25% of realized profits
  autoresearch        → scan for opportunities
  journal             → log tick snapshot
  telegram            → push alerts
```

See `cli/daemon/iterators/` for all iterators. The full list lives in code, not in this README.

### Three Tiers

| Tier | Behavior | Start Here? |
|------|----------|-------------|
| **`watch`** | Monitor only. No trading. Sends alerts. | ✅ Yes |
| **`rebalance`** | Auto-rebalances + guards positions with trailing stops. | When you trust it |
| **`opportunistic`** | All above + scans for opportunities via autoresearch. | Advanced |

### Liquidity-Aware Risk

The daemon detects time-of-day regime and adjusts automatically:

| Regime | When | Size Multiplier | Stop Width |
|--------|------|----------------|------------|
| Normal | Weekday, US/EU hours | 1.0x | 1.0x |
| Low | After-hours (22:00-06:00 UTC) | 0.6x | 1.3x |
| Weekend | Sat/Sun | 0.4x | 1.5x |
| Dangerous | Weekend + after-hours | 0.25x | 2.0x |

Low-liquidity stop hunts wipe retail. The daemon refuses to play.

### Conviction Engine

Position size = base × conviction multiplier. Thesis files in `data/thesis/` define current conviction per market. Stale thesis → auto-clamp leverage. Kill switch in `data/config/` disables the whole system.

The AI agent updates thesis files based on research and market events. Humans approve. Daemon executes.

---

## Supported Markets

The agent trades native Hyperliquid perps **and** trade.xyz builder-deployed perps:

| Market Type | Examples | Coin Format |
|-------------|----------|-------------|
| Native perps | BTC, ETH, SOL | `BTC`, `ETH` |
| trade.xyz perps | BRENTOIL, GOLD, SILVER, NATGAS, SP500, NVDA | `xyz:BRENTOIL`, `xyz:GOLD` |

**Approved tokens (default config):** BTC, BRENTOIL, GOLD, SILVER. No memecoins, no junk. Edit `data/config/market_config.json` and `watchlist.json` to add more.

---

## The AI Agent

Free-text messages to your Telegram bot route to an embedded Claude agent with:

- **20+ tools** — account state, market analysis, prices, funding, orders, thesis, daemon health, codebase read/search/edit, web search, memory read/write, run bash
- **Approval flow** — READ tools auto-execute, WRITE tools (trades, edits, bash) require Telegram inline-button approval
- **Persistent memory** — `data/agent_memory/MEMORY.md` survives across sessions
- **Codebase access** — agent can read, search, and (with approval) edit its own source code
- **Triple-mode tool parsing** — native `tool_calls` (Anthropic), regex `[TOOL: ...]`, and AST-parsed Python blocks (for free models)
- **Context compaction** — long conversations auto-compact like Claude Code
- **Dream consolidation** — periodic memory consolidation between sessions

Configure model via `/models` in Telegram. Defaults to Anthropic direct (session token from your Claude subscription) with OpenRouter fallback.

---

## Featured Strategy: Bitcoin Power Law

The flagship hands-off strategy. BTC follows a power-law corridor over long timeframes:

- Calculate floor and ceiling from the model
- Near floor → increase allocation (accumulate)
- Near ceiling → decrease allocation (take profit)
- Rebalances on threshold deviation

**Live vault (you can follow it):** [HWM Opportunistic MOE on Hyperliquid](https://app.hyperliquid.xyz/vaults/0x9da9a9aef5a968277b5ea66c6a0df7add49d98da)

```bash
python scripts/run_vault_rebalancer.py
```

---

## What You Should Know

### This is experimental software

We're trading real money with it. The codebase evolves weekly. Use at your own risk. **Always start on `--tier watch`. Graduate slowly.**

### Security

- ✅ API wallets only — bot cannot withdraw
- ✅ Keys encrypted (OWS AES-256-GCM + macOS Keychain dual-write)
- ✅ Telegram tokens in env vars or Keychain, never config files
- ✅ Pre-commit hooks scan for secrets
- ⚠️ If someone gets root on your machine, they can reach your Keychain. Server deployments should consider HSMs.

### The AI agent makes mistakes

- It can be fooled by spoofed market data (especially in wartime)
- It can over-commit to a thesis
- The mandatory SL/TP and profit lock are your safety nets — they enforce discipline the agent (and you) can't always maintain
- Always keep a mental cap on total account exposure

### trade.xyz markets are different

- BRENTOIL, GOLD, etc. are **builder-deployed perps** — isolated margin only (no cross)
- The SDK loads them via `dex='xyz'` — coin names come back prefixed (`xyz:BRENTOIL`)
- Liquidity is thinner than native perps. Spreads wider. Stop hunts more common.
- Contract specs (max leverage, tick size) differ from what you'd expect

---

## Telegram Commands

Quick reference — full list via `/commands` or `/help`:

| Command | What It Does |
|---------|-------------|
| `/menu` | Interactive button menu |
| `/status` | Portfolio snapshot — equity, positions, P&L |
| `/position` | Detailed risk per position |
| `/price <coin>` | Current price |
| `/chart <coin> <hours>` | PNG chart |
| `/orders` | Open orders |
| `/pnl` | P&L summary |
| `/watchlist` | Tracked markets |
| `/signals` | Current trade signals |
| `/health` | App health check |
| `/diag` | Error diagnostics |
| `/feedback <text>` | Submit feedback |
| `/bug <text>` | Report a bug |
| `/restart` | Restart daemon |
| *(free text)* | Routed to AI agent |

---

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -x -q
```

1734+ tests. Run before any commit.

### Architecture Docs

- `docs/wiki/architecture/current.md` — live system architecture
- `docs/wiki/components/` — per-component deep dives (daemon, telegram-bot, ai-agent, conviction-engine, risk-manager, vault-rebalancer)
- `docs/wiki/decisions/` — ADRs (architectural decision records)
- `docs/wiki/MAINTAINING.md` — how the doc system stays honest

### Contributing

PRs welcome. If you build something interesting, open an issue first so we can talk.

---

## Heritage

The strategy engine framework was originally forked from a third party (see [ATTRIBUTION.md](ATTRIBUTION.md)). Everything since — daemon, conviction engine, embedded AI agent runtime, Bitcoin Power Law, Telegram bot, mandatory SL/TP enforcement, profit locking, liquidity-aware risk, trade.xyz support, research loop, dream consolidation — was built independently.

No builder fees. No telemetry. No external party calls except market data (Hyperliquid, Binance, CoinGecko).

---

<p align="center">
  <sub>MIT License · Built by humans and Claude · Not financial advice</sub>
</p>
