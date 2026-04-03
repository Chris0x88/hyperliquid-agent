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
_MAX_RESPONSE_CHARS = 3000

# Write tools that require user approval before execution
WRITE_TOOLS = {"place_trade", "update_thesis"}

# In-memory pending actions (action_id -> action dict). TTL 5 min.
_pending_actions: Dict[str, dict] = {}


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
            "description": "Get recent trade history and journal entries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return",
                        "default": 10,
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
        from common.context_harness import build_thesis_context
        from common.account_resolver import resolve_main_wallet

        # Fetch account state
        main_addr = resolve_main_wallet(required=False)
        account_state = {"account": {"total_equity": 0}, "alerts": [], "escalation": "L0"}
        if main_addr:
            for dex in ['', 'xyz']:
                payload = {"type": "clearinghouseState", "user": main_addr}
                if dex:
                    payload["dex"] = dex
                state = _hl_post(payload)
                account_state["account"]["total_equity"] += float(
                    state.get("marginSummary", {}).get("accountValue", 0)
                )

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
    from common.account_resolver import resolve_main_wallet
    main_addr = resolve_main_wallet(required=False)
    if not main_addr:
        return "No wallet configured."

    lines = []
    total_equity = 0.0

    for dex_label, dex in [("Native", ""), ("xyz", "xyz")]:
        payload = {"type": "clearinghouseState", "user": main_addr}
        if dex:
            payload["dex"] = dex
        state = _hl_post(payload)
        eq = float(state.get("marginSummary", {}).get("accountValue", 0))
        total_equity += eq

        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            size = float(pos.get("szi", 0))
            if size == 0:
                continue
            direction = "LONG" if size > 0 else "SHORT"
            entry = float(pos.get("entryPx", 0))
            upnl = float(pos.get("unrealizedPnl", 0))
            lev = pos.get("leverage", {})
            lev_val = lev.get("value", "?") if isinstance(lev, dict) else lev
            liq = pos.get("liquidationPx", "N/A")
            sign = "+" if upnl >= 0 else ""
            lines.append(
                f"  {pos.get('coin','?')} {direction} {abs(size):.1f} @ ${entry:,.2f} "
                f"| uPnL {sign}${upnl:,.2f} | {lev_val}x | liq ${float(liq):,.2f}"
                if liq and liq != "N/A" else
                f"  {pos.get('coin','?')} {direction} {abs(size):.1f} @ ${entry:,.2f} "
                f"| uPnL {sign}${upnl:,.2f} | {lev_val}x"
            )

    # Spot
    spot = _hl_post({"type": "spotClearinghouseState", "user": main_addr})
    for b in spot.get("balances", []):
        total = float(b.get("total", 0))
        if total > 0.01:
            lines.append(f"  Spot {b.get('coin')}: {total:.2f}")
            if b.get("coin") == "USDC":
                total_equity += total

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

    watchlist = ["BTC", "ETH", "xyz:BRENTOIL", "xyz:CL", "xyz:GOLD", "xyz:SILVER", "xyz:NATGAS"]
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
    """Recent trade journal entries."""
    limit = args.get("limit", 10)
    trades_path = _PROJECT_ROOT / "data" / "research" / "trades"
    if not trades_path.exists():
        return "No trade journal entries."

    files = sorted(trades_path.glob("*.json"), reverse=True)[:limit]
    if not files:
        return "No trade journal entries."

    lines = [f"Last {len(files)} trades:"]
    for f in files:
        try:
            t = json.loads(f.read_text())
            lines.append(
                f"  {t.get('timestamp', f.stem)[:10]} {t.get('coin','?')} "
                f"{t.get('side','?')} {t.get('size','?')} @ ${t.get('price','?')} "
                f"PnL: {t.get('pnl', '?')}"
            )
        except Exception:
            pass
    return "\n".join(lines) if len(lines) > 1 else "No readable trade entries."


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

        is_buy = side.lower() in ("buy", "long", "b")
        result = proxy.market_order(
            coin=coin,
            is_buy=is_buy,
            sz=float(size),
        )
        return f"Trade executed: {side.upper()} {size} {coin}\nResult: {result}"
    except Exception as e:
        return f"Trade failed: {e}"


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
        return f"Thesis updated: {market} {direction} conviction={conviction:.2f}"
    except Exception as e:
        return f"Thesis update failed: {e}"


# Dispatch table
_TOOL_DISPATCH = {
    "market_brief": _tool_market_brief,
    "account_summary": _tool_account_summary,
    "live_price": _tool_live_price,
    "analyze_market": _tool_analyze_market,
    "get_orders": _tool_get_orders,
    "trade_journal": _tool_trade_journal,
    "check_funding": _tool_check_funding,
    "place_trade": _tool_place_trade,
    "update_thesis": _tool_update_thesis,
}


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool and return capped result string."""
    fn = _TOOL_DISPATCH.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        result = fn(args)
        log.info("Tool %s executed: %s", name, str(result)[:100])
        return _cap(result)
    except Exception as e:
        log.error("Tool %s failed: %s", name, e)
        return f"Tool error ({name}): {e}"


def is_write_tool(name: str) -> bool:
    """Check if a tool requires user approval."""
    return name in WRITE_TOOLS


def store_pending(tool: str, arguments: dict, chat_id: str) -> str:
    """Store a pending write action. Returns action_id."""
    action_id = uuid.uuid4().hex[:8]
    _pending_actions[action_id] = {
        "tool": tool,
        "arguments": arguments,
        "chat_id": chat_id,
        "ts": time.time(),
    }
    return action_id


def pop_pending(action_id: str) -> Optional[dict]:
    """Retrieve and remove a pending action. Returns None if expired or missing."""
    action = _pending_actions.pop(action_id, None)
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
    else:
        text = f"⚠️ *Confirm Action*\n\n{tool}: {json.dumps(arguments)[:200]}\n\nApprove or reject:"

    buttons = [
        {"text": "✅ Approve", "callback_data": f"approve:{action_id}"},
        {"text": "❌ Reject", "callback_data": f"reject:{action_id}"},
    ]
    return text, buttons
