# HEARTBEAT.md — OpenClaw Periodic Checks

The OpenClaw agent runs this file on a cadence to maintain situational awareness.

## Status Check

**Do NOT use bash commands — they will be blocked by the gateway.**

Use MCP tools instead:

1. Call `market_context(market="xyz:BRENTOIL")` for pre-assembled market brief
2. Call `account(mainnet=True)` for live account state
3. Call `status()` for quick position overview

**Instructions for AI:**
1. Call the MCP tools above.
2. Review the context output carefully.
3. If there are **CRITICAL ALERTS** or **SL DRIFT**, notify the user immediately and recommend action.
4. Review active positions against the active theses. If the thesis is stale, initiate a review.
5. If everything is nominal, log the status silently and take no action.
6. If tools fail, call `diagnostic_report()` and `log_bug()` with the failure details.
