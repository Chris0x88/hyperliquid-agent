"""HyperLiquid API helpers extracted from telegram_bot.py.

Pure data-fetching functions with no Telegram dependency.
Coin-name normalisation utilities live here too so every layer
can import them without pulling in the full bot module.
"""
from __future__ import annotations

from typing import Optional

import requests

from common.watchlist import get_coin_aliases as _get_aliases

# ── Constants ────────────────────────────────────────────────

HL_API = "https://api.hyperliquid.xyz/info"

COIN_ALIASES: dict[str, str] = _get_aliases()

# ── Low-level API helper ─────────────────────────────────────


def _hl_post(payload: dict) -> dict:
    try:
        return requests.post(HL_API, json=payload, timeout=10).json()
    except Exception:
        return {}


# ── Coin-name normalisation ──────────────────────────────────


def _coin_matches(universe_name: str, target: str) -> bool:
    """Check if a universe asset name matches a target coin identifier.

    CRITICAL: The xyz clearinghouse returns universe names WITH the 'xyz:' prefix
    (e.g. 'xyz:BRENTOIL'), while native clearinghouse does NOT (e.g. 'BTC').
    This function handles both forms so callers don't need to worry about it.

    Examples:
        _coin_matches("xyz:BRENTOIL", "BRENTOIL") → True
        _coin_matches("xyz:BRENTOIL", "xyz:BRENTOIL") → True
        _coin_matches("BTC", "BTC") → True
    """
    if universe_name == target:
        return True
    bare_universe = universe_name.replace("xyz:", "")
    bare_target = target.replace("xyz:", "")
    return bare_universe == bare_target


def resolve_coin(text: str) -> Optional[str]:
    """Resolve user input to an HL coin identifier."""
    t = text.strip().lower()
    if t in COIN_ALIASES:
        return COIN_ALIASES[t]
    # Try with xyz: prefix
    if f"xyz:{t}" in COIN_ALIASES:
        return COIN_ALIASES[f"xyz:{t}"]
    return None


# ── Position / order / account fetchers ──────────────────────


def _get_all_positions(addr: str) -> list:
    """Get positions from BOTH native and xyz clearinghouses."""
    positions = []
    for dex in ['', 'xyz']:
        payload = {'type': 'clearinghouseState', 'user': addr}
        if dex:
            payload['dex'] = dex
        state = _hl_post(payload)
        for p in state.get('assetPositions', []):
            pos = p.get('position', {})
            pos['_dex'] = dex or 'native'
            positions.append(pos)
    return positions


def _get_all_orders(addr: str) -> list:
    """Get open orders from BOTH clearinghouses (rich format with orderType/triggerPx)."""
    orders = []
    for dex in ['', 'xyz']:
        payload = {'type': 'frontendOpenOrders', 'user': addr}
        if dex:
            payload['dex'] = dex
        result = _hl_post(payload) or []
        for o in result:
            o['_dex'] = dex or 'native'
        orders.extend(result)
    return orders


def _get_account_values(addr: str) -> dict:
    """Get account values for a single wallet from the shared account model."""
    from common.account_state import fetch_wallet_state

    row = fetch_wallet_state(addr, role="wallet")
    return {
        'native': row['native_equity'],
        'xyz': row['xyz_equity'],
        'spot': row['spot_usdc'],
        'total': row['total_equity'],
    }


def _get_market_oi(coin: str, dex: str = '') -> str:
    """Get open interest + 24h volume for a market. Returns formatted string."""
    try:
        payload: dict = {"type": "metaAndAssetCtxs"}
        if dex == 'xyz':
            payload["dex"] = "xyz"
        data = _hl_post(payload)
        if isinstance(data, list) and len(data) >= 2:
            meta = data[0]
            ctxs = data[1]
            universe = meta.get("universe", [])
            for i, ctx in enumerate(ctxs):
                if i < len(universe) and _coin_matches(universe[i].get("name", ""), coin):
                    oi = float(ctx.get("openInterest", 0))
                    vol = float(ctx.get("dayNtlVlm", 0))
                    parts = []
                    if oi > 0:
                        parts.append(f"OI `${oi / 1e6:.1f}M`")
                    if vol > 0:
                        parts.append(f"Vol `${vol / 1e6:.1f}M`")
                    return " • ".join(parts) if parts else ""
    except Exception:
        pass
    return ""


def _get_current_price(coin: str) -> Optional[float]:
    """Get current mid price for a coin (checks both clearinghouses)."""
    try:
        mids = _hl_post({"type": "allMids"})
        if coin in mids:
            return float(mids[coin])
    except Exception:
        pass
    try:
        mids = _hl_post({"type": "allMids", "dex": "xyz"})
        for k, v in mids.items():
            if k.replace("xyz:", "") == coin or k == coin:
                return float(v)
    except Exception:
        pass
    return None


def _get_all_market_ctx() -> dict:
    """Fetch metaAndAssetCtxs from both clearinghouses.

    Returns dict mapping coin name -> {"markPx": float, "prevDayPx": float}.
    Handles both native (BTC, ETH) and xyz (BRENTOIL, GOLD, etc.) markets.
    """
    result: dict = {}
    for dex in ['', 'xyz']:
        try:
            payload: dict = {"type": "metaAndAssetCtxs"}
            if dex:
                payload["dex"] = dex
            data = _hl_post(payload)
            if isinstance(data, list) and len(data) >= 2:
                universe = data[0].get("universe", [])
                ctxs = data[1]
                for i, ctx in enumerate(ctxs):
                    if i < len(universe):
                        name = universe[i].get("name", "")
                        mark = float(ctx.get("markPx", 0))
                        prev = float(ctx.get("prevDayPx", 0))
                        if mark > 0:
                            result[name] = {"markPx": mark, "prevDayPx": prev}
        except Exception:
            pass
    return result
