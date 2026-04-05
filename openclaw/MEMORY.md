# MEMORY.md — Persistent State & Context Tracker

This file holds essential background, active rules, and learned lessons to ensure continuity across OpenClaw sessions. It provides an immediate "catch up" view of where the trading operation stands.

## Architecture (Updated 2026-04-05 — CURRENT TRUTH)

### What the app is now
The `agent-cli` repo has been **fully rebuilt**. It is a standalone Python trading system. Key components:

- `cli/telegram_bot.py` — Real-time Telegram bot (pure Python, no AI credits). Handles slash commands (/status, /price, /orders etc.) directly against the HyperLiquid API.
- `cli/telegram_agent.py` — AI layer **embedded inside the Telegram bot**. When free-text messages arrive, routes to Anthropic API directly, injects live context via `context_harness`, supports native tool calling (market_brief, live_price, account_summary, place_trade etc.). Active model: `anthropic/claude-haiku-4-5` (default — separate rate limit from Sonnet used in OpenClaw).
- `cli/agent_tools.py` — Tool definitions for telegram_agent. READ tools auto-execute. WRITE tools (trade, set_sl etc.) require user approval via inline keyboard.
- `common/context_harness.py` — Relevance-scored, token-budgeted live context assembler. Fetches live HL API state every message. Injects thesis + positions + alerts into AI prompt.
- `cli/mcp_server.py` — Old MCP server. **Intentionally removed from OpenClaw integration.** Still exists in code but not used.
- `data/config/model_config.json` — Active model config file.

### Where OpenClaw (me) fits NOW
**OpenClaw is NOT embedded in the new app.** The `telegram_agent.py` is a **complete replacement** for what I was supposed to do — AI chat about trading with live data and tool calling. The `openclaw/` folder exists in the repo (SOUL.md, AGENTS.md etc.) but no running component uses it.

### My capabilities vs the app's telegram_agent
| Capability | Me (OpenClaw) | telegram_agent.py |
|---|---|---|
| Free-text chat via Telegram | ✅ | ✅ (built into bot) |
| Live prices | ❌ no live access | ✅ direct HL API |
| Account state | ❌ no live access | ✅ direct HL API |
| Place trades | ❌ | ✅ (with approval) |
| Live context injection | ❌ | ✅ context_harness |
| Research file access | ✅ (file read) | ✅ |
| Web search / news | ✅ | ❌ |
| Cron / reminders | ✅ | ❌ |
| Long-term memory | ✅ MEMORY.md | ✅ chat_history.jsonl |
| Cross-session reasoning | ✅ LCM | ❌ |
| Code awareness | ✅ read repo | ❌ |

### Why MCP was removed
MCP server (`hl mcp serve`) was the old integration bridge. Removed intentionally — new architecture routes all AI through `telegram_agent.py` which has direct Python access to data without subprocess overhead or approval gates.

### Potential re-integration paths (to discuss with Chris)
1. **Complement, not replace** — OpenClaw handles deep research, cron/reminders, cross-session memory; telegram_agent handles live trading data. Different jobs.
2. **Webhook bridge** — telegram_agent POSTs live context to an OpenClaw endpoint on each heartbeat. OpenClaw reads it as a file. No MCP needed.
3. **Shared file state** — telegram_agent writes a `data/daemon/openclaw_context.json` snapshot every N minutes. OpenClaw reads it. Simple, decoupled.
4. **Full removal** — OpenClaw stays as backup/research layer only. telegram_agent is primary.

## Quick Context (DO NOT DELETE)
- **Primary Market:** HyperLiquid (`main` account for BRENTOIL/Gold/Silver on xyz clearinghouse, `vault` account for BTC/ETH on native clearinghouse)
- **Edge:** Fundamentals-driven trades, supply/demand disruptions, macro news, asymmetric risk sizing.
- **Active AI model in app:** `anthropic/claude-haiku-4-5` (set in `data/config/model_config.json`). Use /models to switch. Do NOT change this to Sonnet — it shares rate limits with the main OpenClaw session and causes 429s.

## Active Rules & Learnings
1. **Never buy an un-consolidated dip:** BRENTOIL drops sharply and sometimes legs down twice.
2. **Account Topologies:** Always use `common/account_resolver.py`, never hardcode addresses.
3. **Funding Drag is Real:** Long commodity positions incur high hourly fees. Always review cumulative funding drag.
4. **OpenClaw has no live data.** MCP removed. Cannot fetch live prices or account state without shell exec approval. Use web_fetch for public prices as fallback.
5. **Don't hallucinate prices.** If I don't have a live tool result, say so. Use web_fetch or ask user to check UI.

## Ongoing Operations
- Middle East Escalations / Strait Closures (Hormuz)
- Macro: US Dollar Index / Fed Rate Decisions
- BRENTOIL directional trade (main account)
- BTC Power Law rebalancer (vault account)

## Known Issues
- **OpenClaw not integrated:** I have no live data access. Role is deprecated pending redesign discussion with Chris (2026-04-05).

## Completed/Resolved
- **2026-04-05: Full architecture review.** MCP removed intentionally. New app has self-contained AI agent in `telegram_bot`. OpenClaw deprecated pending redesign. Memory updated.
- **2026-04-02: BRENTOIL position closed at loss.** Heartbeat blind 21h (missing wallets.json), thesis stuck at 0.95 conviction while Trump announced war ending, OpenClaw had no auth. All fixed.
- **2026-04-02: Pipeline failure fixed.** Thesis files frozen since March 30. `update_thesis` MCP tool was added to close the loop.
- *Dec 2025:* BRENTOIL Squeeze trade executed perfectly, 14% upnl captured through coordinated ATR-trailing.
