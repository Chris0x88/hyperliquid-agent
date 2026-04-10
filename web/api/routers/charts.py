"""Candle OHLCV data endpoints for the charting page."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

# Ensure agent-cli is on the path for modules.* imports
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from modules.candle_cache import CandleCache, INTERVAL_MS
from web.api.dependencies import DATA_DIR

router = APIRouter()

_DB_PATH = DATA_DIR / "candles" / "candles.db"

# Coin name mapping — handle both native and xyz: prefix forms
_COIN_ALIASES: dict[str, list[str]] = {
    "BTC": ["BTC"],
    "BRENTOIL": ["BRENTOIL", "xyz:BRENTOIL"],
    "GOLD": ["GOLD", "xyz:GOLD"],
    "SILVER": ["SILVER", "xyz:SILVER"],
    "CL": ["CL", "xyz:CL"],
    "SP500": ["SP500", "xyz:SP500"],
}


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

        # Deduplicate by time (keep last) and sort
        seen: dict[int, dict] = {}
        for c in candles:
            seen[c["time"]] = c
        candles = sorted(seen.values(), key=lambda x: x["time"])

        return {"coin": canonical, "interval": interval, "candles": candles}

    finally:
        cache.close()


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
