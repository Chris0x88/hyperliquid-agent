"""Account status, positions, and P&L endpoints."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests as _requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# Ensure agent-cli is on the path for common.* imports
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from common.account_state import fetch_registered_account_state
from common.account_resolver import resolve_vault_address
from agent.tool_functions import live_price, get_orders, check_funding
from web.api.auth import verify_token
from web.api.dependencies import DATA_DIR
from web.api.readers.sqlite_reader import SqliteReader

router = APIRouter()
_memory_db = SqliteReader(DATA_DIR / "memory" / "memory.db")

# HWM file — same path used by the daemon heartbeat
_HWM_PATH = DATA_DIR / "snapshots" / "hwm.json"
# Working state — written by heartbeat/account_collector with atr_cache + positions
_WORKING_STATE_PATH = DATA_DIR / "memory" / "working_state.json"

_HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def _fetch_vault_breakdown(vault_address: str) -> Optional[dict]:
    """Fetch vault participant breakdown from the HL public info API.

    Returns a dict with:
        your_equity          — leader (operator) share of vault equity
        third_party_equity   — sum of all follower shares
        participant_count    — total follower count (includes leader as 1 participant)
        leader_fraction      — operator's fractional ownership (0.0-1.0)

    Returns None on any network or parse error — callers must handle gracefully.
    """
    try:
        resp = _requests.post(
            _HL_INFO_URL,
            json={"type": "vaultDetails", "vaultAddress": vault_address},
            timeout=8,
        )
        if not resp.ok:
            return None
        d = resp.json()
        # followers list includes both leader and external depositors.
        # The HL API lists leader equity first with user == leader_address
        # or we can use leaderFraction to compute the split.
        leader_fraction = float(d.get("leaderFraction", 0))
        # Sum all follower equity to get total vault equity from the API
        followers = d.get("followers") or []
        total_from_followers = sum(float(f.get("vaultEquity", 0)) for f in followers)

        leader_entry = d.get("leader") or {}
        your_equity = float(leader_entry.get("vaultEquity") or (leader_fraction * total_from_followers))

        third_party = total_from_followers - your_equity
        # participant count = followers who are NOT the leader
        leader_addr = (d.get("leader") or {}).get("user", "").lower()
        external_participants = [
            f for f in followers
            if (f.get("user") or "").lower() != leader_addr
        ]

        return {
            "your_equity": round(your_equity, 2),
            "third_party_equity": round(max(third_party, 0.0), 2),
            "participant_count": len(external_participants),
            "leader_fraction": round(leader_fraction, 6),
        }
    except Exception:
        return None


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


@router.get("/ledger")
async def get_account_ledger():
    """Dense equity ledger for the dashboard EquityLedger card.

    Returns per-wallet breakdown + aggregates:
      - accounts[]: per-wallet rows (native/xyz/spot equity, free_margin, positions)
      - total_equity: sum of all wallet total_equity fields
      - unrealized_pnl: per-coin map (source: live position upnl from HL)
      - leverage_summary: { total_notional, total_margin, effective_leverage }
      - hwm: { value, set_at, drawdown_pct } — sourced from data/snapshots/hwm.json
      - realized_pnl: null (no realized-PnL history available yet — show "—" not $0)
      - funding_today: null (funding accrual not tracked per-day yet — show "—")
      - trade_count_24h: null (trade history not yet queryable — show "—")

    Fields that return null mean "we genuinely don't have this data" — the UI
    MUST render "—" not "$0.00" to distinguish absence from zero.
    """
    bundle = fetch_registered_account_state()
    if not bundle.get("accounts"):
        return {"error": "No wallet configured"}

    acct = bundle.get("account", {})
    total_equity = round(_as_float(acct.get("total_equity")), 2)

    # Vault breakdown — fetched once from HL public API so the UI can show
    # your_equity vs third_party_equity vs participant_count without hardcoding.
    vault_addr = resolve_vault_address()
    vault_breakdown: Optional[dict] = None
    if vault_addr:
        vault_breakdown = _fetch_vault_breakdown(vault_addr)

    # Per-wallet breakdown: each row already has native_equity, xyz_equity,
    # spot_usdc, spot_balances, positions from fetch_wallet_state().
    wallet_rows = []
    for row in bundle.get("accounts", []):
        native_eq = round(_as_float(row.get("native_equity")), 2)
        xyz_eq = round(_as_float(row.get("xyz_equity")), 2)
        spot_usdc_val = round(_as_float(row.get("spot_usdc")), 2)
        wallet_total = round(_as_float(row.get("total_equity")), 2)

        # Spot non-USDC assets value
        spot_assets_val = round(
            sum(
                _as_float(b.get("total"))
                for b in row.get("spot_balances", [])
                if b.get("coin") != "USDC"
            ),
            2,
        )

        # Per-wallet positions — sum marginUsed from raw HL data
        wallet_positions = row.get("positions", [])
        total_margin_wallet = round(
            sum(
                _as_float((p.get("raw") or {}).get("marginUsed") or p.get("margin_used"))
                for p in wallet_positions
            ),
            2,
        )

        # Free margin approximation: perps equity minus committed margin.
        # The real number is clearinghouse withdrawable, but we don't have it
        # per wallet without a separate API call. This is a good approximation.
        perps_equity = native_eq + xyz_eq
        free_margin = round(max(perps_equity - total_margin_wallet, 0.0), 2)

        is_vault = row.get("role") == "vault"

        entry: dict = {
            "role": row.get("role"),
            "label": row.get("label"),
            "address": row.get("address", ""),
            "native_equity": native_eq,
            "xyz_equity": xyz_eq,
            "spot_usdc": spot_usdc_val,
            "spot_assets": spot_assets_val,
            "total_equity": wallet_total,
            "free_margin": free_margin,
            "margin_used": total_margin_wallet,
            "spot_balances": row.get("spot_balances", []),
            "position_count": len(wallet_positions),
            "is_vault": is_vault,
            # Vault-specific breakdown (None when not a vault or API unavailable)
            "vault_your_equity": vault_breakdown.get("your_equity") if (is_vault and vault_breakdown) else None,
            "vault_third_party_equity": vault_breakdown.get("third_party_equity") if (is_vault and vault_breakdown) else None,
            "vault_participant_count": vault_breakdown.get("participant_count") if (is_vault and vault_breakdown) else None,
            "vault_leader_fraction": vault_breakdown.get("leader_fraction") if (is_vault and vault_breakdown) else None,
        }
        wallet_rows.append(entry)

    # Unrealized PnL per open position — sourced directly from HL
    unrealized_by_coin: dict[str, float] = {}
    total_notional = 0.0
    total_margin = 0.0
    for p in bundle.get("positions", []):
        raw = p.get("raw") or {}
        coin = p.get("coin", raw.get("coin", "?"))
        upnl = round(_as_float(raw.get("unrealizedPnl", p.get("upnl"))), 2)
        unrealized_by_coin[coin] = unrealized_by_coin.get(coin, 0.0) + upnl
        total_notional += _as_float(raw.get("positionValue"))
        total_margin += _as_float(raw.get("marginUsed", p.get("margin_used")))

    total_notional = round(total_notional, 2)
    total_margin = round(total_margin, 2)
    eff_leverage = round(total_notional / total_margin, 2) if total_margin > 0 else 0.0

    # HWM — sourced from data/snapshots/hwm.json (written by daemon heartbeat)
    hwm_val: Optional[float] = None
    hwm_set_at: Optional[str] = None
    drawdown_pct: Optional[float] = None
    if _HWM_PATH.exists():
        try:
            hwm_data = json.loads(_HWM_PATH.read_text())
            hwm_val = round(float(hwm_data.get("hwm", 0)), 2)
            # ts is a Unix timestamp (seconds)
            raw_ts = hwm_data.get("reset_at") or hwm_data.get("ts")
            if isinstance(raw_ts, (int, float)):
                hwm_set_at = datetime.fromtimestamp(raw_ts, tz=timezone.utc).isoformat()
            elif isinstance(raw_ts, str):
                hwm_set_at = raw_ts
            if hwm_val and hwm_val > 0 and total_equity < hwm_val:
                drawdown_pct = round((hwm_val - total_equity) / hwm_val * 100, 4)
            else:
                drawdown_pct = 0.0
        except Exception:
            pass

    # Realized PnL — no realized-PnL tracking yet.
    # Return null so the UI shows "—" not "$0.00".
    realized_pnl = {"today": None, "week": None, "inception": None}

    # Funding today — funding_tracker accrues but no per-day totals yet.
    funding_today: Optional[float] = None

    # 24h trade count — no closed-trades table yet.
    trade_count_24h: Optional[int] = None

    return {
        "total_equity": total_equity,
        "accounts": wallet_rows,
        "unrealized_pnl": unrealized_by_coin,
        "leverage_summary": {
            "total_notional": total_notional,
            "total_margin": total_margin,
            "effective_leverage": eff_leverage,
        },
        "hwm": {
            "value": hwm_val,
            "set_at": hwm_set_at,
            "drawdown_pct": drawdown_pct,
        },
        "realized_pnl": realized_pnl,
        "funding_today": funding_today,
        "trade_count_24h": trade_count_24h,
    }


class ResetHWMRequest(BaseModel):
    reason: str = "manual reset"


@router.post("/reset-hwm", dependencies=[Depends(verify_token)])
async def reset_hwm(body: ResetHWMRequest):
    """Reset the high-water mark to current live equity.

    SAFETY: Writes a timestamped backup of the pre-reset HWM before overwriting.
    Requires bearer auth to prevent accidental resets.

    Steps:
      1. Fetch current equity from account state bundle.
      2. Read current HWM from hwm.json (if any).
      3. Write backup to hwm.json.pre-reset-<ts>.json alongside hwm.json.
      4. Write new HWM = current_equity to hwm.json.
    """
    bundle = fetch_registered_account_state()
    if not bundle.get("accounts"):
        raise HTTPException(status_code=503, detail="No wallet configured")

    acct = bundle.get("account", {})
    current_equity = round(_as_float(acct.get("total_equity")), 6)
    if current_equity <= 0:
        raise HTTPException(status_code=503, detail="Could not fetch current equity")

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    now_ts = int(time.time())

    # Read pre-reset HWM for backup
    pre_reset: dict[str, Any] = {}
    if _HWM_PATH.exists():
        try:
            pre_reset = json.loads(_HWM_PATH.read_text())
        except Exception:
            pre_reset = {}

    # Write backup alongside the main HWM file
    backup_path = _HWM_PATH.parent / f"hwm.json.pre-reset-{now_ts}.json"
    backup_path.write_text(
        json.dumps(
            {**pre_reset, "backed_up_at": now_iso, "backup_reason": body.reason},
            indent=2,
        )
    )

    # Write new HWM
    new_hwm = {
        "hwm": current_equity,
        "ts": now_ts,
        "reset_at": now_iso,
        "reset_reason": body.reason,
    }
    _HWM_PATH.write_text(json.dumps(new_hwm, indent=2))

    return {
        "ok": True,
        "previous_hwm": pre_reset.get("hwm"),
        "new_hwm": current_equity,
        "reset_at": now_iso,
        "reason": body.reason,
        "backup_path": str(backup_path),
    }


@router.get("/risk-budget")
async def get_risk_budget():
    """Cumulative open-risk vs 10% equity cap (mirrors portfolio_risk_monitor logic).

    Calculation (mirrors PortfolioRiskMonitorIterator._row_for_position):
      risk_usd = Σ |entry_price - sl_price| × |size|  for each open position
      risk_pct = risk_usd / total_equity

    SL is sourced from exchange open trigger orders (stop-loss only).
    Falls back to liquidation price if no SL order is found for a position.
    If neither SL nor liq is available, that position contributes 0 risk_usd.

    Thresholds (overridable via data/config/portfolio_risk_monitor.json):
      green  < 8%   (warn_pct default)
      amber  8-10%  (between warn and cap)
      red    ≥ 10%  (cap_pct default)

    Returns null values (not zero) if equity cannot be fetched — UI must show "—".
    """
    # Load config overrides if available
    cap_pct = 0.10
    warn_pct = 0.08
    risk_config_path = DATA_DIR / "config" / "portfolio_risk_monitor.json"
    if risk_config_path.exists():
        try:
            cfg = json.loads(risk_config_path.read_text())
            cap_pct = float(cfg.get("cap_pct", cap_pct))
            warn_pct = float(cfg.get("warn_pct", warn_pct))
        except Exception:
            pass

    bundle = fetch_registered_account_state()
    if not bundle.get("accounts"):
        return {
            "risk_usd": None,
            "risk_pct": None,
            "total_equity": None,
            "warn_pct": warn_pct,
            "cap_pct": cap_pct,
            "status": "error",
            "positions": [],
        }

    acct = bundle.get("account", {})
    total_equity = _as_float(acct.get("total_equity"))
    if total_equity <= 0:
        return {
            "risk_usd": None,
            "risk_pct": None,
            "total_equity": None,
            "warn_pct": warn_pct,
            "cap_pct": cap_pct,
            "status": "no_equity",
            "positions": [],
        }

    # Fetch open trigger orders and bucket stop-loss triggers by coin.
    # This mirrors PortfolioRiskMonitorIterator._fetch_triggers() logic
    # but uses the web API's get_orders() rather than the daemon adapter.
    sl_by_coin: dict[str, float] = {}
    try:
        raw_orders = get_orders()
        orders_list = raw_orders if isinstance(raw_orders, list) else (raw_orders or {}).get("orders", [])
        for o in (orders_list or []):
            # HL trigger orders: isTrigger=true, orderType="Stop Market" or "Stop Limit"
            # Side "A" = ask/sell = stop-loss for longs (most common)
            if not o.get("isTrigger", False):
                continue
            order_type = o.get("orderType", "")
            if "Stop" not in order_type:
                continue
            coin = str(o.get("coin", ""))
            if not coin:
                continue
            trig_px = _as_float(o.get("triggerPx"))
            if trig_px <= 0:
                continue
            # For longs: best SL = highest (closest to entry = most protective)
            existing = sl_by_coin.get(coin)
            if existing is None or trig_px > existing:
                sl_by_coin[coin] = trig_px
            # Dual-bucket both prefixed and unprefixed — recurring xyz: bug defence
            alt = coin.replace("xyz:", "") if coin.startswith("xyz:") else f"xyz:{coin}"
            existing_alt = sl_by_coin.get(alt)
            if existing_alt is None or trig_px > existing_alt:
                sl_by_coin[alt] = trig_px
    except Exception:
        pass  # SL lookup is best-effort; falls back to liq price below

    # Per-position risk rows
    position_rows = []
    total_risk_usd = 0.0
    for p in bundle.get("positions", []):
        raw = p.get("raw") or {}
        coin = p.get("coin", raw.get("coin", "?"))
        size = abs(_as_float(raw.get("szi", p.get("size", 0))))
        entry = _as_float(raw.get("entryPx", p.get("entry", 0)))
        liq_px_raw = raw.get("liquidationPx") or p.get("liq") or 0
        liq_px = _as_float(liq_px_raw)

        # SL resolution: exchange trigger → liq fallback → none
        sl_px = sl_by_coin.get(coin)
        sl_source = "exchange"
        if sl_px is None:
            if liq_px > 0:
                sl_px = liq_px
                sl_source = "liquidation_fallback"
            else:
                sl_source = "none"

        if sl_px is not None and entry > 0 and size > 0:
            risk_usd = abs(entry - sl_px) * size
        else:
            risk_usd = 0.0

        total_risk_usd += risk_usd
        position_rows.append(
            {
                "coin": coin,
                "entry": round(entry, 4),
                "sl": round(sl_px, 4) if sl_px is not None else None,
                "sl_source": sl_source,
                "size": round(size, 6),
                "risk_usd": round(risk_usd, 2),
            }
        )

    total_risk_usd = round(total_risk_usd, 2)
    risk_pct = round(total_risk_usd / total_equity, 6) if total_equity > 0 else 0.0

    if risk_pct >= cap_pct:
        status = "critical"
    elif risk_pct >= warn_pct:
        status = "warning"
    else:
        status = "safe"

    return {
        "risk_usd": total_risk_usd,
        "risk_pct": risk_pct,
        "total_equity": round(total_equity, 2),
        "warn_pct": warn_pct,
        "cap_pct": cap_pct,
        "status": status,
        "positions": position_rows,
    }


@router.get("/positions/detailed")
async def get_positions_detailed():
    """Extended position detail: joins live HL state with ATR cache + sweep risk.

    Per-position fields beyond /status:
      - currentPx: live price (sourced from live_price("all"))
      - atr: daily ATR (from data/memory/working_state.json atr_cache)
      - sl_px / tp_px: from exchange open trigger orders
      - sl_distance / tp_distance: delta + % + ATRs from current price
      - liq_cushion_pct: |current - liq| / current * 100
      - liq_atrs: liq distance in ATR multiples
      - time_to_liq_atrs: liq_distance / ATR_1d (days of 1-ATR moves to liq)
      - sweep_risk: from data/checklist/state/latest.json if available
      - wallet: wallet label (Main / Vault)
      - entry_ts / time_held_ms: from working_state.json positions dict

    Data we don't have (returns null, not zero):
      - realized PnL per position
      - entry critique snippet (available via /critiques/ separately)
    """
    bundle = fetch_registered_account_state()
    if not bundle.get("accounts"):
        return {"positions": []}

    # ATR cache from working_state.json (written by heartbeat every 4h)
    atr_cache: dict[str, float] = {}
    try:
        ws = json.loads(_WORKING_STATE_PATH.read_text())
        for coin, row in (ws.get("atr_cache") or {}).items():
            v = float(row.get("value", 0)) if isinstance(row, dict) else float(row)
            atr_cache[coin] = v
            alt = coin.replace("xyz:", "") if coin.startswith("xyz:") else f"xyz:{coin}"
            atr_cache[alt] = v
    except Exception:
        pass

    # Sweep risk from data/checklist/state/latest.json
    sweep_risk_global: Optional[dict] = None
    checklist_path = DATA_DIR / "checklist" / "state" / "latest.json"
    if checklist_path.exists():
        try:
            cl = json.loads(checklist_path.read_text())
            sweep_risk_global = cl.get("sweep_risk")
        except Exception:
            pass

    # Live prices — one call, buckets both prefixed and unprefixed forms
    prices: dict[str, float] = {}
    try:
        price_resp = live_price("all")
        if isinstance(price_resp, dict):
            for k, v in price_resp.items():
                try:
                    fv = float(v)
                    prices[k] = fv
                    alt = k.replace("xyz:", "") if k.startswith("xyz:") else f"xyz:{k}"
                    prices[alt] = fv
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass

    # Open trigger orders bucketed by coin into SL and TP dicts
    sl_by_coin: dict[str, float] = {}
    tp_by_coin: dict[str, float] = {}
    try:
        raw_orders = get_orders()
        orders_list = raw_orders if isinstance(raw_orders, list) else (raw_orders or {}).get("orders", [])
        for o in (orders_list or []):
            if not o.get("isTrigger", False):
                continue
            coin = str(o.get("coin", ""))
            if not coin:
                continue
            trig_px = _as_float(o.get("triggerPx"))
            order_type = o.get("orderType", "")
            is_tp = "Take Profit" in order_type
            is_sl = "Stop" in order_type and not is_tp
            if trig_px <= 0:
                continue

            for bucket, cond in ((sl_by_coin, is_sl), (tp_by_coin, is_tp)):
                if not cond:
                    continue
                alt = coin.replace("xyz:", "") if coin.startswith("xyz:") else f"xyz:{coin}"
                if coin not in bucket:
                    bucket[coin] = trig_px
                if alt not in bucket:
                    bucket[alt] = trig_px
    except Exception:
        pass

    # Entry timestamps from working_state.json positions dict
    ws_positions: dict[str, Any] = {}
    try:
        ws_data = json.loads(_WORKING_STATE_PATH.read_text())
        ws_positions = ws_data.get("positions") or {}
    except Exception:
        pass

    now_ms = int(time.time() * 1000)

    def _dist(px_a: Optional[float], px_b: Optional[float], atr: Optional[float]) -> Optional[dict]:
        """Compute delta/pct/atrs between two prices."""
        if px_a is None or px_b is None or px_a == 0:
            return None
        delta = px_b - px_a
        pct = delta / px_a * 100
        atrs = abs(delta) / atr if (atr and atr > 0) else None
        return {
            "delta": round(delta, 4),
            "pct": round(pct, 3),
            "atrs": round(atrs, 2) if atrs is not None else None,
        }

    result_positions = []
    for p in bundle.get("positions", []):
        raw = p.get("raw") or {}
        coin = p.get("coin", raw.get("coin", "?"))
        size = _as_float(raw.get("szi", p.get("size", 0)))
        entry = _as_float(raw.get("entryPx", p.get("entry", 0)))
        upnl = _as_float(raw.get("unrealizedPnl", p.get("upnl", 0)))
        roe = _as_float(raw.get("returnOnEquity", 0))
        pos_value = _as_float(raw.get("positionValue", 0))
        margin_used = _as_float(raw.get("marginUsed", p.get("margin_used", 0)))
        max_leverage = _as_float(raw.get("maxLeverage", 0))
        liq_px_raw = raw.get("liquidationPx", p.get("liq"))
        liq_px = _as_float(liq_px_raw) if liq_px_raw is not None else 0.0

        raw_lev = raw.get("leverage", {})
        leverage = (
            {"type": raw_lev.get("type", "cross"), "value": _as_float(raw_lev.get("value", p.get("leverage", 0)))}
            if isinstance(raw_lev, dict)
            else {"type": "cross", "value": _as_float(raw_lev or p.get("leverage", 0))}
        )

        current_price = prices.get(coin)
        atr = atr_cache.get(coin)
        sl_px = sl_by_coin.get(coin)
        tp_px = tp_by_coin.get(coin)

        sl_distance = _dist(current_price, sl_px, atr)
        tp_distance = _dist(current_price, tp_px, atr)

        # Liq cushion: |current - liq| / current (always positive)
        liq_cushion_pct: Optional[float] = None
        liq_atrs: Optional[float] = None
        time_to_liq_atrs: Optional[float] = None
        if liq_px > 0 and current_price:
            dist_to_liq = abs(current_price - liq_px)
            liq_cushion_pct = round(dist_to_liq / current_price * 100, 2)
            if atr and atr > 0:
                liq_atrs = round(dist_to_liq / atr, 2)
                time_to_liq_atrs = liq_atrs  # = ATR multiples to liquidation

        # Entry timestamp + time held
        entry_ts: Optional[int] = None
        time_held_ms: Optional[int] = None
        coin_clean = coin.replace("xyz:", "")
        ws_pos = (
            ws_positions.get(coin)
            or ws_positions.get(coin_clean)
            or ws_positions.get(f"xyz:{coin_clean}")
        )
        if ws_pos and isinstance(ws_pos, dict):
            entry_ts = ws_pos.get("entry_ts") or ws_pos.get("opened_at_ms")
            if entry_ts:
                time_held_ms = now_ms - int(entry_ts)

        result_positions.append(
            {
                "coin": coin,
                "szi": _as_str(size),
                "entryPx": _as_str(entry),
                "currentPx": round(current_price, 4) if current_price else None,
                "positionValue": _as_str(pos_value),
                "marginUsed": _as_str(margin_used),
                "unrealizedPnl": _as_str(upnl),
                "returnOnEquity": _as_str(roe),
                "leverage": leverage,
                "maxLeverage": max_leverage,
                "liquidationPx": _as_str(liq_px) if liq_px > 0 else None,
                "liq_cushion_pct": liq_cushion_pct,
                "liq_atrs": liq_atrs,
                "time_to_liq_atrs": time_to_liq_atrs,
                "sl_px": round(sl_px, 4) if sl_px else None,
                "sl_distance": sl_distance,
                "tp_px": round(tp_px, 4) if tp_px else None,
                "tp_distance": tp_distance,
                "atr": round(atr, 4) if atr else None,
                "sweep_risk": sweep_risk_global,
                "dex": p.get("dex", "native"),
                "wallet": p.get("account_label", p.get("account_role", "main")),
                "entry_ts": entry_ts,
                "time_held_ms": time_held_ms,
            }
        )

    return {"positions": result_positions}


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
