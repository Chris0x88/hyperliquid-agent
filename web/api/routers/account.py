"""Account status, positions, and P&L endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

# Ensure agent-cli is on the path for common.* imports
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from common.account_state import fetch_registered_account_state
from agent.tool_functions import live_price, get_orders, check_funding
from web.api.dependencies import DATA_DIR
from web.api.readers.sqlite_reader import SqliteReader

router = APIRouter()
_memory_db = SqliteReader(DATA_DIR / "memory" / "memory.db")


def _as_float(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_str(v) -> str:
    """Return a numeric value as string (matching HL API convention for position fields)."""
    try:
        return str(float(v or 0))
    except (TypeError, ValueError):
        return "0"


def _build_position(p: dict) -> dict:
    """Map internal position dict to the shape the frontend Position interface expects.

    The internal dict (from common.account_state) uses abbreviated keys like
    `size`, `entry`, `upnl` and stores leverage as a plain number.  The frontend
    TypeScript interface mirrors the HL API field names: szi, entryPx,
    positionValue, unrealizedPnl, returnOnEquity, leverage:{type,value},
    liquidationPx, marginUsed, maxLeverage.

    We prefer the raw HL API data stored in p["raw"] and fall back to the
    mapped internal fields so the response always has every key populated.
    """
    raw = p.get("raw") or {}

    size = _as_float(raw.get("szi", p.get("size", 0)))
    entry_px = _as_float(raw.get("entryPx", p.get("entry", 0)))
    upnl = _as_float(raw.get("unrealizedPnl", p.get("upnl", 0)))
    pos_value = _as_float(raw.get("positionValue", 0))
    roe = _as_float(raw.get("returnOnEquity", 0))
    margin_used = _as_float(raw.get("marginUsed", p.get("margin_used", 0)))
    max_leverage = _as_float(raw.get("maxLeverage", 0))
    liq_px = raw.get("liquidationPx", p.get("liq"))

    # Leverage: HL API returns {"type": "cross"|"isolated", "value": N}
    raw_lev = raw.get("leverage", {})
    if isinstance(raw_lev, dict):
        leverage = {
            "type": raw_lev.get("type", "cross"),
            "value": _as_float(raw_lev.get("value", p.get("leverage", 0))),
        }
    else:
        # Internal dict already extracted the scalar
        leverage = {
            "type": "cross",
            "value": _as_float(raw_lev if raw_lev else p.get("leverage", 0)),
        }

    # Coin: internal dict already normalises with xyz: prefix where needed
    coin = p.get("coin", raw.get("coin", "?"))

    return {
        "coin": coin,
        "szi": _as_str(size),
        "entryPx": _as_str(entry_px),
        "positionValue": _as_str(pos_value),
        "unrealizedPnl": _as_str(upnl),
        "returnOnEquity": _as_str(roe),
        "leverage": leverage,
        # Return None when liq price is zero (no liquidation risk) or missing
        "liquidationPx": _as_str(liq_px) if (liq_px is not None and _as_float(liq_px) > 0) else None,
        "marginUsed": _as_str(margin_used),
        "maxLeverage": max_leverage,
        # Extra context for the UI (not in TypeScript interface but harmless)
        "dex": p.get("dex", "native"),
        "account": p.get("account_label", p.get("account_role", "main")),
    }


@router.get("/status")
async def get_account_status():
    """Full account status: equity, positions, margin, P&L.

    Returns data shaped to match the frontend AccountStatus TypeScript interface:
      { equity: number, positions: Position[], spot: SpotBalance[] }

    Positions use HL API field names (szi, entryPx, unrealizedPnl, etc.) so the
    dashboard PositionCards component can render them without NaN.

    EQUITY CALCULATION (REVERTED 2026-04-17):
    Earlier in the session we tried to "fix" a perceived triple-count by using
    `spot_usdc + Σ uPnL`. That formula collapsed the operator's true
    multi-wallet equity (~$580 across main + vault) to ~$21 by ignoring the
    vault wallet entirely. Per the operator: the original per-wallet sum
    (`native + xyz + spot_usdc` summed across ALL configured wallets) was
    very close to right, just had a few cleanup edges. Reverted. The bundle
    `total_equity` returned by fetch_registered_account_state already sums
    each wallet's row including main + vault + subs.
    """
    bundle = fetch_registered_account_state()
    if not bundle.get("accounts"):
        return {"error": "No wallet configured", "equity": 0, "positions": [], "spot": []}

    acct = bundle.get("account", {})
    equity = round(_as_float(acct.get("total_equity")), 2)

    positions = [_build_position(p) for p in bundle.get("positions", [])]

    spot = [
        {"coin": bal["coin"], "total": bal["total"], "account": row["label"]}
        for row in bundle.get("accounts", [])
        for bal in row.get("spot_balances", [])
        if bal.get("total", 0) > 0
    ]

    return {
        "equity": equity,
        "positions": positions,
        "spot": spot,
    }


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
    """Historical equity snapshots for charting.

    Returns snapshots in chronological order (oldest first) with fields:
      timestamp_ms, equity_total, drawdown_pct, high_water_mark, position_count

    drawdown_pct is computed on-the-fly from high_water_mark when the stored
    value is 0 (handles early snapshots before drawdown tracking was live).
    """
    try:
        rows = _memory_db.query(
            """SELECT timestamp_ms, equity_total, spot_usdc, drawdown_pct,
                      position_count, high_water_mark
               FROM account_snapshots
               ORDER BY timestamp_ms DESC
               LIMIT ?""",
            (limit,),
        )
    except FileNotFoundError:
        return {"snapshots": []}

    # Return chronological order
    rows.reverse()

    # Fix drawdown: if stored drawdown_pct is 0 but high_water_mark > equity_total,
    # compute the real drawdown from the HWM.  This handles early snapshots where
    # drawdown_pct was not yet stored by the daemon.
    for r in rows:
        hwm = float(r.get("high_water_mark") or 0)
        equity = float(r.get("equity_total") or 0)
        stored_dd = float(r.get("drawdown_pct") or 0)
        if stored_dd == 0 and hwm > 0 and equity < hwm:
            r["drawdown_pct"] = round((hwm - equity) / hwm * 100, 2)

    return {"snapshots": rows}
