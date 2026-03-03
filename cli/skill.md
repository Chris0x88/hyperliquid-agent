---
name: yex-trader
description: Autonomous Hyperliquid trading — 14 strategies (MM, momentum, arbitrage, LLM) with WOLF multi-slot orchestrator, HOWL performance review, DSL trailing stops, and builder fee revenue collection.
user-invocable: true
argument-hint: "<strategy> [options]"
allowed-tools:
  - Bash
metadata:
  openclaw:
    requires:
      env:
        - HL_PRIVATE_KEY
      bins:
        - python3
    primaryEnv: HL_PRIVATE_KEY
---

# YEX Trader

Autonomous Hyperliquid trading via agent-cli. 14 strategies across market making, momentum, arbitrage, and LLM-powered trading. WOLF multi-slot orchestrator. HOWL nightly performance review. Builder fee revenue collection.

## Setup

```bash
cd ~/agent-cli && pip install -e .
hl setup check  # Validate environment
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HL_PRIVATE_KEY` | Yes* | Hyperliquid private key |
| `HL_KEYSTORE_PASSWORD` | Alt* | Password for encrypted keystore |
| `HL_TESTNET` | No | `true` (default) or `false` |
| `BUILDER_ADDRESS` | No | Builder fee collection address |
| `BUILDER_FEE_TENTHS_BPS` | No | Fee in tenths of bps (10 = 1 bps) |
| `ANTHROPIC_API_KEY` | No | For `claude_agent` strategy |
| `GEMINI_API_KEY` | No | For `claude_agent` with Gemini |

\* Either `HL_PRIVATE_KEY` or a keystore with `HL_KEYSTORE_PASSWORD` is required.

## Commands

### Core Trading

```bash
# Start autonomous trading
hl run <strategy> [-i INSTRUMENT] [-t TICK] [--config FILE] [--mainnet] [--dry-run] [--mock] [--max-ticks N]

# Single manual order
hl trade <instrument> <side> <size>

# Account info
hl account [--mainnet]

# Check positions and PnL
hl status [--watch] [--interval 5]

# List all strategies
hl strategies
```

### WOLF Multi-Slot Orchestrator

```bash
hl wolf run [-t 60] [--preset conservative|default|aggressive] [--mock] [--budget 1000] [--slots 5]
hl wolf once [--mock]
hl wolf status
hl wolf presets
```

### HOWL Performance Review

```bash
hl howl run [--since 2026-03-01] [--data-dir data/cli]
hl howl report [--date 2026-03-03]
hl howl history [-n 10]
```

### Dynamic Stop Loss (DSL)

```bash
hl dsl start <instrument> [--entry-price 2500] [--direction long] [--preset tight|standard|wide]
hl dsl check <instrument>
hl dsl status
hl dsl presets
```

### Scanner & Movers

```bash
hl scanner run [--top 10] [--min-score 7.0]
hl scanner history [-n 5]
hl movers run [--top 10]
```

### Builder Fee

```bash
hl builder status
hl builder approve [--mainnet]
```

### Wallet (Encrypted Keystore)

```bash
hl wallet create
hl wallet import --key <hex>
hl wallet list
hl wallet export [--address 0x...]
```

### Environment Setup

```bash
hl setup check
```

### TEE Clearing House

```bash
hl house join [--mainnet]
hl house status
```

## Strategies (14)

| Name | Type | Description |
|------|------|-------------|
| simple_mm | MM | Symmetric bid/ask quoting around mid |
| avellaneda_mm | MM | Inventory-aware Avellaneda-Stoikov model |
| engine_mm | MM | Production quoting engine — composite FV, dynamic spreads, multi-level ladder |
| regime_mm | MM | Vol-regime adaptive — switches behavior by volatility regime (calm/normal/volatile/extreme) |
| grid_mm | MM | Fixed-interval grid levels above and below mid |
| liquidation_mm | MM | Provides liquidity during cascade/liquidation events |
| funding_arb | Arb | Cross-venue funding rate arbitrage |
| basis_arb | Arb | Trades implied basis from funding rate (contango/backwardation) |
| mean_reversion | Signal | Trades when price deviates from SMA |
| momentum_breakout | Signal | Enters on volume + price breakout above/below N-period range |
| aggressive_taker | Taker | Directional spread crossing with bias |
| hedge_agent | Risk | Reduces excess exposure per deterministic mandate |
| rfq_agent | RFQ | Block-size dark RFQ liquidity |
| claude_agent | LLM | Claude/Gemini-powered autonomous trading agent |

## Instruments

- **Standard perps**: ETH-PERP, BTC-PERP, SOL-PERP, etc.
- **YEX yield markets**: VXX-USDYP (yex:VXX), US3M-USDYP (yex:US3M)

## Workflow

1. **Setup**: `hl setup check`
2. **Mock test**: `hl run avellaneda_mm --mock --max-ticks 5`
3. **Dry run**: `hl run engine_mm --dry-run --max-ticks 10`
4. **Live testnet**: `hl run engine_mm -i ETH-PERP --tick 10`
5. **WOLF mode**: `hl wolf run --mock --max-ticks 5`
6. **Monitor**: `hl status --watch`
7. **Review**: `hl howl run`

## Builder Fee Revenue

Set `BUILDER_ADDRESS` and `BUILDER_FEE_TENTHS_BPS` to collect fees on every trade. Users must approve once via `hl builder approve`. Fee is collected natively by Hyperliquid — no extra gas, no contract calls.

## HOWL Self-Improvement

Run `hl howl run` after a trading session. HOWL computes win rate, fee drag ratio (FDR), direction analysis, holding period buckets, monster trade dependency, and generates actionable recommendations. Reports saved to `data/howl/`.
