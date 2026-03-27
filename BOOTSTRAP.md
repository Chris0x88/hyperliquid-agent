# Bootstrap

Run these checks on every startup. Execute silently -- only report errors or the final status.

## Startup Sequence

1. **Check environment:**
```bash
hl setup check
```
If this fails, report the missing configuration to the user and stop.

2. **Check account balance:**
```bash
hl account
```
If balance is 0, tell the user: "Account has no balance. Deposit USDC via the Hyperliquid web UI before trading."

3. **Check existing positions:**
```bash
hl status
```

4. **Check APEX state (if exists):**
```bash
hl apex status
```

5. **Report ready:**
Report to user: "Agent ready. Balance: $X. Active positions: N. Say 'start trading' to begin APEX, or ask me to scan for opportunities."

## On Failure

If any check fails, report the specific error and suggest a fix. Do not start trading with a broken environment.

## First-Time Setup

If the environment has never been configured:

```bash
# Create wallet (agent-friendly, non-interactive)
hl wallet auto --save-env

# Verify
hl setup check

# Test with mock data (no funds needed)
hl run avellaneda_mm --mock --max-ticks 3
```

Then ask the user to:
1. Set `HL_PRIVATE_KEY` or configure keystore
2. Deposit USDC to their Hyperliquid account
3. Set `HL_TESTNET=false` when ready for mainnet
