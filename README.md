<h1 align="center">HyperLiquid Agent</h1>

<h3 align="center">Autonomous Trading Agent for Hyperliquid</h3>

<p align="center">
  Fully open source. No fees. No telemetry. No tricks.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/strategies-23-C9A84C" alt="Strategies" />
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License" />
  <img src="https://img.shields.io/badge/MCP-16%20tools-8A2BE2" alt="MCP" />
  <img src="https://img.shields.io/badge/OpenClaw-ready-ff6b35" alt="OpenClaw Ready" />
</p>

---

**Plug-and-play trading agent for [OpenClaw](https://agentskills.io).** Ship market-making, momentum, arbitrage, and LLM-powered strategies on [Hyperliquid](https://hyperliquid.xyz) perps. Full autonomous stack: Guard trailing stops, Radar opportunity screening, Pulse momentum detection, APEX orchestrator, REFLECT performance review.

**OpenClaw-native** — config files, skills, and MCP tools are all included. Point your agent at this repo and start trading. Also works as a standalone CLI or Claude Code skill.

**What makes this different:**
- **OpenClaw plug-and-play** — `openclaw.json`, 6 agent skills, 16 MCP tools, workspace files all pre-configured
- **No builder fees** — zero fee skimming on your trades, ever
- **No telemetry** — nothing phones home, no tracking, no analytics
- **Fully open source** — read every line, fork it, make it yours

### Copy My Bitcoin Rebalancer Vault

Follow the Bitcoin Power Law rebalancing strategy on Hyperliquid:

**[Copy Vault on Hyperliquid →](https://app.hyperliquid.xyz/vaults/0x9da9a9aef5a968277b5ea66c6a0df7add49d98da)**

Or run `power_law_btc` yourself with the built-in strategy.

---

## Quick Start — OpenClaw (Recommended)

Already have an OpenClaw agent? Just point it at this repo:

```bash
git clone https://github.com/Chris0x88/hyperliquid-agent.git ~/hyperliquid-agent
cd ~/hyperliquid-agent && bash scripts/bootstrap.sh
```

Everything is pre-configured: `openclaw.json`, workspace files (`AGENTS.md`, `SOUL.md`, `TOOLS.md`, `BOOTSTRAP.md`), 6 agent skills, and 16 MCP tools. Your agent can onboard itself — the Onboard skill walks it from zero to first trade.

## Quick Start — CLI

```bash
git clone https://github.com/Chris0x88/hyperliquid-agent.git && cd hyperliquid-agent
bash scripts/bootstrap.sh        # Creates venv, installs, validates
```

### Agent-Friendly (Zero Prompts)

```bash
hl wallet auto --save-env        # Create wallet + save creds (no prompts)
hl keys import                   # Import keys
hl run avellaneda_mm --mock --max-ticks 3   # Validate
hl apex run --mock --max-ticks 5            # Full pipeline test
```

### Manual Setup

```bash
export HL_PRIVATE_KEY=0x...
export HL_TESTNET=true           # default

hl setup check                   # Validate environment
hl run engine_mm -i ETH-PERP --tick 10
```

### Mainnet

```bash
export HL_PRIVATE_KEY=0x...
export HL_TESTNET=false

hl run engine_mm -i ETH-PERP --tick 10 --mainnet
hl apex run --mainnet
```

---

## Strategies

23 built-in strategies across four categories. Every strategy extends `BaseStrategy` with a single `on_tick()` method — no shared state, no hidden coupling between strategies.

### Market Making

Provide two-sided liquidity and earn the spread.

| Strategy | Description | Key Parameters | When to Use |
|----------|-------------|----------------|-------------|
| `engine_mm` | Production quoting engine — composite 4-signal fair value, dynamic spreads, inventory skew, multi-level quote ladder. | `base_size`, `num_levels` | Primary MM strategy. |
| `avellaneda_mm` | Avellaneda-Stoikov optimal market maker. Reservation price adjusts with inventory. | `gamma`, `k`, `base_size` | Theoretically grounded inventory-aware quoting. |
| `regime_mm` | Vol-regime adaptive — classifies into 4 regimes, switches spread/sizing per regime. | `base_size` | Volatile markets. |
| `simple_mm` | Symmetric bid/ask at fixed spread around mid. | `spread_bps`, `size` | Testnet, benchmarking. |
| `grid_mm` | Fixed-interval grid levels above and below mid. | `grid_spacing_bps`, `num_levels` | Range-bound markets. |
| `liquidation_mm` | Provides liquidity during cascade/liquidation events. | `oi_drop_threshold_pct` | Liquidation-heavy markets. |

### Arbitrage

| Strategy | Description | Key Parameters | When to Use |
|----------|-------------|----------------|-------------|
| `funding_arb` | Cross-venue funding rate arbitrage. | `divergence_threshold_bps` | Funding divergence. |
| `basis_arb` | Trades implied basis from funding rate. | `basis_threshold_bps`, `size` | Contango/backwardation. |

### Signal / Directional

| Strategy | Description | Key Parameters | When to Use |
|----------|-------------|----------------|-------------|
| `momentum_breakout` | Volume + price breakout. | `lookback`, `breakout_threshold_bps` | Trending markets. |
| `mean_reversion` | Trades SMA deviation. | `window`, `threshold_bps` | Range-bound markets. |
| `aggressive_taker` | Crosses the spread with directional bias. | `size`, `bias_amplitude` | Strong directional conviction. |
| `power_law_btc` | Bitcoin Power Law rebalancing — long-term BTC accumulation based on the Power Law model. | See plugin config | Bitcoin believers. |
| `brent_oil_squeeze` | Oil supply squeeze momentum. | See strategy | Oil macro events. |
| `oil_liq_sweep` | Oil liquidation sweep. | See strategy | Oil cascade events. |
| `oil_war_regime` | Oil war regime mean-reversion. | See strategy | Oil geopolitical events. |
| `oi_divergence` | OI/price divergence signals. | See strategy | Smart money detection. |
| `trend_follower` | Multi-timeframe trend following. | See strategy | Trending markets. |
| `risk_multipliers` | Risk-adjusted position sizing. | See strategy | Portfolio overlay. |
| `simplified_ensemble` | Ensemble of multiple signal sources. | See strategy | Diversified signals. |
| `funding_momentum` | Funding rate momentum. | See strategy | Funding trends. |

### Infrastructure / Risk

| Strategy | Description | Key Parameters | When to Use |
|----------|-------------|----------------|-------------|
| `hedge_agent` | Reduces excess exposure per deterministic mandate. | `notional_threshold` | Always-on risk overlay. |
| `rfq_agent` | Block-size dark RFQ liquidity. | `min_size`, `spread_bps` | Institutional flow. |
| `claude_agent` | Multi-model LLM trading agent (Gemini, Claude, OpenAI). | `model`, `base_size` | Autonomous LLM reasoning. |

### Quoting Engine Pipeline

```
Market Data -> Composite Fair Value -> Dynamic Spread -> Inventory Skew -> Multi-Level Ladder -> Orders
               (4-signal blend)       (fee+vol+tox)     (price+size)     (exponential decay)
```

### LLM Agent (Multi-Model)

| Provider | Models | Env Variable |
|----------|--------|-------------|
| Google Gemini | `gemini-2.0-flash`, `gemini-2.5-pro` | `GEMINI_API_KEY` |
| Anthropic Claude | `claude-haiku-4-5-20251001`, `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-4o`, `gpt-4o-mini`, `o3-mini` | `OPENAI_API_KEY` |

---

## Skills

Built on the open [Agent Skills](https://agentskills.io) standard. Each skill is self-contained with instructions, scripts, and references.

| Skill | What it does |
|-------|-------------|
| **Onboard** | Step-by-step first-time setup — zero to first trade. |
| **APEX** | Fully autonomous 2-3 slot trading. Composes Radar + Pulse + Guard. |
| **Radar** | 4-stage funnel screening all HL perps. Scores 0-400. |
| **Pulse** | Detects sudden capital inflow via OI/volume/funding signals. |
| **Guard** | 2-phase trailing stop with tiered profit-locking. |
| **REFLECT** | Nightly self-improvement loop — analyzes trades, generates recommendations. |

### Install Skills

```bash
# Raw URLs
https://raw.githubusercontent.com/Chris0x88/hyperliquid-agent/main/skills/onboard/SKILL.md
https://raw.githubusercontent.com/Chris0x88/hyperliquid-agent/main/skills/apex/SKILL.md
https://raw.githubusercontent.com/Chris0x88/hyperliquid-agent/main/skills/radar/SKILL.md
https://raw.githubusercontent.com/Chris0x88/hyperliquid-agent/main/skills/pulse/SKILL.md
https://raw.githubusercontent.com/Chris0x88/hyperliquid-agent/main/skills/guard/SKILL.md
https://raw.githubusercontent.com/Chris0x88/hyperliquid-agent/main/skills/reflect/SKILL.md

# Claude Code
git clone https://github.com/Chris0x88/hyperliquid-agent.git ~/hyperliquid-agent
cd ~/hyperliquid-agent && pip install -e .
```

---

## Autonomous Trading Stack

### APEX — Autonomous Multi-Slot Strategy

Top-level orchestrator. Composes Radar + Pulse + Guard into a single autonomous strategy managing 2-3 concurrent positions.

| Preset | Slots | Leverage | Radar Threshold | Daily Loss Limit |
|--------|-------|----------|-----------------|------------------|
| `default` | 3 | 10x | 170 | $500 |
| `conservative` | 2 | 5x | 190 | $250 |
| `aggressive` | 3 | 15x | 150 | $1,000 |

```bash
hl apex run --mock --max-ticks 10          # Mock test
hl apex run                                 # Live testnet
hl apex run --preset conservative --mainnet # Live mainnet
```

### Guard — Dynamic Stop Loss

Two phases: **Phase 1** lets the trade breathe with wide retrace. **Phase 2** locks profit through tiered ratcheting.

```bash
hl guard run -i ETH-PERP --preset tight
```

### Radar — Opportunity Screening

Multi-factor screening across all HL perps. 4-stage funnel, scores 0-400.

```bash
hl radar once --mock    # Single scan
hl radar run --mock     # Continuous
```

### Pulse — Momentum Detection

Detects sudden capital inflow via OI, volume, funding, and price signals. 5-tier signal taxonomy.

```bash
hl pulse once --mock    # Single scan
hl pulse run --mock     # Continuous
```

### REFLECT — Performance Review

Nightly self-improvement loop. When running inside APEX, REFLECT auto-adjusts parameters based on findings (FDR, win rate, direction imbalance, consecutive losses).

```bash
hl reflect run --since 2026-03-01
hl reflect report
```

---

## Production Safety

- **Exchange-Level Stop Loss Sync** — Guard places trigger orders directly on Hyperliquid. If the runner crashes, the exchange-side stop remains active.
- **Clearinghouse Reconciliation** — Bidirectional reconciliation between APEX slots and HL positions. Detects orphans and size mismatches.
- **Risk Guardian** — Graduated risk response: OPEN → COOLDOWN → CLOSED with automatic transitions.
- **Rotation Cooldown** — Anti-churn: 45 min minimum hold, 5 min slot cooldown.
- **ALO Fee Optimization** — Entry orders default to post-only for maker rebates.

---

## Commands

```bash
# Core trading
hl run <strategy> [options]       # Start autonomous trading
hl status [--watch]               # Show positions, PnL, risk
hl trade <inst> <side> <size>     # Place a single order
hl account                        # Show HL account state
hl strategies                     # List all strategies

# Autonomous stack
hl apex run [options]             # APEX multi-slot orchestrator
hl apex reconcile [--fix]         # Reconcile state vs exchange
hl radar run [options]            # Opportunity radar
hl pulse run [options]            # Pulse momentum detector
hl guard run -i ETH-PERP [opts]  # Guard trailing stop
hl reflect run [--since DATE]    # Performance review

# Infrastructure
hl wallet auto [--save-env]       # Create wallet (agent-friendly)
hl setup check                    # Validate environment
hl mcp serve                      # Start MCP server
```

---

## MCP Server

Expose all trading tools via [Model Context Protocol](https://modelcontextprotocol.io) for AI agent integration.

```bash
hl mcp serve                      # stdio transport (default)
hl mcp serve --transport sse      # SSE transport
```

**16 tools:** `account`, `status`, `trade`, `run_strategy`, `strategies`, `radar_run`, `apex_status`, `apex_run`, `reflect_run`, `setup_check`, `wallet_list`, `wallet_auto`, `agent_memory`, `trade_journal`, `judge_report`

**[Full API Reference →](docs/api-reference.md)**

---

## Custom Strategies

```python
from sdk.strategy_sdk.base import BaseStrategy
from common.models import MarketSnapshot, StrategyDecision

class MyStrategy(BaseStrategy):
    def __init__(self, lookback=10, threshold=0.5, size=0.1, **kwargs):
        super().__init__(strategy_id="my_strategy")
        self.lookback, self.threshold, self.size = lookback, threshold, size
        self._prices = []

    def on_tick(self, snapshot, context=None):
        mid = snapshot.mid_price
        self._prices.append(mid)
        if len(self._prices) < self.lookback:
            return []

        pct = (mid - self._prices[-self.lookback]) / self._prices[-self.lookback] * 100
        if abs(pct) > self.threshold:
            return [StrategyDecision(
                action="place_order",
                instrument=snapshot.instrument,
                side="buy" if pct > 0 else "sell",
                size=self.size,
                limit_price=round(snapshot.ask if pct > 0 else snapshot.bid, 2),
            )]
        return []
```

```bash
hl run my_strategies.my_strategy:MyStrategy -i ETH-PERP --tick 10
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HL_PRIVATE_KEY` | Yes* | Hyperliquid private key |
| `HL_KEYSTORE_PASSWORD` | Alt* | Password for encrypted keystore |
| `HL_TESTNET` | No | `true` (default) or `false` for mainnet |
| `ANTHROPIC_API_KEY` | No | For `claude_agent` with Claude |
| `GEMINI_API_KEY` | No | For `claude_agent` with Gemini |
| `OPENAI_API_KEY` | No | For `claude_agent` with OpenAI |

\* Either `HL_PRIVATE_KEY` or a keystore with `HL_KEYSTORE_PASSWORD` is required.

---

## Architecture

```
cli/           CLI commands and trading engine
  commands/    Subcommand modules (run, apex, radar, pulse, guard, reflect, ...)
  mcp_server.py  MCP server (16 tools via FastMCP)
  hl_adapter.py  Direct HL API adapter (live + mock)
  keystore.py    Encrypted keystore (geth-compatible)
  strategy_registry.py  Strategy + market definitions
strategies/    23 trading strategy implementations
modules/       Pure logic modules (zero I/O)
skills/        Agent Skills (SKILL.md + runners)
plugins/       Strategy plugins (power_law_btc)
sdk/           Strategy base class and model registry
parent/        HL API proxy, position tracking, risk management
scripts/       Backtest harness, bootstrap
tests/         Test suite
```

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## Heritage

HyperLiquid Agent is forked from [Nunchi's agent-cli](https://github.com/Nunchi-trade/agent-cli). Credit to the Nunchi team for the foundational architecture. We've removed all fees, telemetry, and external dependencies — and we're taking the project in our own direction: fully open, community-first, and continuously improving.

See [ATTRIBUTION.md](ATTRIBUTION.md) for full credits.

---

## Direction

This is an actively maintained project. The plan:
- Keep tracking upstream Nunchi for useful updates
- Add more strategies and improve existing ones
- Better backtesting and historical data (Hydromancer Reservoir)
- Deeper AI agent integration
- Community contributions welcome

---

<p align="center">
  <sub>MIT License &bull; Chris Imgraben</sub>
</p>
