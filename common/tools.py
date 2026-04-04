"""Unified tool core — pure functions returning dicts.

Single source of truth for all tool logic. Consumed by:
- AI agent (via code_tool_parser → tool_renderers.render_for_ai)
- Telegram commands (via tool_renderers.render_for_telegram) [future]
- agent_tools.py (thin wrappers for backward compat)

Every function returns a dict. No formatting, no Telegram, no AI concerns.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("tools")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HL_API = "https://api.hyperliquid.xyz/info"


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _hl_post(payload: dict) -> Any:
    try:
        return requests.post(_HL_API, json=payload, timeout=10).json()
    except Exception:
        return {}


def _resolve_main_wallet() -> Optional[str]:
    from common.account_resolver import resolve_main_wallet
    return resolve_main_wallet(required=False)


def _coin_matches(universe_name: str, target: str) -> bool:
    """Handle xyz: prefix normalization for coin matching."""
    bare_uni = universe_name.replace("xyz:", "") if universe_name.startswith("xyz:") else universe_name
    bare_tgt = target.replace("xyz:", "") if target.startswith("xyz:") else target
    return bare_uni.upper() == bare_tgt.upper()


# ═══════════════════════════════════════════════════════════════════════
# READ Tools
# ═══════════════════════════════════════════════════════════════════════

def status() -> dict:
    """Account equity, open positions with entry/uPnL/leverage/liq, spot balances."""
    addr = _resolve_main_wallet()
    if not addr:
        return {"error": "No wallet configured"}

    total_equity = 0.0
    positions = []

    for dex_label, dex in [("native", ""), ("xyz", "xyz")]:
        payload: dict = {"type": "clearinghouseState", "user": addr}
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
            lev = pos.get("leverage", {})
            lev_val = lev.get("value", "?") if isinstance(lev, dict) else lev
            liq = pos.get("liquidationPx")
            positions.append({
                "coin": pos.get("coin", "?"),
                "direction": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_px": float(pos.get("entryPx", 0)),
                "upnl": float(pos.get("unrealizedPnl", 0)),
                "leverage": lev_val,
                "liquidation_px": float(liq) if liq and liq != "N/A" else None,
                "dex": dex_label,
            })

    # Spot balances
    spot_balances = []
    spot = _hl_post({"type": "spotClearinghouseState", "user": addr})
    for b in spot.get("balances", []):
        total = float(b.get("total", 0))
        if total > 0.01:
            spot_balances.append({"coin": b.get("coin"), "total": total})
            if b.get("coin") == "USDC":
                total_equity += total

    return {
        "equity": round(total_equity, 2),
        "positions": positions,
        "spot": spot_balances,
    }


def live_price(market: str = "all") -> dict:
    """Current mid prices for watched markets or a specific one."""
    mids = _hl_post({"type": "allMids"})
    mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
    mids.update(mids_xyz)

    if market.lower() != "all":
        for k, v in mids.items():
            if market.lower() in k.lower():
                return {"prices": {k: float(v)}}
        return {"error": f"No price found for '{market}'"}

    from common.watchlist import get_watchlist_coins
    watchlist = get_watchlist_coins()
    prices = {}
    for k in watchlist:
        if k in mids:
            prices[k] = float(mids[k])
    return {"prices": prices}


def analyze_market(coin: str) -> dict:
    """Technicals: trend, S/R, ATR, BBands, volume, signals."""
    try:
        from modules.candle_cache import CandleCache
        from common.market_snapshot import build_snapshot, render_snapshot, render_signal_summary

        mids = _hl_post({"type": "allMids"})
        mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
        mids.update(mids_xyz)
        price = float(mids.get(coin, 0))
        if not price:
            return {"error": f"No price data for {coin}"}

        cache = CandleCache()
        snap = build_snapshot(coin, cache, price)
        technicals_text = render_snapshot(snap, detail="full")
        signals_text = render_signal_summary(snap)
        return {
            "coin": coin,
            "price": price,
            "technicals": technicals_text,
            "signals": signals_text,
        }
    except Exception as e:
        return {"error": f"Analysis error: {e}"}


def market_brief(market: str) -> dict:
    """Full market context: price, technicals, position, thesis, memory."""
    try:
        from common.context_harness import build_thesis_context

        addr = _resolve_main_wallet()
        account_state = {"account": {"total_equity": 0}, "alerts": [], "escalation": "L0"}
        if addr:
            for dex in ['', 'xyz']:
                payload: dict = {"type": "clearinghouseState", "user": addr}
                if dex:
                    payload["dex"] = dex
                state = _hl_post(payload)
                account_state["account"]["total_equity"] += float(
                    state.get("marginSummary", {}).get("accountValue", 0)
                )

        snapshot_text = None
        try:
            from modules.candle_cache import CandleCache
            from common.market_snapshot import build_snapshot, render_snapshot
            mids = _hl_post({"type": "allMids"})
            mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
            mids.update(mids_xyz)
            price = float(mids.get(market, 0))
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
        return {"market": market, "brief": result.text}
    except Exception as e:
        return {"error": f"Error building market brief: {e}"}


def check_funding(coin: str) -> dict:
    """Funding rates, OI, volume for a market."""
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
                    return {
                        "coin": display,
                        "price": mark,
                        "change_24h_pct": round(change, 2),
                        "funding_rate": funding,
                        "funding_ann_pct": round(funding * 100 * 24 * 365, 1),
                        "oi": oi,
                        "volume_24h": vol,
                    }

    return {"error": f"No funding data for {coin}"}


def get_orders() -> dict:
    """All open orders (trigger, limit, stop) across both clearinghouses."""
    addr = _resolve_main_wallet()
    if not addr:
        return {"error": "No wallet configured"}

    orders = []
    for dex in ['', 'xyz']:
        payload: dict = {"type": "openOrders", "user": addr}
        if dex:
            payload["dex"] = dex
        raw = _hl_post(payload) or []
        for o in raw:
            orders.append({
                "coin": o.get("coin", "?"),
                "side": "BUY" if o.get("side") == "B" else "SELL",
                "size": o.get("sz"),
                "price": o.get("limitPx"),
                "type": o.get("orderType", "limit"),
            })
    return {"orders": orders}


def trade_journal(limit: int = 10) -> dict:
    """Recent trade records with PnL."""
    trades_path = _PROJECT_ROOT / "data" / "research" / "trades"
    if not trades_path.exists():
        return {"entries": []}

    files = sorted(trades_path.glob("*.json"), reverse=True)[:limit]
    entries = []
    for f in files:
        try:
            t = json.loads(f.read_text())
            entries.append({
                "timestamp": t.get("timestamp", f.stem)[:10],
                "coin": t.get("coin", "?"),
                "side": t.get("side", "?"),
                "size": t.get("size", "?"),
                "price": t.get("price", "?"),
                "pnl": t.get("pnl", "?"),
            })
        except Exception:
            pass
    return {"entries": entries}


def thesis_state(market: str = "all") -> dict:
    """Current thesis conviction, direction, age for markets."""
    thesis_dir = _PROJECT_ROOT / "data" / "thesis"
    if not thesis_dir.exists():
        return {"theses": {}}

    results = {}
    for path in thesis_dir.glob("*_state.json"):
        try:
            data = json.loads(path.read_text())
            mkt = data.get("market", path.stem.replace("_state", ""))
            if market != "all" and not _coin_matches(mkt, market):
                continue
            results[mkt] = {
                "direction": data.get("direction", "flat"),
                "conviction": data.get("conviction", 0),
                "summary": data.get("thesis_summary", ""),
                "updated_at": data.get("updated_at", ""),
            }
        except Exception:
            pass
    return {"theses": results}


def daemon_health() -> dict:
    """Daemon status: tier, tick count, strategies, risk gate."""
    try:
        state_path = _PROJECT_ROOT / "data" / "daemon" / "daemon_state.json"
        if not state_path.exists():
            return {"error": "Daemon state file not found"}
        data = json.loads(state_path.read_text())
        return {
            "tier": data.get("tier", "unknown"),
            "tick": data.get("tick", 0),
            "gate": data.get("gate", "unknown"),
            "last_tick_at": data.get("last_tick_at", ""),
            "strategies": data.get("active_strategies", []),
        }
    except Exception as e:
        return {"error": f"Daemon health error: {e}"}


# ═══════════════════════════════════════════════════════════════════════
# WRITE Tools (require approval in AI context)
# ═══════════════════════════════════════════════════════════════════════

def place_trade(coin: str, side: str, size: float) -> dict:
    """Place a market order. Only called after user approval."""
    try:
        from cli.hl_adapter import DirectHLProxy
        proxy = DirectHLProxy()
        is_buy = side.lower() in ("buy", "long", "b")
        result = proxy.market_order(coin=coin, is_buy=is_buy, sz=float(size))
        return {"filled": True, "coin": coin, "side": side, "size": size, "result": str(result)}
    except Exception as e:
        return {"error": f"Trade failed: {e}"}


def update_thesis(market: str, direction: str, conviction: float, summary: str = "") -> dict:
    """Update thesis conviction file. Only called after user approval."""
    try:
        thesis_dir = _PROJECT_ROOT / "data" / "thesis"
        thesis_dir.mkdir(parents=True, exist_ok=True)

        safe_name = market.replace(":", "_").replace("/", "_")
        path = thesis_dir / f"{safe_name}_state.json"
        if path.exists():
            data = json.loads(path.read_text())
            old_conviction = data.get("conviction", 0)
        else:
            data = {"market": market}
            old_conviction = 0

        data["direction"] = direction
        data["conviction"] = conviction
        if summary:
            data["thesis_summary"] = summary
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data["last_evaluation_ts"] = int(time.time() * 1000)

        path.write_text(json.dumps(data, indent=2) + "\n")
        return {
            "updated": True,
            "market": market,
            "direction": direction,
            "old_conviction": old_conviction,
            "new_conviction": conviction,
        }
    except Exception as e:
        return {"error": f"Thesis update failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════

TOOL_REGISTRY: Dict[str, Any] = {
    "status": status,
    "live_price": live_price,
    "analyze_market": analyze_market,
    "market_brief": market_brief,
    "check_funding": check_funding,
    "get_orders": get_orders,
    "trade_journal": trade_journal,
    "thesis_state": thesis_state,
    "daemon_health": daemon_health,
    "place_trade": place_trade,
    "update_thesis": update_thesis,
    # Back-compat aliases
    "account_summary": status,
}

WRITE_TOOLS = {"place_trade", "update_thesis"}

# Tool descriptions for system prompt injection
TOOL_DESCRIPTIONS = {
    "status": "Account equity, positions, spot balances",
    "live_price": "Current prices for watched markets or specific market",
    "analyze_market": "Technical analysis: trend, S/R, ATR, BBands, signals",
    "market_brief": "Full market context: price, technicals, thesis, memory",
    "check_funding": "Funding rate, OI, volume for a market",
    "get_orders": "All open orders across clearinghouses",
    "trade_journal": "Recent trade history with PnL",
    "thesis_state": "Current thesis conviction and direction",
    "daemon_health": "Daemon status: tier, tick, strategies",
    "place_trade": "Place a market order (requires approval)",
    "update_thesis": "Update thesis conviction (requires approval)",
}
