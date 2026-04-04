---
name: hyperliquid-research
description: "Navigate the HyperLiquid Agent trading research system. Use when discussing oil trades, BTC positions, market thesis, facility damage, troop movements, or any trading-related question. Uses MCP tools — NO bash commands."
---

# HyperLiquid Research Navigator

## CRITICAL: Do NOT use bash/shell commands. They will be blocked.

All data access goes through MCP tools. Never run cat, tail, ls, or any shell command.

## How to Answer Any Trading Question

### Step 1: Call `market_context` MCP tool
This returns pre-assembled market data including technicals, position state, memory context, and thesis — all in one call. This is your primary data source.

```
market_context(market="xyz:BRENTOIL", budget=2000)
```

For BTC questions:
```
market_context(market="BTC", budget=2000)
```

### Step 2: For live position/account data
```
account(mainnet=True)
```
or
```
status()
```

### Step 3: For technical analysis
```
analyze(coin="BRENTOIL", interval="1h", days=30)
```

### Step 4: For historical context
```
agent_memory(query_type="recent", limit=20)
trade_journal(limit=10)
```

### Step 5: For historical candles
```
get_candles(coin="BRENTOIL", interval="1h", days=30)
```

## When Something Fails

Call `diagnostic_report()` to see what's broken, then tell the user what happened. Never silently fail.

## Key Facts (Quick Reference)
- Contract: xyz:BRENTOIL tracks ICE Brent June 2026 (BZM6), rolling Jul 7-13
- Oracle: Pyth Network. Funding: hourly. Margin: isolated only. Max 20x.
- OI cap: $750M. Trading hours: Sun 6PM ET - Fri 5PM ET.
- Main account: 0x80B5801...F205 (oil, gold, silver on xyz clearinghouse)
- Vault account: 0x9da9a9...98da (BTC/ETH on native clearinghouse)
- Key thesis: Supply disruption (Hormuz), 10M bpd gap unfillable
- Trading style: Druckenmiller — asymmetric sizing on high conviction

## Report Issues
If you notice a problem, call `log_bug(title="...", description="...")` so Claude Code can fix it.
