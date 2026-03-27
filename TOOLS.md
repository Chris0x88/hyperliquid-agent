# Tools

## MCP Server

Start with `hl mcp serve` (stdio) or `hl mcp serve --transport sse` (HTTP).

Exposes 15 trading tools via Model Context Protocol:

### Query Tools (fast, no side effects)
- `strategies` -- List all 15 available strategies with params
- `account` -- Show HL account state (balance, margin, positions)
- `status` -- Current positions, PnL, and risk state
- `setup_check` -- Validate environment configuration
- `wallet_list` -- List available wallets

### Action Tools (side effects, may be long-running)
- `trade` -- Place a single order (instrument, side, size)
- `run_strategy` -- Start autonomous strategy trading
- `apex_run` -- Start APEX autonomous multi-slot trading
- `apex_status` -- Show APEX orchestrator state
- `radar_run` -- Run opportunity radar across all HL perps
- `reflect_run` -- Run REFLECT performance review
- `wallet_auto` -- Create wallet automatically

### Intelligence Tools (memory and analysis)
- `agent_memory` -- Read learnings, param changes, market observations
- `trade_journal` -- Structured position records with reasoning
- `judge_report` -- Signal quality evaluation and false positive rates

## CLI: hl

All MCP tools are also available as CLI commands. Use the CLI for operations not exposed via MCP:

```bash
# Core trading
hl run <strategy> [-i INSTRUMENT] [-t TICK] [--mock] [--dry-run] [--mainnet] [--max-ticks N]
hl trade <instrument> <side> <size>
hl account [--mainnet]
hl status [--watch]
hl strategies

# APEX multi-slot orchestrator
hl apex run [--preset default|conservative|aggressive] [--mock] [--mainnet]
hl apex once [--mock]
hl apex status
hl apex presets

# Radar opportunity scanner
hl radar once [--mock]
hl radar run [--top 10]

# Guard trailing stop
hl guard run -i <instrument> [--preset tight|standard|wide]

# Performance review
hl reflect run [--since DATE]
hl reflect report [--date DATE]

# Market browser
hl markets [--search BTC] [--sort volume] [--min-volume 1000000]
hl markets info BTC

# Wallet management
hl wallet auto                       # Agent-friendly non-interactive
hl wallet list
hl wallet import --key <hex>

# Environment
hl setup check
```

## Strategies (15)

| Name | Type | Description |
|------|------|-------------|
| simple_mm | MM | Symmetric bid/ask quoting around mid |
| avellaneda_mm | MM | Inventory-aware Avellaneda-Stoikov model |
| engine_mm | MM | Production quoting engine -- composite FV, dynamic spreads |
| regime_mm | MM | Vol-regime adaptive (calm/normal/volatile/extreme) |
| grid_mm | MM | Fixed-interval grid levels above and below mid |
| liquidation_mm | MM | Provides liquidity during cascade events |
| funding_arb | Arb | Cross-venue funding rate arbitrage |
| basis_arb | Arb | Trades implied basis from funding rate |
| mean_reversion | Signal | Trades when price deviates from SMA |
| momentum_breakout | Signal | Enters on volume + price breakout |
| aggressive_taker | Taker | Directional spread crossing with bias |
| hedge_agent | Risk | Reduces excess exposure per mandate |
| rfq_agent | RFQ | Block-size dark RFQ liquidity |
| claude_agent | LLM | LLM-powered autonomous trading (Gemini/Claude/OpenAI) |
| power_law_btc | Model | Bitcoin Heartbeat Model -- power-law rebalancer (0-40x) |

## Instruments

- **Standard perps**: ETH-PERP, BTC-PERP, SOL-PERP, and 226 more (`hl markets` to browse)
- **YEX yield markets**: VXX-USDYP, US3M-USDYP, BTCSWP-USDYP
