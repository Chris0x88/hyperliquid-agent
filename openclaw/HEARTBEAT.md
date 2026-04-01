# HEARTBEAT.md — OpenClaw Periodic Checks

The OpenClaw agent runs this file on a cadence to maintain situational awareness.

## Status Check

Run the following command to get the latest market state, account equity, position status, and active alerts:

```bash
python scripts/scheduled_check.py --format digest
```

**Instructions for AI:**
1. Run the command above.
2. Read the digest output carefully.
3. If there are **CRITICAL ALERTS** or **SL DRIFT**, notify the user immediately and recommend action.
4. Review active positions against the active theses. If the thesis is stale, initiate a review.
5. If everything is nominal, log the status silently and take no action.
