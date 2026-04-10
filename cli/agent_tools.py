"""Agent tool definitions and executor for Telegram AI agent.

Provides OpenAI-format tool schemas for OpenRouter function calling.
READ tools execute automatically. WRITE tools require user approval
via Telegram inline keyboard before execution.

Tool implementations call the same underlying libraries as the MCP server
(common.context_harness, modules.candle_cache, etc.) but do NOT import
from mcp_server.py to avoid the mcp package dependency.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

log = logging.getLogger("agent_tools")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HL_API = "https://api.hyperliquid.xyz/info"
_MAX_RESPONSE_CHARS = 12000

# Write tools that require user approval before execution
WRITE_TOOLS = {"place_trade", "update_thesis", "close_position", "set_sl", "set_tp", "memory_write", "edit_file", "run_bash"}

# Display tools — pre-formatted output, send directly to Telegram without LLM commentary
DISPLAY_TOOLS = {"get_calendar", "get_research", "get_technicals"}

# Durable pending actions — file-backed so approvals survive bot restarts.
_PENDING_FILE = _PROJECT_ROOT / "data" / "state" / "pending_actions.json"
_pending_actions: Dict[str, dict] = {}


def _load_pending() -> None:
    """Hydrate in-memory cache from durable store on startup."""
    global _pending_actions
    try:
        if _PENDING_FILE.exists():
            raw = json.loads(_PENDING_FILE.read_text())
            now = time.time()
            # Only load non-expired entries
            _pending_actions = {k: v for k, v in raw.items() if now - v.get("ts", 0) <= 300}
    except Exception:
        _pending_actions = {}


def _persist_pending() -> None:
    """Atomically write pending actions to disk."""
    try:
        _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PENDING_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_pending_actions))
        tmp.replace(_PENDING_FILE)
    except Exception:
        log.warning("Failed to persist pending actions", exc_info=True)


# Hydrate on import
_load_pending()


# ═══════════════════════════════════════════════════════════════════════
# Tool Definitions (OpenAI format)
# ═══════════════════════════════════════════════════════════════════════

TOOL_DEFS: List[dict] = [
    {
        "type": "function",
        "function": {
            "name": "market_brief",
            "description": "Get a compact market brief: price, technicals, position, thesis, and memory for a market.",
            "parameters": {
                "type": "object",
                "properties": {
                    "market": {
                        "type": "string",
                        "description": "Market identifier, e.g. 'xyz:BRENTOIL', 'BTC', 'xyz:GOLD'",
                    },
                },
                "required": ["market"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "account_summary",
            "description": "Get account equity, open positions with entry/uPnL/leverage/liquidation, and spot balances.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "live_price",
            "description": "Get current prices for all watched markets or a specific one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "market": {
                        "type": "string",
                        "description": "Optional. Specific market like 'BTC' or 'xyz:BRENTOIL'. Omit for all prices.",
                        "default": "all",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_market",
            "description": "Deep technical analysis: trend, support/resistance, ATR, Bollinger bands, volume profile, flags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {
                        "type": "string",
                        "description": "Coin to analyze, e.g. 'BTC', 'xyz:BRENTOIL'",
                    },
                },
                "required": ["coin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_orders",
            "description": "Get all open orders across both clearinghouses.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trade_journal",
            "description": "Get recent trade history and journal entries. Hard-capped at 25 per call (NORTH_STAR P10).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return (1-25). Default 10.",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 25,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_signals",
            "description": "Get recent Pulse (capital inflow) and Radar (opportunity scanner) trade signals. Hard-capped at 50 per call (NORTH_STAR P10).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max signals to return (1-50). Default 20.",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "source": {
                        "type": "string",
                        "enum": ["all", "pulse", "radar"],
                        "description": "Filter by signal source",
                        "default": "all",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_funding",
            "description": "Get funding rate, premium, and open interest for a market.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {
                        "type": "string",
                        "description": "Coin to check, e.g. 'BTC', 'BRENTOIL'",
                    },
                },
                "required": ["coin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_trade",
            "description": "Place a trade order. REQUIRES USER APPROVAL before execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {"type": "string", "description": "Market, e.g. 'BRENTOIL', 'BTC'"},
                    "side": {"type": "string", "enum": ["buy", "sell"], "description": "Buy (long) or sell (short)"},
                    "size": {"type": "number", "description": "Number of contracts/coins"},
                },
                "required": ["coin", "side", "size"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_thesis",
            "description": "Update thesis conviction and direction for a market. REQUIRES USER APPROVAL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "market": {"type": "string", "description": "Market, e.g. 'xyz:BRENTOIL'"},
                    "direction": {"type": "string", "enum": ["long", "short", "flat"]},
                    "conviction": {"type": "number", "description": "0.0 to 1.0"},
                    "summary": {"type": "string", "description": "Brief thesis summary"},
                },
                "required": ["market", "direction", "conviction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_position",
            "description": "Close an existing position via IOC market order. The 'side' is the CLOSING side (opposite of position direction): use 'sell' to close a long, 'buy' to close a short. REQUIRES USER APPROVAL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {"type": "string", "description": "Market identifier, e.g. 'BTC', 'xyz:BRENTOIL', 'xyz:SP500'"},
                    "side": {"type": "string", "enum": ["buy", "sell"], "description": "Closing side (opposite of position direction)"},
                    "size": {"type": "number", "description": "Number of contracts/coins to close"},
                },
                "required": ["coin", "side", "size"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_sl",
            "description": "Place an exchange-side stop-loss trigger order. Every position MUST have a stop-loss on the exchange (hard rule). REQUIRES USER APPROVAL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {"type": "string", "description": "Market identifier"},
                    "side": {"type": "string", "enum": ["buy", "sell"], "description": "Stop side (opposite of position direction — 'sell' stops a long, 'buy' stops a short)"},
                    "size": {"type": "number", "description": "Size to stop"},
                    "trigger_price": {"type": "number", "description": "Trigger price for the stop"},
                },
                "required": ["coin", "side", "size", "trigger_price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_tp",
            "description": "Place an exchange-side take-profit trigger order. Every position MUST have a take-profit on the exchange (hard rule). REQUIRES USER APPROVAL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {"type": "string", "description": "Market identifier"},
                    "side": {"type": "string", "enum": ["buy", "sell"], "description": "TP side (opposite of position direction)"},
                    "size": {"type": "number", "description": "Size to take profit on"},
                    "trigger_price": {"type": "number", "description": "Trigger price for the take-profit"},
                },
                "required": ["coin", "side", "size", "trigger_price"],
            },
        },
    },
    # ── General tools ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the project. Path relative to project root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to project root, e.g. 'cli/telegram_agent.py'"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search the codebase for a pattern (grep). Returns matching lines with file:line format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex supported)"},
                    "path": {"type": "string", "description": "Directory to search in, relative to project root", "default": "."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files matching a glob pattern relative to project root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py', 'cli/*.py', 'docs/wiki/*.md'"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information. Returns titles, URLs, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results to return", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_read",
            "description": "Read from agent persistent memory. Use 'index' to see all topics, or specify a topic name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic name or 'index' for the memory index", "default": "index"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": "Write to agent persistent memory. Creates or updates a topic file. REQUIRES APPROVAL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic name (becomes filename, e.g. 'trading_rules')"},
                    "content": {"type": "string", "description": "Full content to write to the topic file (markdown)"},
                },
                "required": ["topic", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a project file by replacing a specific string. Claude Code pattern. REQUIRES APPROVAL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to project root"},
                    "old_str": {"type": "string", "description": "Exact string to find and replace (must be unique in file)"},
                    "new_str": {"type": "string", "description": "Replacement string"},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Run a shell command in the project directory. 30s timeout. REQUIRES APPROVAL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_errors",
            "description": "Get recent agent errors from diagnostics. Helps you understand what's failing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max errors to return", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_feedback",
            "description": "Get recent user feedback submitted via /feedback. Hard-capped at 25 per call (NORTH_STAR P10). Each entry's text is truncated at 500 chars.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max feedback entries to return (1-25). Default 10.",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 25,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "introspect_self",
            "description": (
                "Returns a live snapshot of YOUR OWN state — active model, available tools, "
                "approved markets (watchlist), open positions across all venues, thesis files "
                "with ages, last memory consolidation timestamp, and daemon health. "
                "Call this whenever you are unsure what you can do, what you are configured "
                "to know, or what state the system is in. Prefer this over guessing from prompt knowledge."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_reference",
            "description": (
                "Read one of your built-in reference docs at agent/reference/<topic>.md. "
                "Topics: 'tools' (every tool, when to use it, failure modes), "
                "'architecture' (what runs where, file roles), "
                "'workflows' (how to think about a trade, verify execution, handle failures), "
                "'rules' (current trading rules and constraints). "
                "Use these when you need depth that the always-loaded prompt does not carry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": ["tools", "architecture", "workflows", "rules"]},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_lessons",
            "description": (
                "BM25-ranked search over your trade-lesson corpus (verbatim post-mortems "
                "of closed trades written after each position closes). Use this BEFORE "
                "opening a new position to check whether you've traded a similar setup "
                "before and what happened — the lesson summaries are injected automatically "
                "at decision time, but this tool lets you drill in with specific queries. "
                "Empty query returns most-recent lessons ordered by trade_closed_at. "
                "Non-empty query uses FTS5 over summary + body_full + tags, ranked by BM25. "
                "Results exclude lessons Chris rejected (reviewed_by_chris = -1) unless "
                "include_rejected=True (useful for anti-pattern search). Returns lesson "
                "id, market, direction, outcome, ROE%, summary. Use get_lesson(id) to read "
                "the verbatim body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword search over summary/body/tags. Empty string returns recent lessons by date.",
                        "default": "",
                    },
                    "market": {
                        "type": "string",
                        "description": "Optional market filter, e.g. 'xyz:BRENTOIL', 'BTC'.",
                    },
                    "direction": {
                        "type": "string",
                        "description": "Optional direction filter: 'long', 'short', or 'flat'.",
                        "enum": ["long", "short", "flat"],
                    },
                    "signal_source": {
                        "type": "string",
                        "description": "Optional signal source filter: 'thesis_driven', 'radar', 'pulse_signal', 'pulse_immediate', 'manual'.",
                    },
                    "lesson_type": {
                        "type": "string",
                        "description": "Optional lesson type filter.",
                        "enum": [
                            "sizing",
                            "entry_timing",
                            "exit_quality",
                            "thesis_invalidation",
                            "funding_carry",
                            "catalyst_timing",
                            "pattern_recognition",
                        ],
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Optional outcome filter.",
                        "enum": ["win", "loss", "breakeven", "scratched"],
                    },
                    "include_rejected": {
                        "type": "boolean",
                        "description": "If true, include lessons Chris rejected. Defaults to false — rejected lessons are hidden from ranking.",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (1-20). Default 5. Hard-capped per NORTH_STAR P10.",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lesson",
            "description": (
                "Fetch a single lesson by id and return its full verbatim body (the "
                "entire post-mortem: thesis snapshot at open time, entry reasoning, "
                "journal retrospective, autoresearch eval window, news context at open, "
                "and your own structured analysis from when you wrote it). Call this "
                "after search_lessons when a ranked hit looks relevant and you need the "
                "full context, not just the summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Lesson id from search_lessons results.",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar",
            "description": (
                "Get upcoming calendar events: contract rollovers (WTI/Brent roll dates, "
                "blended oracle weights), macro events (OPEC, EIA, FOMC, NFP), and "
                "geopolitical deadlines. Returns events within the next N days."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "How many days ahead to look. Default 7.",
                        "default": 7,
                    },
                    "market": {
                        "type": "string",
                        "description": "Filter by market: 'oil', 'btc', 'macro', or 'all'. Default 'all'.",
                        "default": "all",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_research",
            "description": (
                "Read market research notes, including detailed contract rollover analysis, "
                "supply mechanics, convergence studies, and deep research. Use this when "
                "the user asks about HOW something works (e.g. 'how does WTI rollover work') "
                "or wants past research recalled."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "market": {
                        "type": "string",
                        "description": "Market slug: 'xyz_cl', 'xyz_brentoil', 'btc', 'xyz_gold', 'xyz_sp500'",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional keyword to filter notes (e.g. 'rollover', 'supply', 'convergence')",
                    },
                },
                "required": ["market"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_technicals",
            "description": (
                "Get current technical indicators for a market: RSI (1h/4h/1d), "
                "Bollinger Band position, EMA trend, ATR, and recent price action. "
                "Pre-computed from candle data — no LLM interpretation needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "market": {
                        "type": "string",
                        "description": "Market identifier, e.g. 'xyz:BRENTOIL', 'BTC', 'xyz:CL'",
                    },
                },
                "required": ["market"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════
# Tool Implementation
# ═══════════════════════════════════════════════════════════════════════

def _cap(text: str, limit: int = _MAX_RESPONSE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 30] + "\n...(truncated)"


def _hl_post(payload: dict) -> dict:
    try:
        return requests.post(_HL_API, json=payload, timeout=10).json()
    except Exception:
        return {}


def _tool_market_brief(args: dict) -> str:
    """Compact market brief using context harness."""
    market = args.get("market", "xyz:BRENTOIL")
    try:
        from common.account_state import fetch_registered_account_state
        from common.context_harness import build_thesis_context

        account_state = fetch_registered_account_state()

        # Fetch snapshot
        snapshot_text = None
        try:
            from modules.candle_cache import CandleCache
            from common.market_snapshot import build_snapshot, render_snapshot
            price_key = market
            mids = _hl_post({"type": "allMids"})
            mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
            mids.update(mids_xyz)
            price = float(mids.get(price_key, 0))
            if price:
                cache = CandleCache()
                snap = build_snapshot(market, cache, price)
                snapshot_text = render_snapshot(snap, detail="standard")
        except Exception:
            pass

        result = build_thesis_context(
            market=market,
            account_state=account_state,
            market_snapshot_text=snapshot_text,
            token_budget=1500,
        )
        return _cap(result.text)
    except Exception as e:
        return f"Error building market brief: {e}"


def _tool_account_summary(args: dict) -> str:
    """Account equity + positions from both clearinghouses."""
    from common.account_state import fetch_registered_account_state

    bundle = fetch_registered_account_state()
    if not bundle.get("accounts"):
        return "No wallet configured."

    lines = []
    total_equity = float(bundle.get("account", {}).get("total_equity", 0))
    for row in bundle.get("accounts", []):
        lines.append(
            f"  {row['label']}: ${row['total_equity']:,.2f} "
            f"(native ${row['native_equity']:,.2f} | xyz ${row['xyz_equity']:,.2f} | spot ${row['spot_usdc']:,.2f})"
        )
    for pos in bundle.get("positions", []):
        size = float(pos.get("size", 0))
        direction = "LONG" if size > 0 else "SHORT"
        entry = float(pos.get("entry", 0))
        upnl = float(pos.get("upnl", 0))
        lev_val = pos.get("leverage", "?")
        liq = pos.get("liq", "N/A")
        sign = "+" if upnl >= 0 else ""
        prefix = pos.get("account_label", pos.get("account_role", "Account"))
        lines.append(
            f"  {prefix} {pos.get('coin','?')} {direction} {abs(size):.1f} @ ${entry:,.2f} "
            f"| uPnL {sign}${upnl:,.2f} | {lev_val}x | liq ${float(liq):,.2f}"
            if liq and liq != "N/A" else
            f"  {prefix} {pos.get('coin','?')} {direction} {abs(size):.1f} @ ${entry:,.2f} "
            f"| uPnL {sign}${upnl:,.2f} | {lev_val}x"
        )

    header = f"ACCOUNT: ${total_equity:,.2f} equity"
    if lines:
        return header + "\nPOSITIONS:\n" + "\n".join(lines)
    return header + "\nNo open positions."


def _tool_live_price(args: dict) -> str:
    """Current prices from both clearinghouses."""
    target = args.get("market", "all").lower()
    mids = _hl_post({"type": "allMids"})
    mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
    mids.update(mids_xyz)

    if target != "all":
        # Try exact match then fuzzy
        for k, v in mids.items():
            if target in k.lower():
                return f"{k}: ${float(v):,.2f}"
        return f"No price found for '{target}'"

    from common.watchlist import get_watchlist_coins
    watchlist = get_watchlist_coins()
    lines = []
    for k in watchlist:
        if k in mids:
            lines.append(f"{k}: ${float(mids[k]):,.2f}")
    return "\n".join(lines) if lines else "No prices available."


def _tool_analyze_market(args: dict) -> str:
    """Deep technical analysis using market snapshot + signal interpretation."""
    coin = args.get("coin", "BTC")
    try:
        from modules.candle_cache import CandleCache
        from common.market_snapshot import build_snapshot, render_snapshot, render_signal_summary

        mids = _hl_post({"type": "allMids"})
        mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
        mids.update(mids_xyz)
        price = float(mids.get(coin, 0))
        if not price:
            return f"No price data for {coin}"

        cache = CandleCache()
        snap = build_snapshot(coin, cache, price)
        technicals = render_snapshot(snap, detail="full")
        signals = render_signal_summary(snap)
        return _cap(f"{technicals}\n{signals}")
    except Exception as e:
        return f"Analysis error: {e}"


def _tool_get_orders(args: dict) -> str:
    """Open orders from both clearinghouses."""
    from common.account_resolver import resolve_main_wallet
    main_addr = resolve_main_wallet(required=False)
    if not main_addr:
        return "No wallet configured."

    orders = []
    for dex in ['', 'xyz']:
        payload = {'type': 'openOrders', 'user': main_addr}
        if dex:
            payload['dex'] = dex
        orders.extend(_hl_post(payload) or [])

    if not orders:
        return "No open orders."

    lines = [f"{len(orders)} open orders:"]
    for o in orders[:15]:
        side = "BUY" if o.get("side") == "B" else "SELL"
        lines.append(f"  {side} {o.get('sz')} {o.get('coin')} @ ${o.get('limitPx')}")
    return "\n".join(lines)


def _tool_trade_journal(args: dict) -> str:
    """Recent trade journal entries from both trade files and journal JSONL.

    Hard-bounded per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11:
    the corpus may grow forever, but a single agent prompt sees at most
    25 trades, with each row's narrative fields truncated. The 12KB
    final _cap() in the tool dispatcher is the safety net; this is the
    primary cap.
    """
    # Hard ceiling: clamp the agent's requested limit. Default 10. Max 25.
    raw_limit = args.get("limit", 10)
    try:
        limit = max(1, min(25, int(raw_limit)))
    except (TypeError, ValueError):
        limit = 10

    trades = []

    # Source 1: Individual trade JSON files (already capped via slice)
    trades_path = _PROJECT_ROOT / "data" / "research" / "trades"
    if trades_path.exists():
        for f in sorted(trades_path.glob("*.json"), reverse=True)[:limit]:
            try:
                trades.append(json.loads(f.read_text()))
            except Exception:
                pass

    # Source 2: Journal JSONL (auto-logged by daemon on position close).
    # Streaming tail-read: only the last 5*limit lines are JSON-decoded so
    # an enormous historical journal doesn't get fully parsed every call.
    journal_path = _PROJECT_ROOT / "data" / "research" / "journal.jsonl"
    if journal_path.exists():
        try:
            from collections import deque
            tail = deque(maxlen=max(50, limit * 5))
            with journal_path.open("r") as fh:
                for line in fh:
                    tail.append(line)
            for line in tail:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass

    if not trades:
        return "No trade journal entries."

    # Deduplicate by trade_id, sort by close timestamp descending
    seen = set()
    unique = []
    for t in trades:
        tid = t.get("trade_id", id(t))
        if tid not in seen:
            seen.add(tid)
            unique.append(t)
    unique.sort(key=lambda t: t.get("timestamp_close", t.get("timestamp", "")), reverse=True)
    unique = unique[:limit]

    lines = [f"Last {len(unique)} trades:"]
    for t in unique:
        # Support both old format (coin/side/price) and new format (instrument/direction/entry_price/exit_price)
        coin = t.get("instrument", t.get("coin", "?")).replace("xyz:", "")
        direction = t.get("direction", t.get("side", "?"))
        entry = t.get("entry_price", t.get("price", "?"))
        exit_p = t.get("exit_price", "?")
        pnl = t.get("pnl", "?")
        roe = t.get("roe_pct", "")
        sl = t.get("stop_loss") or t.get("stop", "")
        tp = t.get("take_profit") or ""
        ts = t.get("timestamp_close", t.get("timestamp", "?"))[:10] if isinstance(t.get("timestamp_close", t.get("timestamp")), str) else "?"

        line = f"  {ts} {coin} {direction} size={t.get('size','?')} entry=${entry} exit=${exit_p} PnL=${pnl}"
        if roe:
            line += f" ({roe:+.1f}%)" if isinstance(roe, (int, float)) else f" ({roe}%)"
        if sl:
            line += f" SL=${sl}"
        if tp:
            line += f" TP=${tp}"
        lines.append(line)

    return "\n".join(lines)


def _tool_get_signals(args: dict) -> str:
    """Recent Pulse and Radar trade signals.

    Hard-bounded per NORTH_STAR P10 / Critical Rule 11: clamp limit
    at 50 (signals are smaller per-row than feedback/journal so the
    cap is more generous), streaming tail-read so a giant signals
    file doesn't get fully decoded every call.
    """
    # Hard ceiling: clamp the agent's requested limit. Default 20. Max 50.
    raw_limit = args.get("limit", 20)
    try:
        limit = max(1, min(50, int(raw_limit)))
    except (TypeError, ValueError):
        limit = 20

    source_filter = args.get("source", "all")
    signals_path = _PROJECT_ROOT / "data" / "research" / "signals.jsonl"

    if not signals_path.exists():
        return "No signals yet. Pulse and Radar scanners persist signals to data/research/signals.jsonl."

    # Streaming tail-read: bound memory regardless of file size.
    # Read 5*limit lines from the end so filtered output still has
    # enough rows to fill the limit.
    from collections import deque

    signals = []
    try:
        tail = deque(maxlen=max(100, limit * 5))
        with signals_path.open("r") as fh:
            for line in fh:
                tail.append(line)
        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
                if source_filter != "all" and s.get("source") != source_filter:
                    continue
                signals.append(s)
            except Exception:
                continue
    except OSError:
        return "Failed to read signals file."

    if not signals:
        return f"No {source_filter} signals found."

    signals = signals[-limit:]
    signals.reverse()

    lines = [f"Last {len(signals)} signals:"]
    for s in signals:
        src = s.get("source", "?").upper()
        asset = s.get("asset", "?")
        direction = s.get("direction", "?")
        ts = s.get("timestamp_human", "?")

        if src == "PULSE":
            tier = s.get("tier", "?")
            conf = s.get("confidence", 0)
            sig_type = s.get("signal_type", "")
            lines.append(f"  [{ts}] PULSE {asset} {direction} tier={tier} conf={conf:.0f}% ({sig_type})")
        elif src == "RADAR":
            score = s.get("score", 0)
            lines.append(f"  [{ts}] RADAR {asset} {direction} score={score:.0f}")
        else:
            lines.append(f"  [{ts}] {src} {asset} {direction}")

    return "\n".join(lines)


def _tool_check_funding(args: dict) -> str:
    """Funding rate, premium, OI for a market."""
    coin = args.get("coin", "BTC")
    # Normalize: strip xyz: for matching, but also try with it
    bare = coin.replace("xyz:", "") if coin.startswith("xyz:") else coin
    lookup_variants = {bare, f"xyz:{bare}", coin, coin.upper(), bare.upper()}

    for dex in ['', 'xyz']:
        payload: dict = {"type": "metaAndAssetCtxs"}
        if dex:
            payload["dex"] = dex
        data = _hl_post(payload)
        if isinstance(data, list) and len(data) >= 2:
            universe = data[0].get("universe", [])
            ctxs = data[1]
            for i, ctx in enumerate(ctxs):
                name = universe[i].get("name", "") if i < len(universe) else ""
                if name in lookup_variants or name.replace("xyz:", "") in lookup_variants:
                    funding = float(ctx.get("funding", 0))
                    oi = float(ctx.get("openInterest", 0))
                    vol = float(ctx.get("dayNtlVlm", 0))
                    mark = float(ctx.get("markPx", 0))
                    prev = float(ctx.get("prevDayPx", 0))
                    change = ((mark - prev) / prev * 100) if prev > 0 else 0

                    display = name.replace("xyz:", "") if name.startswith("xyz:") else name
                    lines = [f"{display} Market Data:"]
                    lines.append(f"  Price: ${mark:,.2f} ({change:+.1f}% 24h)")
                    lines.append(f"  Funding: {funding*100:.4f}%/h ({funding*100*24*365:.1f}% ann)")
                    lines.append(f"  OI: ${oi/1e6:.1f}M")
                    lines.append(f"  24h Volume: ${vol/1e6:.1f}M")
                    return "\n".join(lines)

    return f"No funding data for {coin}"


def _tool_place_trade(args: dict) -> str:
    """Execute a trade. Only called after user approval."""
    coin = args.get("coin", "")
    side = args.get("side", "")
    size = args.get("size", 0)

    try:
        from cli.hl_adapter import DirectHLProxy
        proxy = DirectHLProxy()

        # Normalise side: agent may say "long"/"buy"/"b" or "short"/"sell"/"s"
        norm_side = "buy" if side.lower() in ("buy", "long", "b") else "sell"
        # IOC market order: price=0.0 triggers snapshot+slippage path in adapter
        fill = proxy.place_order(
            instrument=coin,
            side=norm_side,
            size=float(size),
            price=0.0,
            tif="Ioc",
        )
        if fill is None:
            return f"Trade failed: no fill (order rejected or not matched) — {norm_side} {size} {coin}"
        # Audit F7-B: read-back verification — confirm position actually changed
        verification = _verify_position_after_trade(coin, norm_side, float(size))
        return (
            f"Trade executed: {norm_side.upper()} {fill.quantity} {fill.instrument} "
            f"@ {fill.price} (oid={fill.oid})\n{verification}"
        )
    except Exception as e:
        return f"Trade failed: {e}"


def _verify_position_after_trade(coin: str, side: str, size: float) -> str:
    """Read-back: confirm a trade actually moved the position. Audit F7-B."""
    try:
        from common.account_resolver import resolve_main_wallet
        addr = resolve_main_wallet(required=False)
        if not addr:
            return "VERIFY: skipped (no wallet)"
        bare = coin.replace("xyz:", "")
        for dex in ("", "xyz"):
            payload = {"type": "clearinghouseState", "user": addr}
            if dex:
                payload["dex"] = dex
            state = _hl_post(payload)
            for p in state.get("assetPositions", []):
                pos = p.get("position", {})
                pos_coin = pos.get("coin", "")
                if pos_coin == coin or pos_coin.replace("xyz:", "") == bare:
                    sz = float(pos.get("szi", 0))
                    direction = "LONG" if sz > 0 else "SHORT" if sz < 0 else "FLAT"
                    return f"VERIFY: {pos_coin} now {direction} {abs(sz)} (entry {pos.get('entryPx')})"
        return f"VERIFY: no position found for {coin} after trade — flat or fill missing"
    except Exception as e:
        return f"VERIFY: read-back failed: {e}"


def _tool_update_thesis(args: dict) -> str:
    """Update thesis file. Only called after user approval."""
    market = args.get("market", "")
    direction = args.get("direction", "flat")
    conviction = float(args.get("conviction", 0))
    summary = args.get("summary", "")

    try:
        thesis_dir = _PROJECT_ROOT / "data" / "thesis"
        thesis_dir.mkdir(parents=True, exist_ok=True)

        # Load or create thesis state
        safe_name = market.replace(":", "_").replace("/", "_")
        path = thesis_dir / f"{safe_name}_state.json"
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = {"market": market}

        data["direction"] = direction
        data["conviction"] = conviction
        if summary:
            data["thesis_summary"] = summary
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data["last_evaluation_ts"] = int(time.time() * 1000)

        path.write_text(json.dumps(data, indent=2) + "\n")
        # Audit F7-B: read-back verification — confirm file actually has new values
        try:
            verify = json.loads(path.read_text())
            if verify.get("direction") == direction and abs(float(verify.get("conviction", -1)) - conviction) < 1e-9:
                return f"Thesis updated: {market} {direction} conviction={conviction:.2f} (verified on disk)"
            return f"Thesis update VERIFICATION FAILED: wrote {direction}/{conviction} but disk has {verify.get('direction')}/{verify.get('conviction')}"
        except Exception as ve:
            return f"Thesis updated: {market} {direction} conviction={conviction:.2f} (verify read failed: {ve})"
    except Exception as e:
        return f"Thesis update failed: {e}"


def _tool_close_position(args: dict) -> str:
    """Close a position via market order. Only called after user approval."""
    coin = args.get("coin", "")
    side = args.get("side", "")
    size = args.get("size", 0)
    try:
        from cli.hl_adapter import DirectHLProxy
        proxy = DirectHLProxy()
        # The 'side' arg here is the closing side (opposite of position direction)
        norm_side = "buy" if side.lower() in ("buy", "long", "b") else "sell"
        fill = proxy.place_order(
            instrument=coin,
            side=norm_side,
            size=float(size),
            price=0.0,
            tif="Ioc",
        )
        if fill is None:
            return f"Close failed: no fill — {norm_side} {size} {coin}"
        # Audit F7-B: read-back verification
        verification = _verify_position_after_trade(coin, norm_side, float(size))
        return (
            f"Position closed: {norm_side.upper()} {fill.quantity} {fill.instrument} "
            f"@ {fill.price} (oid={fill.oid})\n{verification}"
        )
    except Exception as e:
        return f"Close failed: {e}"


def _tool_set_sl(args: dict) -> str:
    """Set a stop-loss trigger order. Only called after user approval."""
    coin = args.get("coin", "")
    side = args.get("side", "")
    size = args.get("size", 0)
    trigger_price = args.get("trigger_price", 0)
    try:
        from cli.hl_adapter import DirectHLProxy
        proxy = DirectHLProxy()
        oid = proxy.place_trigger_order(coin, side, float(size), float(trigger_price))
        if oid:
            return f"SL set: {coin} @ ${trigger_price:,.2f} (oid={oid})"
        return f"SL order placed but no OID returned for {coin} @ ${trigger_price:,.2f}"
    except Exception as e:
        return f"SL failed: {e}"


def _tool_set_tp(args: dict) -> str:
    """Set a take-profit trigger order. Only called after user approval."""
    coin = args.get("coin", "")
    side = args.get("side", "")
    size = args.get("size", 0)
    trigger_price = args.get("trigger_price", 0)
    try:
        from cli.hl_adapter import DirectHLProxy
        proxy = DirectHLProxy()
        oid = proxy.place_tp_trigger_order(coin, side, float(size), float(trigger_price))
        if oid:
            return f"TP set: {coin} @ ${trigger_price:,.2f} (oid={oid})"
        return f"TP order placed but no OID returned for {coin} @ ${trigger_price:,.2f}"
    except Exception as e:
        return f"TP failed: {e}"


def _tool_read_file(args: dict) -> str:
    from common.tools import read_file
    result = read_file(args.get("path", ""))
    if "error" in result:
        return result["error"]
    content = result.get("content", "")
    if len(content) > 10000:
        content = content[:10000] + "\n... (truncated)"
    return content

def _tool_search_code(args: dict) -> str:
    from common.tools import search_code
    result = search_code(args.get("pattern", ""), args.get("path", "."))
    if "error" in result:
        return result["error"]
    matches = result.get("matches", [])
    return f"{result['count']} matches:\n" + "\n".join(matches)

def _tool_list_files(args: dict) -> str:
    from common.tools import list_files
    result = list_files(args.get("pattern", ""))
    if "error" in result:
        return result["error"]
    files = result.get("files", [])
    return f"{result['count']} files:\n" + "\n".join(files)

def _tool_web_search(args: dict) -> str:
    from common.tools import web_search
    result = web_search(args.get("query", ""), args.get("max_results", 5))
    if "error" in result:
        return result["error"]
    lines = []
    for r in result.get("results", []):
        lines.append(f"• {r['title']}\n  {r['url']}\n  {r['snippet']}")
    return "\n\n".join(lines) if lines else "No results found."

def _tool_memory_read(args: dict) -> str:
    from common.tools import memory_read
    result = memory_read(args.get("topic", "index"))
    if "error" in result:
        return result["error"]
    return result.get("content", "")

def _tool_memory_write(args: dict) -> str:
    from common.tools import memory_write
    result = memory_write(args.get("topic", ""), args.get("content", ""))
    if "error" in result:
        return result["error"]
    return f"Memory saved: {result['topic']}.md (index updated)"

def _tool_edit_file(args: dict) -> str:
    from common.tools import edit_file
    result = edit_file(args.get("path", ""), args.get("old_str", ""), args.get("new_str", ""))
    if "error" in result:
        return result["error"]
    return f"Edited {result['path']} ({result['replacements']} replacement)"

def _tool_run_bash(args: dict) -> str:
    from common.tools import run_bash
    result = run_bash(args.get("command", ""))
    if "error" in result:
        return result["error"]
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"])
    if result.get("stderr"):
        parts.append(f"STDERR: {result['stderr']}")
    parts.append(f"(exit {result['returncode']})")
    return "\n".join(parts)


def _tool_get_errors(args: dict) -> str:
    from common.tools import get_errors
    result = get_errors(args.get("limit", 10))
    if "error" in result:
        return result["error"]
    errors = result.get("errors", [])
    if not errors:
        return "No recent errors."
    lines = []
    for e in errors:
        lines.append(f"[{e['time']}] {e['event']}: {e['details']}")
    return f"{result['count']} recent errors:\n" + "\n".join(lines)

def _tool_get_feedback(args: dict) -> str:
    """Read recent /feedback entries.

    Hard-bounded per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11:
    the corpus may grow forever, but a single agent prompt sees at most
    25 entries with each entry's text capped. The 12KB final _cap() in
    the tool dispatcher is the safety net; this is the primary cap.
    """
    from common.tools import get_feedback

    # Hard ceiling: clamp the agent's requested limit. Default 10. Max 25.
    raw_limit = args.get("limit", 10)
    try:
        limit = max(1, min(25, int(raw_limit)))
    except (TypeError, ValueError):
        limit = 10

    result = get_feedback(limit)
    if "error" in result:
        return result["error"]
    feedback = result.get("feedback", [])
    if not feedback:
        return "No feedback recorded."
    lines = []
    for f in feedback:
        # Per-row truncation — a /feedback entry can be a pasted article.
        text = f.get("text") or ""
        if len(text) > 500:
            text = text[:497] + "..."
        lines.append(f"[{f['time']}] {text}")
    return f"{result['count']} feedback entries (showing {len(lines)}):\n" + "\n".join(lines)


def _tool_introspect_self(args: dict) -> str:
    """Live snapshot of the agent's own state. Audit F1.

    Pulls from the running system rather than from prompt-loaded knowledge,
    so the agent can answer 'what tools do I have / what markets am I
    approved on / what positions are open' from reality.
    """
    lines: List[str] = []

    # Active model
    try:
        from cli.telegram_agent import _get_active_model
        lines.append(f"ACTIVE MODEL: {_get_active_model()}")
    except Exception as e:
        lines.append(f"ACTIVE MODEL: <unavailable: {e}>")

    # Tools available (introspect from this module)
    tool_names = sorted(t["function"]["name"] for t in TOOL_DEFS)
    write_set = WRITE_TOOLS
    lines.append(f"TOOLS ({len(tool_names)}):")
    for n in tool_names:
        marker = " [WRITE — needs approval]" if n in write_set else ""
        lines.append(f"  - {n}{marker}")

    # Approved markets (watchlist)
    try:
        from common.watchlist import load_watchlist
        wl = load_watchlist()
        names = ", ".join(m.get("display") or m.get("coin", "?") for m in wl)
        lines.append(f"WATCHLIST ({len(wl)}): {names}")
    except Exception as e:
        lines.append(f"WATCHLIST: <unavailable: {e}>")

    # Open positions (both venues)
    try:
        from common.account_resolver import resolve_main_wallet
        addr = resolve_main_wallet(required=False)
        positions: List[str] = []
        if addr:
            for dex in ("", "xyz"):
                payload = {"type": "clearinghouseState", "user": addr}
                if dex:
                    payload["dex"] = dex
                state = _hl_post(payload)
                for p in state.get("assetPositions", []):
                    pos = p.get("position", {})
                    sz = float(pos.get("szi", 0))
                    if sz == 0:
                        continue
                    side = "LONG" if sz > 0 else "SHORT"
                    coin = pos.get("coin", "?")
                    entry = float(pos.get("entryPx", 0))
                    upnl = float(pos.get("unrealizedPnl", 0))
                    lev = (pos.get("leverage") or {}).get("value", "?") if isinstance(pos.get("leverage"), dict) else "?"
                    positions.append(f"  {coin} {side} {abs(sz)} @ {entry} | uPnL {upnl:+.2f} | {lev}x")
        if positions:
            lines.append(f"OPEN POSITIONS ({len(positions)}):")
            lines.extend(positions)
        else:
            lines.append("OPEN POSITIONS: none")
    except Exception as e:
        lines.append(f"OPEN POSITIONS: <unavailable: {e}>")

    # Thesis files + ages
    try:
        thesis_dir = _PROJECT_ROOT / "data" / "thesis"
        if thesis_dir.exists():
            now = time.time()
            entries = []
            for f in sorted(thesis_dir.glob("*.json")):
                age_h = (now - f.stat().st_mtime) / 3600
                entries.append(f"  {f.stem} ({age_h:.1f}h old)")
            if entries:
                lines.append(f"THESIS FILES ({len(entries)}):")
                lines.extend(entries)
            else:
                lines.append("THESIS FILES: none")
    except Exception as e:
        lines.append(f"THESIS FILES: <unavailable: {e}>")

    # Memory state
    try:
        mem_dir = _PROJECT_ROOT / "data" / "agent_memory"
        if mem_dir.exists():
            topics = sorted(f.stem for f in mem_dir.glob("*.md") if f.name != "MEMORY.md")
            lines.append(f"MEMORY TOPICS ({len(topics)}): {', '.join(topics) or '(none)'}")
            dream = mem_dir / "dream_consolidation.md"
            if dream.exists():
                age_h = (time.time() - dream.stat().st_mtime) / 3600
                lines.append(f"LAST DREAM CONSOLIDATION: {age_h:.1f}h ago")
    except Exception as e:
        lines.append(f"MEMORY: <unavailable: {e}>")

    # Daemon health
    try:
        pid_file = _PROJECT_ROOT / "data" / "daemon" / "daemon.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            import os
            try:
                os.kill(pid, 0)
                lines.append(f"DAEMON: running (pid {pid})")
            except ProcessLookupError:
                lines.append(f"DAEMON: STALE PID {pid} — not running")
        else:
            lines.append("DAEMON: no pid file")
    except Exception as e:
        lines.append(f"DAEMON: <unavailable: {e}>")

    return "\n".join(lines)


def _tool_read_reference(args: dict) -> str:
    """Read a built-in reference doc. Audit F1."""
    topic = args.get("topic", "")
    allowed = {"tools", "architecture", "workflows", "rules"}
    if topic not in allowed:
        return f"Unknown topic '{topic}'. Allowed: {', '.join(sorted(allowed))}"
    path = _PROJECT_ROOT / "agent" / "reference" / f"{topic}.md"
    if not path.exists():
        return f"Reference doc not found: agent/reference/{topic}.md"
    return _cap(path.read_text())


def _format_holding(holding_ms: int) -> str:
    """Render holding time as a compact human string."""
    if holding_ms <= 0:
        return "0m"
    minutes = holding_ms // 60_000
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours/24:.1f}d"


def _tool_search_lessons(args: dict) -> str:
    """BM25-ranked search over the trade lesson corpus. See TOOL_DEFS entry.

    Hard-bounded per NORTH_STAR P10 / Critical Rule 11: clamp limit at 20.
    Lesson summaries are short (~150 chars each), but a 20-row response
    is already ~3KB which is the right ceiling for prompt injection.
    """
    from common import memory as common_memory

    # Hard ceiling: clamp the agent's requested limit. Default 5. Max 20.
    raw_limit = args.get("limit", 5) or 5
    try:
        limit = max(1, min(20, int(raw_limit)))
    except (TypeError, ValueError):
        limit = 5

    try:
        # Read _DB_PATH dynamically at call time so tests can monkeypatch it.
        # The default-arg binding on search_lessons captures _DB_PATH at function
        # definition time, so passing it explicitly here is the only reliable way.
        rows = common_memory.search_lessons(
            query=args.get("query", "") or "",
            market=args.get("market") or None,
            direction=args.get("direction") or None,
            signal_source=args.get("signal_source") or None,
            lesson_type=args.get("lesson_type") or None,
            outcome=args.get("outcome") or None,
            include_rejected=bool(args.get("include_rejected", False)),
            limit=limit,
            db_path=common_memory._DB_PATH,
        )
    except Exception as e:
        return f"Lesson search failed: {e}"

    if not rows:
        return "No lessons found for that query/filter combination."

    lines = [f"Found {len(rows)} lesson(s):"]
    for r in rows:
        lesson_id = r.get("id")
        market = r.get("market", "?")
        direction = r.get("direction", "?")
        outcome = r.get("outcome", "?")
        roe = r.get("roe_pct", 0.0)
        closed = (r.get("trade_closed_at") or "")[:10]
        signal = r.get("signal_source", "?")
        ltype = r.get("lesson_type", "?")
        summary = r.get("summary", "").strip()
        reviewed = r.get("reviewed_by_chris", 0)
        review_flag = " [approved]" if reviewed == 1 else (" [rejected]" if reviewed == -1 else "")
        lines.append(
            f"\n#{lesson_id} {closed} {market} {direction} ({signal}, {ltype}) "
            f"→ {outcome} {roe:+.1f}%{review_flag}\n  {summary}"
        )
    lines.append("\nUse get_lesson(id) to read the verbatim body.")
    return "\n".join(lines)


def _tool_get_lesson(args: dict) -> str:
    """Fetch one lesson by id and render its full verbatim body."""
    from common import memory as common_memory

    raw_id = args.get("id")
    if raw_id is None:
        return "get_lesson requires 'id' argument"
    try:
        lesson_id = int(raw_id)
    except (TypeError, ValueError):
        return f"get_lesson id must be an integer, got {raw_id!r}"

    try:
        # Dynamic _DB_PATH read — same reason as _tool_search_lessons.
        row = common_memory.get_lesson(lesson_id, db_path=common_memory._DB_PATH)
    except Exception as e:
        return f"get_lesson failed: {e}"

    if row is None:
        return f"Lesson #{lesson_id} not found."

    # Tags come back from SQLite as a JSON string.
    tags_raw = row.get("tags", "[]") or "[]"
    try:
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else list(tags_raw)
    except (ValueError, TypeError):
        tags = []

    reviewed = row.get("reviewed_by_chris", 0)
    review_flag = "approved" if reviewed == 1 else ("rejected" if reviewed == -1 else "unreviewed")

    header_lines = [
        f"# Lesson #{row.get('id')}",
        f"**Trade closed:** {row.get('trade_closed_at', '?')}",
        f"**Market:** {row.get('market', '?')} {row.get('direction', '?')}",
        f"**Signal source:** {row.get('signal_source', '?')}",
        f"**Lesson type:** {row.get('lesson_type', '?')}",
        f"**Outcome:** {row.get('outcome', '?')} "
        f"(PnL ${row.get('pnl_usd', 0):+.2f}, ROE {row.get('roe_pct', 0):+.2f}%, "
        f"held {_format_holding(int(row.get('holding_ms') or 0))})",
    ]
    conviction = row.get("conviction_at_open")
    if conviction is not None:
        header_lines.append(f"**Conviction at open:** {conviction:.2f}")
    journal_id = row.get("journal_entry_id")
    if journal_id:
        header_lines.append(f"**Journal entry:** {journal_id}")
    thesis_path = row.get("thesis_snapshot_path")
    if thesis_path:
        header_lines.append(f"**Thesis snapshot:** {thesis_path}")
    if tags:
        header_lines.append(f"**Tags:** {', '.join(tags)}")
    header_lines.append(f"**Review status:** {review_flag}")
    header_lines.append("")
    header_lines.append(f"**Summary:** {row.get('summary', '').strip()}")
    header_lines.append("")
    header_lines.append("## Verbatim body")
    header_lines.append("")
    # Per NORTH_STAR P10 / Critical Rule 11: cap body_full at 6000 chars
    # before joining. The lesson engine spec says ~5KB; an agent-authored
    # lesson can technically be any size. The 12KB final _cap() in the
    # dispatcher is the safety net but a single lesson would consume the
    # entire tool result budget. 6000 chars is generous (~1500 tokens)
    # for any reasonable post-mortem and matches cmd_lesson's Telegram
    # render which also caps at 3000.
    body = (row.get("body_full") or "").strip()
    if len(body) > 6000:
        body = body[:6000] + "\n\n[... TRUNCATED at 6KB cap per NORTH_STAR P10. Use /lesson <id> for the full body.]"
    header_lines.append(body)

    return "\n".join(header_lines)


def _tool_get_calendar(args: dict) -> str:
    """Surface upcoming calendar events from all calendar JSON files."""
    from datetime import datetime, timedelta, timezone

    days_ahead = min(max(1, args.get("days_ahead", 7)), 90)
    market_filter = args.get("market", "all").lower()
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days_ahead)

    calendar_dir = _PROJECT_ROOT / "data" / "calendar"
    if not calendar_dir.exists():
        return "No calendar data directory found."

    events = []

    # 1. Load brent/WTI rollover calendars
    for rollfile in ["brent_rollover.json"]:
        path = calendar_dir / rollfile
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for entry in data.get("brent_futures", []):
                    ltd = entry.get("last_trading")
                    if ltd:
                        try:
                            dt = datetime.fromisoformat(ltd).replace(tzinfo=timezone.utc)
                            if now - timedelta(days=1) <= dt <= cutoff:
                                days_until = (dt - now).days
                                events.append({
                                    "date": ltd,
                                    "days_until": days_until,
                                    "name": f"BRENT Roll — {entry.get('contract', '?')} last trading",
                                    "impact": "high",
                                    "market": "oil",
                                    "details": f"Delivery month: {entry.get('delivery_month', '?')}",
                                })
                        except ValueError:
                            pass
            except Exception:
                pass

    # 2. Load quarterly/annual/weekly events
    for calfile in ["quarterly.json", "annual.json"]:
        path = calendar_dir / calfile
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            for ev in data.get("events", []):
                date_str = ev.get("date")
                if not date_str:
                    continue
                try:
                    dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
                    if now - timedelta(days=1) <= dt <= cutoff:
                        mkt = ev.get("market", "macro")
                        if market_filter != "all" and market_filter != mkt:
                            continue
                        days_until = (dt - now).days
                        events.append({
                            "date": date_str,
                            "days_until": days_until,
                            "name": ev.get("name", "?"),
                            "impact": ev.get("impact", "?"),
                            "market": mkt,
                            "details": ev.get("notes", ""),
                        })
                except ValueError:
                    pass
        except Exception:
            pass

    # 3. Load weekly template for today's day
    weekly_path = calendar_dir / "weekly_template.json"
    if weekly_path.exists():
        try:
            weekly = json.loads(weekly_path.read_text())
            today_name = now.strftime("%A").lower()
            if today_name in weekly:
                day_info = weekly[today_name]
                events.append({
                    "date": now.strftime("%Y-%m-%d"),
                    "days_until": 0,
                    "name": f"TODAY ({today_name.title()})",
                    "impact": "info",
                    "market": "macro",
                    "details": f"Volume: {day_info.get('volume_norm', '?')}. {day_info.get('notes', '')}",
                })
        except Exception:
            pass

    if not events:
        return f"No calendar events in the next {days_ahead} days."

    events.sort(key=lambda e: e.get("date", ""))
    lines = [f"📅 Calendar — next {days_ahead} days ({len(events)} events):"]
    for ev in events:
        d = ev["days_until"]
        when = "TODAY" if d <= 0 else f"in {d}d"
        lines.append(f"  [{ev['date']}] ({when}) [{ev['impact'].upper()}] {ev['name']}")
        if ev.get("details"):
            lines.append(f"    {ev['details'][:200]}")

    return "\n".join(lines)


def _tool_get_research(args: dict) -> str:
    """Read market research notes from the data/research/markets/ directory."""
    market = args.get("market", "").lower().replace(":", "_").replace("-", "_")
    query = args.get("query", "").lower()

    research_dir = _PROJECT_ROOT / "data" / "research" / "markets" / market
    if not research_dir.exists():
        # Try common aliases
        aliases = {
            "wti": "xyz_cl", "cl": "xyz_cl", "oil": "xyz_brentoil",
            "brent": "xyz_brentoil", "brentoil": "xyz_brentoil",
            "gold": "xyz_gold", "silver": "xyz_silver", "sp500": "xyz_sp500",
        }
        market = aliases.get(market, market)
        research_dir = _PROJECT_ROOT / "data" / "research" / "markets" / market
        if not research_dir.exists():
            return f"No research directory for market '{market}'. Available: {[d.name for d in (_PROJECT_ROOT / 'data' / 'research' / 'markets').iterdir() if d.is_dir()]}"

    # Collect all .md files from the market directory
    notes = []
    for md_file in sorted(research_dir.rglob("*.md")):
        rel = md_file.relative_to(research_dir)
        if query:
            # Flexible match: check if query or any 3+ char substring appears in filename or content
            filename_lower = str(rel).lower()
            content_preview = md_file.read_text()[:1000].lower()
            search_text = filename_lower + " " + content_preview
            # Match if query appears OR if query stem (first 4 chars) appears
            query_stem = query[:4] if len(query) > 4 else query
            if query not in search_text and query_stem not in search_text:
                continue
        notes.append((str(rel), md_file))

    if not notes:
        return f"No research notes matching '{query}' for {market}."

    # Build output — read each note (capped)
    lines = [f"📚 Research for {market} ({len(notes)} notes):"]
    total_chars = 0
    for rel_path, file_path in notes:
        content = file_path.read_text()
        if total_chars + len(content) > _MAX_RESPONSE_CHARS:
            remaining = _MAX_RESPONSE_CHARS - total_chars
            if remaining > 200:
                lines.append(f"\n--- {rel_path} ---")
                lines.append(content[:remaining] + "\n[...TRUNCATED]")
            else:
                lines.append(f"\n[{len(notes) - notes.index((rel_path, file_path))} more notes not shown — narrow with query param]")
            break
        lines.append(f"\n--- {rel_path} ---")
        lines.append(content)
        total_chars += len(content)

    return "\n".join(lines)


def _tool_get_technicals(args: dict) -> str:
    """Get current technical indicators for a market from candle data."""
    market = args.get("market", "BTC")

    try:
        from modules.candle_cache import CandleCache
        from common.market_snapshot import build_snapshot, render_snapshot
        import requests as req

        cache = CandleCache()

        # Get current price
        price = 0.0
        for dex_flag in [None, "xyz"]:
            payload: dict = {"type": "allMids"}
            if dex_flag:
                payload["dex"] = dex_flag
            r = req.post("https://api.hyperliquid.xyz/info", json=payload, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if market in data:
                    price = float(data[market])
                    break

        if not price:
            return f"Could not fetch current price for {market}."

        snap = build_snapshot(market, cache, price)
        text = render_snapshot(snap, detail="full")
        return text

    except Exception as e:
        return f"Technicals unavailable for {market}: {e}"


# Dispatch table
_TOOL_DISPATCH = {
    "market_brief": _tool_market_brief,
    "account_summary": _tool_account_summary,
    "live_price": _tool_live_price,
    "analyze_market": _tool_analyze_market,
    "get_orders": _tool_get_orders,
    "trade_journal": _tool_trade_journal,
    "get_signals": _tool_get_signals,
    "check_funding": _tool_check_funding,
    "place_trade": _tool_place_trade,
    "update_thesis": _tool_update_thesis,
    "close_position": _tool_close_position,
    "set_sl": _tool_set_sl,
    "set_tp": _tool_set_tp,
    "read_file": _tool_read_file,
    "search_code": _tool_search_code,
    "list_files": _tool_list_files,
    "web_search": _tool_web_search,
    "memory_read": _tool_memory_read,
    "memory_write": _tool_memory_write,
    "edit_file": _tool_edit_file,
    "run_bash": _tool_run_bash,
    "get_errors": _tool_get_errors,
    "get_feedback": _tool_get_feedback,
    "introspect_self": _tool_introspect_self,
    "read_reference": _tool_read_reference,
    "search_lessons": _tool_search_lessons,
    "get_lesson": _tool_get_lesson,
    "get_calendar": _tool_get_calendar,
    "get_research": _tool_get_research,
    "get_technicals": _tool_get_technicals,
}


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool and return capped result string."""
    fn = _TOOL_DISPATCH.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    t0 = time.time()
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        result = fn(args)
        duration_ms = int((time.time() - t0) * 1000)
        log.info("Tool %s executed (%dms): %s", name, duration_ms, str(result)[:100])
        # Log to diagnostics for /diag tool call counting
        try:
            from common.diagnostics import get_diagnostics
            get_diagnostics().log_tool_call(name, args, str(result)[:200], duration_ms=duration_ms)
        except Exception:
            pass
        return _cap(result)
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        log.error("Tool %s failed (%dms): %s", name, duration_ms, e)
        try:
            from common.diagnostics import get_diagnostics
            get_diagnostics().log_tool_call(name, arguments, str(e), duration_ms=duration_ms, error=True)
        except Exception:
            pass
        return f"Tool error ({name}): {e}"


def is_write_tool(name: str) -> bool:
    """Check if a tool requires user approval."""
    return name in WRITE_TOOLS


def store_pending(tool: str, arguments: dict, chat_id: str) -> str:
    """Store a pending write action. Returns action_id.

    Persists to disk so approvals survive bot restarts.
    """
    action_id = uuid.uuid4().hex[:8]
    _pending_actions[action_id] = {
        "tool": tool,
        "arguments": arguments,
        "chat_id": chat_id,
        "ts": time.time(),
    }
    _persist_pending()
    return action_id


def pop_pending(action_id: str) -> Optional[dict]:
    """Retrieve and remove a pending action. Returns None if expired or missing."""
    action = _pending_actions.pop(action_id, None)
    if action is not None:
        _persist_pending()
    if action is None:
        return None
    # 5 minute TTL
    if time.time() - action["ts"] > 300:
        return None
    return action


def format_confirmation(tool: str, arguments: dict, action_id: str) -> Tuple[str, list]:
    """Build Telegram confirmation message and buttons for a write tool."""
    if tool == "place_trade":
        side = arguments.get("side", "?").upper()
        size = arguments.get("size", "?")
        coin = arguments.get("coin", "?")
        text = f"⚠️ *Confirm Trade*\n\n{side} {size} {coin}\n\nApprove or reject:"
    elif tool == "update_thesis":
        market = arguments.get("market", "?")
        direction = arguments.get("direction", "?")
        conv = arguments.get("conviction", "?")
        text = f"⚠️ *Confirm Thesis Update*\n\n{market} → {direction} conviction={conv}\n\nApprove or reject:"
    elif tool == "close_position":
        side = arguments.get("side", "?").upper()
        size = arguments.get("size", "?")
        coin = arguments.get("coin", "?")
        text = f"⚠️ *Close Position*\n\n{side} {size} {coin}\n\nApprove or reject:"
    elif tool == "set_sl":
        coin = arguments.get("coin", "?")
        price = arguments.get("trigger_price", "?")
        text = f"🛡 *Set Stop-Loss*\n\n{coin} @ ${price}\n\nApprove or reject:"
    elif tool == "set_tp":
        coin = arguments.get("coin", "?")
        price = arguments.get("trigger_price", "?")
        text = f"🎯 *Set Take-Profit*\n\n{coin} @ ${price}\n\nApprove or reject:"
    else:
        text = f"⚠️ *Confirm Action*\n\n{tool}: {json.dumps(arguments)[:200]}\n\nApprove or reject:"

    buttons = [
        {"text": "✅ Approve", "callback_data": f"approve:{action_id}"},
        {"text": "❌ Reject", "callback_data": f"reject:{action_id}"},
    ]
    return text, buttons


# ═══════════════════════════════════════════════════════════════════════
# Pending Action Maintenance (Nautilus-inspired cleanup)
# ═══════════════════════════════════════════════════════════════════════

_PENDING_TTL = 300  # 5 minutes


def cleanup_expired_pending() -> int:
    """Remove expired pending actions. Returns count removed.

    Called periodically from the polling loop to prevent memory accumulation.
    Passivbot-inspired: proactive cleanup, not just lazy expiry on retrieval.
    """
    now = time.time()
    expired = [k for k, v in _pending_actions.items() if now - v["ts"] > _PENDING_TTL]
    for k in expired:
        _pending_actions.pop(k, None)
    if expired:
        _persist_pending()
        log.info("Cleaned up %d expired pending actions", len(expired))
    return len(expired)


def pending_count() -> int:
    """Number of pending actions (including potentially expired)."""
    return len(_pending_actions)


def pending_summary() -> list:
    """Return summary of all pending actions for /health diagnostics."""
    now = time.time()
    return [
        {
            "id": k,
            "tool": v["tool"],
            "age_s": int(now - v["ts"]),
            "expired": now - v["ts"] > _PENDING_TTL,
        }
        for k, v in _pending_actions.items()
    ]
