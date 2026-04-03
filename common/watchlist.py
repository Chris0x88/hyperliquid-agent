"""Centralized watchlist — single source of truth for tracked markets.

All market lists across the system (telegram bot, AI agent, MCP server,
agent tools, scheduled checks) import from here instead of hardcoding.

Config file: data/config/watchlist.json
Format: [{"display": "BTC", "coin": "BTC", "aliases": ["btc"], "category": "crypto"}, ...]
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

log = logging.getLogger("watchlist")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "data" / "config" / "watchlist.json"

# Hardcoded fallback if config file is missing or corrupt
_DEFAULT_WATCHLIST = [
    {"display": "BTC", "coin": "BTC", "aliases": ["btc", "bitcoin"], "category": "crypto"},
    {"display": "ETH", "coin": "ETH", "aliases": ["eth", "ethereum"], "category": "crypto"},
    {"display": "Brent Oil", "coin": "xyz:BRENTOIL", "aliases": ["oil", "brent", "brentoil", "crude"], "category": "commodity"},
    {"display": "WTI Crude", "coin": "xyz:CL", "aliases": ["wti", "cl", "crude-us"], "category": "commodity"},
    {"display": "Gold", "coin": "xyz:GOLD", "aliases": ["gold", "xau"], "category": "commodity"},
    {"display": "Silver", "coin": "xyz:SILVER", "aliases": ["silver", "xag"], "category": "commodity"},
]


def load_watchlist() -> List[Dict]:
    """Load watchlist from JSON config. Falls back to hardcoded default."""
    try:
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text())
            if isinstance(data, list) and data:
                return data
    except Exception as e:
        log.warning("Failed to load watchlist config: %s", e)
    return list(_DEFAULT_WATCHLIST)


def get_watchlist_coins() -> List[str]:
    """Return just the coin IDs (e.g. ['BTC', 'xyz:BRENTOIL', ...])."""
    return [m["coin"] for m in load_watchlist()]


def get_approved_markets() -> List[str]:
    """Alias for get_watchlist_coins() — used by permission checks."""
    return get_watchlist_coins()


def get_coin_aliases() -> Dict[str, str]:
    """Return {alias: coin_id} dict for resolving user input to HL coin names."""
    aliases: Dict[str, str] = {}
    for m in load_watchlist():
        coin = m["coin"]
        aliases[coin.lower()] = coin
        aliases[m["display"].lower()] = coin
        for a in m.get("aliases", []):
            aliases[a.lower()] = coin
    return aliases


def get_watchlist_as_tuples() -> List[tuple]:
    """Return watchlist in the legacy (display, coin, aliases, category) tuple format.

    Used by telegram_bot.py for backward compatibility.
    """
    return [
        (m["display"], m["coin"], m.get("aliases", []), m.get("category", ""))
        for m in load_watchlist()
    ]


def add_market(display: str, coin: str, aliases: List[str], category: str = "other") -> bool:
    """Add a market to the watchlist config. Returns True on success."""
    watchlist = load_watchlist()
    # Check if already exists
    if any(m["coin"] == coin for m in watchlist):
        return False
    watchlist.append({
        "display": display,
        "coin": coin,
        "aliases": aliases,
        "category": category,
    })
    return _save_watchlist(watchlist)


def remove_market(coin: str) -> bool:
    """Remove a market from the watchlist config. Returns True on success."""
    watchlist = load_watchlist()
    original_len = len(watchlist)
    watchlist = [m for m in watchlist if m["coin"] != coin]
    if len(watchlist) == original_len:
        return False  # not found
    return _save_watchlist(watchlist)


def search_hl_markets(query: str) -> List[Dict]:
    """Search HL exchange for markets matching query. Returns candidates.

    Hits both native and xyz clearinghouse allMids endpoints.
    Returns: [{"coin": "xyz:CL", "price": 111.03, "dex": "xyz"}, ...]
    """
    query_lower = query.lower()
    results = []

    for dex_label, payload in [("native", {"type": "allMids"}), ("xyz", {"type": "allMids", "dex": "xyz"})]:
        try:
            r = requests.post("https://api.hyperliquid.xyz/info", json=payload, timeout=8)
            if r.status_code == 200:
                for coin, mid in r.json().items():
                    bare = coin.replace("xyz:", "").lower()
                    if query_lower in bare or query_lower in coin.lower():
                        results.append({
                            "coin": coin,
                            "price": float(mid),
                            "dex": dex_label,
                        })
        except Exception:
            pass
        time.sleep(0.15)

    # Sort by relevance (exact match first, then alphabetical)
    results.sort(key=lambda r: (0 if query_lower == r["coin"].replace("xyz:", "").lower() else 1, r["coin"]))
    return results[:10]


def _save_watchlist(watchlist: List[Dict]) -> bool:
    """Atomically write watchlist to config file."""
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(watchlist, indent=2) + "\n")
        tmp.replace(_CONFIG_PATH)
        return True
    except Exception as e:
        log.error("Failed to save watchlist: %s", e)
        return False
