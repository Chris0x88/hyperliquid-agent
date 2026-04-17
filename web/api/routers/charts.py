"""Candle OHLCV data endpoints for the charting page.

Extended with:
  GET /charts/{market}/markers  — news, trade, lesson, critique markers
  GET /charts/{market}/overlay  — liquidation zones + sweep-risk score
"""

from __future__ import annotations

import json
import logging
import sqlite3
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

from engines.data.candle_cache import CandleCache, INTERVAL_MS
from web.api.dependencies import DATA_DIR
from web.api.readers.jsonl_reader import FileEventReader

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


# ─── Marker data readers ──────────────────────────────────────────────────────

_catalysts_reader = FileEventReader(DATA_DIR / "news" / "catalysts.jsonl")
_headlines_reader = FileEventReader(DATA_DIR / "news" / "headlines.jsonl")
_MEMORY_DB = DATA_DIR / "memory" / "memory.db"
_HEATMAP_ZONES = DATA_DIR / "heatmap" / "zones.jsonl"


def _memory_conn() -> sqlite3.Connection | None:
    """Open a read-only connection to memory.db; return None if not found."""
    if not _MEMORY_DB.exists():
        return None
    conn = sqlite3.connect(str(_MEMORY_DB), check_same_thread=False, timeout=5)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _coin_matches(coin: str, value: str | list) -> bool:
    """True if the canonical coin name (e.g. BRENTOIL) appears in value.

    Handles both native form ('BRENTOIL') and xyz: prefix ('xyz:BRENTOIL').
    Value may be a string or a list of strings.
    """
    forms = {coin.upper(), f"xyz:{coin.upper()}"}
    if isinstance(value, list):
        return any(v.upper() in forms or v.replace("xyz:", "").upper() == coin.upper() for v in value)
    return value.upper() in forms or value.replace("xyz:", "").upper() == coin.upper()


def _read_zones_for_market(canonical: str, limit: int = 50) -> list[dict]:
    """Read the most recent heatmap zones for a market from zones.jsonl."""
    if not _HEATMAP_ZONES.exists():
        return []
    zones: list[dict] = []
    try:
        with open(_HEATMAP_ZONES, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    z = json.loads(line)
                    if _coin_matches(canonical, z.get("instrument", "")):
                        zones.append(z)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    # Return most recent `limit` zones
    return zones[-limit:]


# ─── /markers endpoint ────────────────────────────────────────────────────────

@router.get("/{market}/markers")
async def get_chart_markers(
    market: str,
    lookback_h: int = Query(default=72, ge=1, le=8760, description="Hours of history to include"),
):
    """Chart marker data for a market.

    Returns four lists:
    - news: catalyst events with timestamp, severity, headline, rationale
    - trades: entry/exit markers from action_log
    - lessons: post-mortems from lessons table (closed-trade context)
    - critiques: entry critique markers (stub — entry_critic not yet wired to DB)

    Any list that has no underlying data source returns an empty list with
    stub=True so the frontend can render placeholder surfaces.
    """
    canonical = _resolve_coin(market)
    cutoff_ms = int((time.time() - lookback_h * 3600) * 1000)
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - lookback_h * 3600))

    # ── News markers ──────────────────────────────────────────────────────────
    # Join catalysts (have instruments + severity) with headlines (have title/url)
    headlines_by_id: dict[str, dict] = {}
    for h in _headlines_reader.read_latest(500):
        hid = h.get("id")
        if hid:
            headlines_by_id[hid] = h

    news_markers: list[dict] = []
    for c in _catalysts_reader.read_latest(500):
        instruments = c.get("instruments", [])
        if not _coin_matches(canonical, instruments):
            continue
        event_ts_iso = c.get("event_date") or c.get("created_at", "")
        # Parse ISO to unix seconds for the chart
        try:
            import datetime as dt
            ts = dt.datetime.fromisoformat(event_ts_iso.replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if ts * 1000 < cutoff_ms:
            continue
        hid = c.get("headline_id", "")
        hl = headlines_by_id.get(hid, {})
        news_markers.append({
            "time": int(ts),
            "type": "news",
            "severity": c.get("severity", 1),          # 1-5
            "category": c.get("category", "unknown"),
            "headline": hl.get("title", c.get("rationale", "News event")),
            "source": hl.get("source", ""),
            "url": hl.get("url", ""),
            "rationale": c.get("rationale", ""),
            "expected_direction": c.get("expected_direction"),
            "stub": False,
        })
    news_markers.sort(key=lambda x: x["time"])

    # ── Trade / action markers from action_log ────────────────────────────────
    # Filter to ACTUAL TRADE events. The action_log table also stores
    # auto-deleverage events, stop placements, TP placements, and other
    # system housekeeping — those are not trades and clutter the chart
    # ("21 trade actions" was 22 deleverage + 3 stop_placed in practice).
    # Operator wants this view to mean: real entry / exit / scale decisions.
    _REAL_TRADE_ACTIONS = {
        "place_order", "market_order", "limit_order",
        "position_opened", "position_closed",
        "scale_in", "scale_out",
        "manual_entry", "manual_exit",
        "buy", "sell",  # generic action types from older code paths
    }
    # Everything else (deleverage / stop_placed / tp_placed / sl_updated /
    # leverage_adjusted etc) is housekeeping and stays out of this list.
    # If a future row uses an action_type we haven't whitelisted, it WILL
    # be filtered — operator can grep action_log directly to investigate.
    trade_markers: list[dict] = []
    housekeeping_count = 0
    conn = _memory_conn()
    if conn is not None:
        try:
            rows = conn.execute(
                """
                SELECT timestamp_ms, market, action_type, detail, reasoning, outcome
                FROM action_log
                WHERE market = ? AND timestamp_ms >= ?
                ORDER BY timestamp_ms ASC
                """,
                (canonical, cutoff_ms),
            ).fetchall()
            for r in rows:
                action = (r["action_type"] or "").lower()
                if action not in _REAL_TRADE_ACTIONS:
                    housekeeping_count += 1
                    continue
                detail_raw = r["detail"] or "{}"
                try:
                    detail = json.loads(detail_raw) if detail_raw.startswith("{") else {}
                except json.JSONDecodeError:
                    detail = {}
                trade_markers.append({
                    "time": r["timestamp_ms"] // 1000,
                    "type": "trade",
                    "action": r["action_type"],
                    "market": r["market"],
                    "detail": detail,
                    "reasoning": r["reasoning"] or "",
                    "outcome": r["outcome"] or "",
                    "stub": False,
                })
            if housekeeping_count > 0:
                log.debug(
                    "/charts/%s/markers: filtered %d housekeeping action_log rows "
                    "(deleverage / stop_placed / etc) to keep trade marker list trade-only",
                    canonical, housekeeping_count,
                )
        except Exception as exc:
            log.debug("action_log query failed: %s", exc)
        finally:
            conn.close()
    else:
        trade_markers = []  # No memory DB yet

    # ── Lesson markers from lessons table ─────────────────────────────────────
    lesson_markers: list[dict] = []
    conn2 = _memory_conn()
    if conn2 is not None:
        try:
            rows2 = conn2.execute(
                """
                SELECT id, created_at, trade_closed_at, market, direction,
                       lesson_type, outcome, pnl_usd, roe_pct, holding_ms,
                       conviction_at_open, summary, tags
                FROM lessons
                WHERE market = ? AND trade_closed_at >= ?
                ORDER BY trade_closed_at ASC
                """,
                (canonical, cutoff_iso),
            ).fetchall()
            for r in rows2:
                try:
                    import datetime as dt
                    ts = dt.datetime.fromisoformat(
                        r["trade_closed_at"].replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    continue
                try:
                    tags = json.loads(r["tags"]) if r["tags"] else []
                except json.JSONDecodeError:
                    tags = []
                lesson_markers.append({
                    "time": int(ts),
                    "type": "lesson",
                    "lesson_id": r["id"],
                    "market": r["market"],
                    "direction": r["direction"],
                    "lesson_type": r["lesson_type"],
                    "outcome": r["outcome"],
                    "pnl_usd": r["pnl_usd"],
                    "roe_pct": r["roe_pct"],
                    "holding_ms": r["holding_ms"],
                    "conviction_at_open": r["conviction_at_open"],
                    "summary": r["summary"],
                    "tags": tags,
                    "stub": False,
                })
        except Exception as exc:
            log.debug("lessons query failed: %s", exc)
        finally:
            conn2.close()

    # ── Entry critique markers — read directly from entry_critiques.jsonl ─────
    # The daemon iterator (and scripts/critique_position.py) write post-mortem
    # rows here on every new entry. We don't need a memory.db migration —
    # the jsonl is small enough to read tail-N per request.
    critique_markers: list[dict] = []
    try:
        critiques_path = DATA_DIR / "research" / "entry_critiques.jsonl"
        if critiques_path.exists():
            # Bounded read — last 200 critiques is plenty (< 50KB typically)
            tail_reader = FileEventReader(critiques_path)
            for c in tail_reader.read_latest(200):
                inst = c.get("instrument", "")
                # Coin-name normalisation (xyz: prefix bug — handled by helper)
                if not _coin_matches(canonical, [inst]):
                    continue
                created_at = c.get("created_at", "")
                try:
                    import datetime as dt
                    ts = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
                if ts * 1000 < cutoff_ms:
                    continue
                grade = c.get("grade", {}) or {}
                # Compose a compact summary for the marker tooltip
                pass_count = grade.get("pass_count", 0)
                warn_count = grade.get("warn_count", 0)
                fail_count = grade.get("fail_count", 0)
                overall = grade.get("overall_label", "?")
                suggestions = grade.get("suggestions") or []
                critique_markers.append({
                    "time": int(ts),
                    "type": "critique",
                    "instrument": inst,
                    "direction": c.get("direction", "?"),
                    "entry_price": c.get("entry_price"),
                    "entry_qty": c.get("entry_qty"),
                    "leverage": c.get("leverage"),
                    "overall_label": overall,
                    "pass_count": pass_count,
                    "warn_count": warn_count,
                    "fail_count": fail_count,
                    "suggestions": suggestions[:3],
                    "stub": False,
                })
    except Exception as exc:
        log.debug("entry_critiques read failed: %s", exc)
    critique_markers.sort(key=lambda x: x["time"])

    return {
        "market": canonical,
        "lookback_h": lookback_h,
        "news": news_markers,
        "trades": trade_markers,
        "lessons": lesson_markers,
        "critiques": critique_markers,
    }


# ─── /overlay endpoint ────────────────────────────────────────────────────────

@router.get("/{market}/overlay")
async def get_chart_overlay(
    market: str,
    lookback_h: int = Query(default=24, ge=1, le=720),
):
    """Manipulation-overlay data for the chart.

    Returns:
    - liq_zones: list of liquidation-heatmap zones for the market
    - cascades: recent cascade events (stub — sweep_detector not yet shipped)
    - sweep_risk: integer 0-100 risk score from sweep_detector (stub today)

    Items with stub=True will be replaced in-place when Phase 2 sweep_detector ships.
    """
    canonical = _resolve_coin(market)

    # ── Liquidation heatmap zones ─────────────────────────────────────────────
    raw_zones = _read_zones_for_market(canonical, limit=100)
    liq_zones: list[dict] = []
    for z in raw_zones:
        liq_zones.append({
            "snapshot_at": z.get("snapshot_at", ""),
            "side": z.get("side", ""),           # "bid" | "ask"
            "price_low": z.get("price_low"),
            "price_high": z.get("price_high"),
            "centroid": z.get("centroid"),
            "notional_usd": z.get("notional_usd"),
            "distance_bps": z.get("distance_bps"),
            "rank": z.get("rank", 1),
            "stub": False,
        })

    # ── Cascades — stub (sweep_detector Phase 2) ──────────────────────────────
    cascades: list[dict] = [{
        "stub": True,
        "message": "Cascade events require sweep_detector (Phase 2). Returns real data when shipped.",
    }]

    # ── Sweep-risk score — stub ───────────────────────────────────────────────
    sweep_risk = {
        "score": 0,
        "label": "Unknown",
        "stub": True,
        "message": "Sweep risk score from sweep_detector (Phase 2). Returns 0-100 when shipped.",
    }

    return {
        "market": canonical,
        "liq_zones": liq_zones,
        "cascades": cascades,
        "sweep_risk": sweep_risk,
    }
