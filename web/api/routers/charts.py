"""Candle OHLCV data endpoints for the charting page."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional

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

# Minimum cached candles below which we do a live backfill from HL API
_BACKFILL_THRESHOLD = 50

# ─── Singleton DB connection ──────────────────────────────────────────────────
# Re-use one CandleCache connection across requests to avoid the overhead of
# opening the SQLite file + WAL on every API call.
#
# Thread safety: FastAPI async endpoints run in the asyncio event loop (single
# thread by default with uvicorn).  All accesses to _cache happen in that same
# thread so no lock is needed.  If the application is ever run with thread
# workers, replace with a threading.local() pattern.

_cache: Optional[CandleCache] = None


def _get_cache() -> CandleCache:
    """Return the module-level CandleCache, creating it if needed."""
    global _cache
    if _cache is None:
        if not _DB_PATH.exists():
            raise FileNotFoundError(f"Candle database not found: {_DB_PATH}")
        _cache = CandleCache(db_path=str(_DB_PATH))
        # Checkpoint WAL on first open to reduce read amplification from
        # a large WAL file accumulated by the daemon's write sessions.
        try:
            _cache._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass
    return _cache


def _reset_cache() -> None:
    """Close and reset the singleton so the next call re-opens it."""
    global _cache
    if _cache is not None:
        try:
            _cache.close()
        except Exception:
            pass
        _cache = None


# ─── Live data helpers ────────────────────────────────────────────────────────

def _fetch_live_candles(
    coin: str,
    interval: str,
    interval_ms: int,
    n_candles: int = 2,
) -> list[dict]:
    """Fetch the last *n_candles* candles live from HL API.

    Returns candles in lightweight-charts format (time in SECONDS).

    For the main chart load we fetch enough candles to cover the requested
    window when the cache is sparse.  For tick updates we fetch just 2
    (current + previous) to minimise latency.

    Note: xyz perps (BRENTOIL, GOLD, SILVER, CL, SP500) require the
    xyz: prefix in the coin field — this is handled via _HL_COIN_NAME.
    """
    hl_coin = _HL_COIN_NAME.get(coin, coin)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - n_candles * interval_ms

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
            timeout=8,
        )
        if r.status_code != 200:
            log.warning("HL API returned %s for %s %s", r.status_code, coin, interval)
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
        log.debug("Live fetch failed for %s %s (%d candles): %s", coin, interval, n_candles, e)
        return []


def _store_live_candles(coin: str, interval: str, live: list[dict]) -> None:
    """Persist live-fetched candles to the cache DB for future use."""
    if not live or not _DB_PATH.exists():
        return
    hl_coin = _HL_COIN_NAME.get(coin, coin)
    raw_fmt = [
        {
            "t": c["time"] * 1000,
            "o": str(c["open"]),
            "h": str(c["high"]),
            "l": str(c["low"]),
            "c": str(c["close"]),
            "v": str(c["volume"]),
        }
        for c in live
    ]
    try:
        cache = _get_cache()
        cache.store_candles(hl_coin, interval, raw_fmt)
    except Exception as e:
        log.debug("Failed to persist live candles for %s %s: %s", coin, interval, e)


# ─── Coin name resolution ─────────────────────────────────────────────────────

def _resolve_coin(coin: str) -> str:
    """Return the canonical coin name (without xyz: prefix), uppercased."""
    upper = coin.upper()
    for canonical, aliases in _COIN_ALIASES.items():
        for alias in aliases:
            if upper == alias.upper():
                return canonical
    # Fallback: return as-is (handles unlisted coins)
    return upper


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/candles/{coin}")
async def get_candles(
    coin: str,
    interval: str = Query(default="1h"),
    limit: int = Query(default=200, ge=1, le=2000),
):
    """OHLCV candles for a market.

    Returns [{time, open, high, low, close, volume}, ...] sorted oldest-first.
    `time` is a Unix timestamp in SECONDS (as required by lightweight-charts).

    Strategy:
    1. Read cached candles from SQLite (fast — singleton connection, WAL).
    2. If cache has fewer than _BACKFILL_THRESHOLD candles, fetch the full
       requested window live from HL API and persist to cache.
    3. Always overlay the last 2 live candles to keep the current bar fresh.
    """
    if interval not in INTERVAL_MS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interval '{interval}'. Valid: {list(INTERVAL_MS.keys())}",
        )

    if not _DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Candle database not found")

    interval_ms = INTERVAL_MS[interval]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - limit * interval_ms

    canonical = _resolve_coin(coin)

    # Try all known coin name forms in the DB
    candidates = list(_COIN_ALIASES.get(canonical, [canonical]))
    if f"xyz:{canonical}" not in candidates:
        candidates.append(f"xyz:{canonical}")

    cached_rows: list = []
    try:
        cache = _get_cache()
        for candidate in candidates:
            cached_rows = cache.get_candles(candidate, interval, start_ms, end_ms)
            if cached_rows:
                break
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log.warning("Cache read error for %s %s: %s — resetting connection", canonical, interval, exc)
        _reset_cache()
        cached_rows = []

    # Convert cached rows to lightweight-charts format
    candles: list[dict] = [
        {
            "time": r["t"] // 1000,   # ms → seconds
            "open": float(r["o"]),
            "high": float(r["h"]),
            "low": float(r["l"]),
            "close": float(r["c"]),
            "volume": float(r["v"]),
        }
        for r in cached_rows
    ]

    # ── Live backfill when cache is sparse ────────────────────────────────────
    # If the cache has very few candles for this interval (e.g. BRENTOIL 15m
    # had only 3 rows), fetch the full requested window live from HL API and
    # persist to cache so subsequent requests are fast.
    if len(candles) < _BACKFILL_THRESHOLD:
        log.info(
            "Cache sparse for %s %s (%d rows < %d threshold) — live backfill",
            canonical, interval, len(candles), _BACKFILL_THRESHOLD,
        )
        live_all = _fetch_live_candles(canonical, interval, interval_ms, n_candles=limit)
        if live_all:
            _store_live_candles(canonical, interval, live_all)
            # Merge: live_all completely replaces sparse cached data for this window
            seen: dict[int, dict] = {}
            for c in candles:
                seen[c["time"]] = c
            for c in live_all:
                seen[c["time"]] = c
            candles = sorted(seen.values(), key=lambda x: x["time"])
    else:
        # Cache is healthy — just refresh the last 2 candles from live API
        live_tail = _fetch_live_candles(canonical, interval, interval_ms, n_candles=2)
        if live_tail:
            _store_live_candles(canonical, interval, live_tail)
            seen = {c["time"]: c for c in candles}
            for c in live_tail:
                seen[c["time"]] = c
            candles = sorted(seen.values(), key=lambda x: x["time"])

    # Trim to requested limit (take most recent)
    if len(candles) > limit:
        candles = candles[-limit:]

    return {"coin": canonical, "interval": interval, "candles": candles}


@router.get("/candles/{coin}/tick")
async def get_candle_tick(
    coin: str,
    interval: str = Query(default="1h"),
):
    """Live tick — returns just the current + previous candle from HL API.

    Lightweight endpoint for high-frequency polling (every 2-3s).
    Persists to cache so the DB stays current (INSERT OR REPLACE overwrites
    partial candles with updated data).
    """
    if interval not in INTERVAL_MS:
        raise HTTPException(status_code=400, detail=f"Invalid interval '{interval}'")

    canonical = _resolve_coin(coin)
    interval_ms = INTERVAL_MS[interval]
    candles = _fetch_live_candles(canonical, interval, interval_ms, n_candles=2)

    if candles:
        _store_live_candles(canonical, interval, candles)

    return {"coin": canonical, "interval": interval, "candles": candles}


@router.get("/candles/{coin}/meta")
async def get_candle_meta(coin: str):
    """Available intervals and date range for a coin."""
    if not _DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Candle database not found")

    canonical = _resolve_coin(coin)
    candidates = list(_COIN_ALIASES.get(canonical, [canonical]))
    if f"xyz:{canonical}" not in candidates:
        candidates.append(f"xyz:{canonical}")

    result: dict = {"coin": canonical, "intervals": {}}
    try:
        cache = _get_cache()
        for candidate in candidates:
            for iv in cache.intervals_for(candidate):
                rng = cache.date_range(candidate, iv)
                if rng and iv not in result["intervals"]:
                    result["intervals"][iv] = {
                        "start_ms": rng[0],
                        "end_ms": rng[1],
                        "count": cache.count(candidate, iv),
                    }
    except Exception as exc:
        log.warning("Meta query error for %s: %s", canonical, exc)
        _reset_cache()

    return result
