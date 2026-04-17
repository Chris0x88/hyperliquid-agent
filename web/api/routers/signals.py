"""Signals API — discovery + on-demand compute.

The dashboard uses these endpoints to:
  • GET /api/signals            — list all registered signals (cards + specs)
  • GET /api/signals/by-category — same, grouped by category for UI sidebar
  • GET /api/signals/{slug}/card — single card (for expander / explainer)
  • GET /api/signals/{slug}/compute?coin=X&interval=Y — run the signal

Candles are loaded from the same cache the /charts endpoints use.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from common.signals import all_signals, by_category, compute, get  # noqa: E402
from engines.data.candle_cache import CandleCache, INTERVAL_MS  # noqa: E402

log = logging.getLogger(__name__)
router = APIRouter()

_DB_PATH = _project_root / "data" / "candles.db"
_cache: CandleCache | None = None


def _get_cache() -> CandleCache:
    global _cache
    if _cache is None:
        _cache = CandleCache(str(_DB_PATH))
    return _cache


# ── Discovery ──────────────────────────────────────────────────────────────


@router.get("/")
async def list_signals():
    """All registered signals — cards + chart specs, sorted deterministically."""
    return {
        "signals": [
            {"card": s.card.to_dict(), "chart_spec": s.chart_spec.to_dict()}
            for s in all_signals()
        ]
    }


@router.get("/by-category")
async def list_signals_by_category():
    """Registered signals grouped by category. Drives the dashboard sidebar."""
    return {
        "categories": {
            cat: [
                {"card": s.card.to_dict(), "chart_spec": s.chart_spec.to_dict()}
                for s in sigs
            ]
            for cat, sigs in by_category().items()
        }
    }


@router.get("/{slug}/card")
async def get_signal_card(slug: str):
    """Just the card (explanatory metadata) for one signal."""
    cls = get(slug)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"Unknown signal: {slug}")
    return {
        "card": cls.card.to_dict(),
        "chart_spec": cls.chart_spec.to_dict(),
    }


# ── Compute ────────────────────────────────────────────────────────────────


@router.get("/{slug}/compute")
async def compute_signal(
    slug: str,
    coin: str = Query(..., description="Market symbol (BTC, xyz:CL, etc.)"),
    interval: str = Query(default="1h"),
    limit: int = Query(default=500, ge=10, le=5000),
):
    """Compute a signal against cached candles for a market.

    Returns the full SignalResult: time-series values, markers, meta,
    plus snapshots of the card + chart_spec for one-shot rendering.
    """
    cls = get(slug)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"Unknown signal: {slug}")

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

    # Try common coin aliases — matches behaviour in routers/charts.py
    upper = coin.upper()
    candidates = [upper, f"xyz:{upper}"]
    if upper.startswith("XYZ:"):
        candidates = [coin, upper[4:]]

    candles: list = []
    try:
        cache = _get_cache()
        for candidate in candidates:
            candles = cache.get_candles(candidate, interval, start_ms, end_ms)
            if candles:
                break
    except Exception as exc:
        log.warning("Cache read failed for %s %s: %s", coin, interval, exc)
        raise HTTPException(status_code=503, detail=f"Cache read failed: {exc}")

    if not candles:
        raise HTTPException(
            status_code=404,
            detail=f"No candles cached for {coin} at {interval}",
        )

    try:
        result = compute(slug, candles)
    except Exception as exc:
        log.error("Signal compute failed: slug=%s coin=%s err=%s", slug, coin, exc)
        raise HTTPException(status_code=500, detail=f"Compute failed: {exc}")

    return result.to_dict() | {"coin": coin, "interval": interval, "bar_count": len(candles)}
