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

## Completed/Resolved
*Move closed theses or resolved macro events here to maintain a timeline.*
- *[Example]* Dec 2025: BRENTOIL Squeeze trade executed perfectly, 14% upnl captured through coordinated ATR-trailing.
