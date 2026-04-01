---
name: hyperliquid-research
description: "Navigate the HyperLiquid Agent trading research system. Use when discussing oil trades, BTC positions, market thesis, facility damage, troop movements, or any trading-related question. Reads research files from the agent-cli repo."
---

# HyperLiquid Research Navigator

When the user asks about oil, BTC, trading positions, market analysis, or thesis:

## Step 1: Read Current State
```bash
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/markets/xyz_brentoil/README.md
```

## Step 2: Read Latest Signals
```bash
tail -5 /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/markets/xyz_brentoil/signals.jsonl
```

## Step 3: Read Latest Research Notes
```bash
ls -t /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/markets/xyz_brentoil/notes/ | head -5
```
Then read the most recent note file.

## Step 4: Check Active Strategy
```bash
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/strategy_versions/ACTIVE.md
```

## Step 5: Check Framework
```bash
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/FRAMEWORK.md
```

## Step 6: Check Operations Manual
```bash
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/OPERATIONS.md
```

## For BTC/Vault Questions
```bash
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/markets/btc/README.md
tail -5 /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/markets/btc/signals.jsonl
```

## Key Facts (Quick Reference)
- Contract: xyz:BRENTOIL tracks ICE Brent June 2026 (BZM6), rolling Jul 7-13
- Oracle: Pyth Network. Funding: hourly. Margin: isolated only. Max 20x.
- OI cap: $750M. Trading hours: Sun 6PM ET - Fri 5PM ET.
- Thesis: 10M bpd gap unfillable. Physical $126 vs paper $112.
- Key people: Druckenmiller (commodity supercycle), Bessent (Treasury), Lutnick (Commerce)
- Risk: April 6 deadline, contract roll Apr 7-13, weekend liquidity

Always read the files before answering — they contain the latest intelligence from Claude Code's research sessions.
