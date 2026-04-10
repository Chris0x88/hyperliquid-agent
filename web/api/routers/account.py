"""Account status, positions, and P&L endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

# Ensure agent-cli is on the path for common.* imports
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from common.tools import status, live_price, get_orders, check_funding
from web.api.dependencies import DATA_DIR
from web.api.readers.sqlite_reader import SqliteReader

router = APIRouter()
_memory_db = SqliteReader(DATA_DIR / "memory" / "memory.db")


@router.get("/status")
async def get_account_status():
    """Full account status: equity, positions, margin, P&L."""
    return status()


@router.get("/prices")
async def get_prices(market: str = "all"):
    """Current prices for watched markets or a specific market."""
    return live_price(market)


@router.get("/orders")
async def get_open_orders():
    """Open orders (trigger, limit, stop)."""
    return get_orders()


@router.get("/funding/{coin}")
async def get_funding(coin: str):
    """Funding rate, OI, volume, 24h change for a market."""
    return check_funding(coin)


@router.get("/equity-curve")
async def get_equity_curve(limit: int = 500):
    """Historical equity snapshots for charting."""
    rows = _memory_db.query(
        """SELECT timestamp_ms, equity_total, spot_usdc, drawdown_pct,
                  position_count, high_water_mark
           FROM account_snapshots
           ORDER BY timestamp_ms DESC
           LIMIT ?""",
        (limit,),
    )
    # Return chronological order
    rows.reverse()
    return {"snapshots": rows}
