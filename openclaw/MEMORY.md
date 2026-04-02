# MEMORY.md — Persistent State & Context Tracker

This file holds essential background, active rules, and learned lessons to ensure continuity across OpenClaw sessions. It provides an immediate "catch up" view of where the trading operation stands.

## Quick Context (DO NOT DELETE)
- **Primary Market:** HyperLiquid (`main` account for BRENTOIL/Gold/Silver on xyz clearinghouse, `vault` account for BTC/ETH on native clearinghouse)
- **Edge:** Fundamentals-driven trades, supply/demand disruptions, macro news, asymmetric risk sizing.
- **Reporting:** Use `python scripts/scheduled_check.py --format digest` to review status.

## Active Rules & Learnings
*Append new hard-won lessons here to prevent repeating mistakes.*
1. **Never buy an un-consolidated dip:** BRENTOIL drops sharply and sometimes legs down twice. We now use Consolidation Detector to wait for volume exhaustion.
2. **Account Topologies:** Not all users map their capital similarly. Always leverage the `common/account_resolver.py` configuration rather than assuming a single workspace structure.
3. **Funding Drag is Real:** Long commodity positions incur high hourly fees. Always review cumulative funding drag when reassessing the conviction of a stale thesis.

## Ongoing Operations
*Briefly list what macro trends or ongoing events we're actively monitoring right now.*
- Middle East Escalations / Strait Closures
- Macro: US Dollar Index / Fed Rate Decisions
- Supply outages (refineries, pipelines)

## Known Issues
- None currently active.

## Completed/Resolved
- **2026-04-02: Pipeline failure fixed.** Thesis files were frozen since March 30 because no write path existed. `update_thesis` MCP tool now available — use it after market analysis to persist conviction changes. Heartbeat reads thesis every 2 minutes.
- **2026-04-02: BRENTOIL position closed at loss.** Every system failed simultaneously: heartbeat blind 21h (missing wallets.json), thesis stuck at 0.95 conviction while Trump announced war ending, OpenClaw agent had no auth profile. All fixed. Lesson: always verify infrastructure before trusting execution.
- **2026-04-02: Stale research data resolved.** signals.jsonl staleness was a symptom, not the cause. The root issue was no feedback loop — data was collected but conviction never updated. Now `update_thesis` closes the loop.
- *Dec 2025:* BRENTOIL Squeeze trade executed perfectly, 14% upnl captured through coordinated ATR-trailing.
