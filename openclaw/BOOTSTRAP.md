# BOOTSTRAP.md — First Session Startup

On first session or after restart:

## Step 1: Load Skills
Load the `hyperliquid-research` skill immediately. This gives you access to MCP tools for all trading data.

## Step 2: Read Current State via MCP Tools
**Do NOT use bash commands — they will be blocked by the gateway.**

Call these MCP tools instead:
1. `market_context(market="xyz:BRENTOIL")` — Gets pre-assembled market brief
2. `account(mainnet=True)` — Gets live account state
3. `status()` — Quick position overview

## Step 3: Greet
Tell the user you're online and give a 3-line status:
- Current BRENTOIL position (or FLAT)
- Thesis strength
- Next catalyst

## Step 4: Be Ready
The user will ask about markets. Use MCP tools first, answer from data.
If any tool fails, call `diagnostic_report()` to understand why, then tell the user.
