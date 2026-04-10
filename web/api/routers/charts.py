"""Candle OHLCV data endpoints for the charting page."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import requests as http_requests
from fastapi import APIRouter, HTTPException, Query

# Ensure agent-cli is on the path for modules.* imports
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from modules.candle_cache import CandleCache, INTERVAL_MS
from web.api.dependencies import DATA_DIR

log = logging.getLogger("charts")

router = APIRouter()

_DB_PATH = DATA_DIR / "candles" / "candles.db"

_HL_INFO_URL = "https://api.hyperliquid.xyz/info"

# Coin name mapping — handle both native and xyz: prefix forms
_COIN_ALIASES: dict[str, list[str]] = {
    "BTC": ["BTC"],
    "BRENTOIL": ["BRENTOIL", "xyz:BRENTOIL"],
    "GOLD": ["GOLD", "xyz:GOLD"],
    "SILVER": ["SILVER", "xyz:SILVER"],
    "CL": ["CL", "xyz:CL"],
    "SP500": ["SP500", "xyz:SP500"],
}

# Which HL API coin name to use for live fetch (xyz perps need xyz: prefix)
_HL_COIN_NAME: dict[str, str] = {
    "BTC": "BTC",
    "BRENTOIL": "xyz:BRENTOIL",
    "GOLD": "xyz:GOLD",
    "SILVER": "xyz:SILVER",
    "CL": "xyz:CL",
    "SP500": "xyz:SP500",
}


def _fetch_live_tail(coin: str, interval: str, interval_ms: int) -> list[dict]:
    """Fetch the last 2 candles live from HL API for the current tick.

    Returns candles in lightweight-charts format (time in seconds).
    We fetch 2 candles so we also refresh the just-completed candle
    with its final volume.
    """
    hl_coin = _HL_COIN_NAME.get(coin, coin)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - 2 * interval_ms

    try:
        r = http_requests.post(
            _HL_INFO_URL,
            json={
                "type": "candleSnapshot",
                "req": {
                    "coin": hl_coin,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": now_ms,
                },
            },
            timeout=5,
        )
        if r.status_code != 200:
            return []
        raw = r.json()
        if not isinstance(raw, list):
            return []
        return [
            {
                "time": int(c["t"]) // 1000,
                "open": float(c["o"]),
                "high": float(c["h"]),
                "low": float(c["l"]),
                "close": float(c["c"]),
                "volume": float(c["v"]),
            }
            for c in raw
        ]
    except Exception as e:
        log.debug("Live tail fetch failed for %s %s: %s", coin, interval, e)
        return []


def _resolve_coin(coin: str) -> str | None:
    """Return the canonical coin name as stored in the DB, or None if unknown."""
    upper = coin.upper()
    # Direct match first
    for canonical, aliases in _COIN_ALIASES.items():
        for alias in aliases:
            if upper == alias.upper():
                return canonical
    # Fallback: return as-is (handles unlisted coins)
    return upper


@router.get("/candles/{coin}")
async def get_candles(
    coin: str,
    interval: str = Query(default="1h"),
    limit: int = Query(default=200, ge=1, le=2000),
):
    """OHLCV candles for a market.

    Returns [{time, open, high, low, close, volume}, ...] sorted oldest-first.
    `time` is a Unix timestamp in SECONDS (as required by lightweight-charts).
    """
    if interval not in INTERVAL_MS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interval '{interval}'. Valid: {list(INTERVAL_MS.keys())}",
        )

    if not _DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Candle database not found")

    cache = CandleCache(db_path=str(_DB_PATH))
    try:
        interval_ms = INTERVAL_MS[interval]
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - limit * interval_ms

        canonical = _resolve_coin(coin)

        # Try canonical name first, then xyz: prefixed form
        candidates = _COIN_ALIASES.get(canonical, [canonical])
        if f"xyz:{canonical}" not in candidates:
            candidates = candidates + [f"xyz:{canonical}"]

        rows: list = []
        for candidate in candidates:
            rows = cache.get_candles(candidate, interval, start_ms, end_ms)
            if rows:
                break

        if not rows:
            # Return empty list rather than 404 — chart will show "no data" state
            return {"coin": canonical, "interval": interval, "candles": []}

        candles = [
            {
                "time": r["t"] // 1000,          # ms → seconds for lightweight-charts
                "open": float(r["o"]),
                "high": float(r["h"]),
                "low": float(r["l"]),
                "close": float(r["c"]),
                "volume": float(r["v"]),
            }
            for r in rows
        ]

        # Fetch live tail (last 2 candles) from HL API — overwrites
        # stale/partial cached candles with real-time data
        live = _fetch_live_tail(canonical, interval, interval_ms)

        # Deduplicate by time — live data wins over cached
        seen: dict[int, dict] = {}
        for c in candles:
            seen[c["time"]] = c
        for c in live:
            seen[c["time"]] = c  # live overwrites cached
        candles = sorted(seen.values(), key=lambda x: x["time"])

        return {"coin": canonical, "interval": interval, "candles": candles}

    finally:
        cache.close()


@router.get("/candles/{coin}/tick")
async def get_candle_tick(
    coin: str,
    interval: str = Query(default="1h"),
):
    """Live tick — returns just the current + previous candle from HL API.

    Lightweight endpoint for high-frequency polling (every 2-3s).
    Also persists to cache so the DB stays current (INSERT OR REPLACE
    overwrites partial candles with updated data).
    """
    if interval not in INTERVAL_MS:
        raise HTTPException(status_code=400, detail=f"Invalid interval '{interval}'")

    canonical = _resolve_coin(coin)
    interval_ms = INTERVAL_MS[interval]
    candles = _fetch_live_tail(canonical, interval, interval_ms)

    # Persist to cache — keeps DB current without waiting for daemon
    if candles and _DB_PATH.exists():
        try:
            hl_coin = _HL_COIN_NAME.get(canonical, canonical)
            cache = CandleCache(db_path=str(_DB_PATH))
            cache.store_candles(hl_coin, interval, [
                {"t": c["time"] * 1000, "o": str(c["open"]), "h": str(c["high"]),
                 "l": str(c["low"]), "c": str(c["close"]), "v": str(c["volume"])}
                for c in candles
            ])
            cache.close()
        except Exception:
            pass  # non-critical — display still works

    return {"coin": canonical, "interval": interval, "candles": candles}


@router.get("/candles/{coin}/meta")
async def get_candle_meta(coin: str):
    """Available intervals and date range for a coin."""
    if not _DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Candle database not found")

    cache = CandleCache(db_path=str(_DB_PATH))
    try:
        canonical = _resolve_coin(coin)
        candidates = _COIN_ALIASES.get(canonical, [canonical]) + [f"xyz:{canonical}"]

        result: dict = {"coin": canonical, "intervals": {}}
        for candidate in candidates:
            for iv in cache.intervals_for(candidate):
                rng = cache.date_range(candidate, iv)
                if rng and iv not in result["intervals"]:
                    result["intervals"][iv] = {
                        "start_ms": rng[0],
                        "end_ms": rng[1],
                        "count": cache.count(candidate, iv),
                    }

        return result
    finally:
        cache.close()
