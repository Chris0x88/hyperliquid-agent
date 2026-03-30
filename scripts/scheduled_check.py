#!/usr/bin/env python3
"""Scheduled task runner — collects all mechanical data for the AI to evaluate.

Run from agent-cli/: python scripts/scheduled_check.py

Outputs a compact JSON summary of everything the AI needs to make decisions.
The AI reads this output, does research, makes conviction calls, writes ThesisState.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    result = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "timestamp_ms": int(time.time() * 1000),
    }

    # --- 1. Calendar context ---
    try:
        from common.calendar import CalendarContext
        cal = CalendarContext.get_current("data/calendar")
        result["calendar"] = cal.to_prompt()
    except Exception as e:
        result["calendar"] = f"ERROR: {e}"

    # --- 2. Account state ---
    try:
        import requests
        from common.credentials import resolve_private_key
        from eth_account import Account

        key = resolve_private_key(venue="hl")
        account = Account.from_key(key)
        addr = account.address
        url = "https://api.hyperliquid.xyz/info"

        # Native HL
        native = requests.post(url, json={"type": "clearinghouseState", "user": addr}, timeout=10).json()
        margin = native.get("marginSummary", {})
        native_equity = float(margin.get("accountValue", 0))

        # Spot
        spot = requests.post(url, json={"type": "spotClearinghouseState", "user": addr}, timeout=10).json()
        spot_usdc = sum(float(b.get("total", 0)) for b in spot.get("balances", []) if b.get("coin") == "USDC")

        # xyz dex (BRENTOIL)
        xyz = requests.post(url, json={"type": "clearinghouseState", "user": addr, "dex": "xyz"}, timeout=10).json()
        xyz_equity = float(xyz.get("marginSummary", {}).get("accountValue", 0))

        # xyz open orders
        xyz_orders = requests.post(url, json={"type": "openOrders", "user": addr, "dex": "xyz"}, timeout=10).json()

        total_equity = native_equity + xyz_equity + spot_usdc

        result["account"] = {
            "native_equity": round(native_equity, 2),
            "xyz_equity": round(xyz_equity, 2),
            "spot_usdc": round(spot_usdc, 2),
            "total_equity": round(total_equity, 2),
            "address": addr,
        }

        # --- 3. BRENTOIL position ---
        oil_pos = None
        for ap in xyz.get("assetPositions", []):
            p = ap.get("position", ap)
            coin = p.get("coin", "")
            # API returns "xyz:BRENTOIL" or "BRENTOIL" depending on context
            if "BRENTOIL" in coin and float(p.get("szi", 0)) != 0:
                oil_pos = p
                break

        if oil_pos:
            szi = float(oil_pos["szi"])
            entry_px = float(oil_pos["entryPx"])
            liq_px = float(oil_pos.get("liquidationPx") or 0)
            upnl = float(oil_pos.get("unrealizedPnl", 0))
            lev_data = oil_pos.get("leverage") or {}
            leverage = float(lev_data.get("value", 10))

            mids = requests.post(url, json={"type": "allMids"}, timeout=10).json()
            # Try both "BRENTOIL" and "xyz:BRENTOIL" keys
            current_price = float(mids.get("BRENTOIL", mids.get("xyz:BRENTOIL", entry_px)))
            liq_dist_pct = abs(current_price - liq_px) / current_price * 100 if liq_px > 0 else 999

            has_sl = any(
                o.get("orderType") == "Stop Market" and "BRENTOIL" in o.get("coin", "")
                for o in xyz_orders
            )
            has_tp = any(
                o.get("orderType") == "Take Profit Market" and "BRENTOIL" in o.get("coin", "")
                for o in xyz_orders
            )

            existing_sl_price = None
            for o in xyz_orders:
                if o.get("orderType") == "Stop Market" and "BRENTOIL" in o.get("coin", ""):
                    existing_sl_price = float(o.get("triggerPx", o.get("limitPx", 0)))
                    break

            result["brentoil"] = {
                "size": szi,
                "entry": entry_px,
                "current_price": current_price,
                "upnl": round(upnl, 2),
                "liq_price": liq_px,
                "liq_dist_pct": round(liq_dist_pct, 1),
                "leverage": leverage,
                "has_sl": has_sl,
                "sl_price": existing_sl_price,
                "target_sl": round(liq_px * 1.02, 2) if liq_px > 0 else None,
                "has_tp": has_tp,
            }

            # CRITICAL ALERTS
            alerts = []
            if not has_sl:
                alerts.append("CRITICAL: NO EXCHANGE SL — SET IMMEDIATELY")
            if liq_dist_pct < 5:
                alerts.append(f"CRITICAL: liq distance {liq_dist_pct:.1f}% — REDUCE NOW")
            elif liq_dist_pct < 8:
                alerts.append(f"WARNING: liq distance {liq_dist_pct:.1f}%")
            if existing_sl_price and liq_px > 0:
                target_sl = liq_px * 1.02
                drift = abs(existing_sl_price - target_sl) / target_sl if target_sl > 0 else 0
                if drift > 0.02:
                    alerts.append(f"SL DRIFT: current ${existing_sl_price:.2f} vs target ${target_sl:.2f}")
            result["alerts"] = alerts
        else:
            result["brentoil"] = None
            result["alerts"] = []

        # --- 4. Funding rate ---
        try:
            meta = requests.post(url, json={"type": "metaAndAssetCtxs", "dex": "xyz"}, timeout=10).json()
            # Find BRENTOIL in the asset contexts
            if isinstance(meta, list) and len(meta) > 1:
                for asset_ctx in meta[1]:
                    if isinstance(asset_ctx, dict) and asset_ctx.get("coin") == "BRENTOIL":
                        result["brentoil_funding"] = float(asset_ctx.get("funding", 0))
                        break
        except Exception:
            pass

    except Exception as e:
        result["account_error"] = str(e)

    # --- 5. Existing thesis state ---
    try:
        from common.thesis import ThesisState
        states = ThesisState.load_all("data/thesis")
        for market, s in states.items():
            key_name = market.replace(":", "_").replace("-", "_").lower()
            result[f"thesis_{key_name}"] = {
                "conviction": s.conviction,
                "effective_conviction": s.effective_conviction(),
                "direction": s.direction,
                "age_hours": round(s.age_hours, 1),
                "stale": s.is_stale,
            }
    except Exception as e:
        result["thesis_error"] = str(e)

    # --- 6. Recent learnings ---
    try:
        lf = "data/research/learnings.md"
        if os.path.exists(lf):
            with open(lf) as f:
                content = f.read()
            result["recent_learnings"] = content[-1500:] if len(content) > 1500 else content
    except Exception:
        pass

    # --- 7. HWM + drawdown ---
    try:
        hwm_file = "data/snapshots/hwm.json"
        if os.path.exists(hwm_file):
            with open(hwm_file) as f:
                hwm = json.load(f)
            result["hwm"] = hwm.get("hwm", 0)
            equity = result.get("account", {}).get("total_equity", 0)
            if hwm.get("hwm", 0) > 0 and equity > 0:
                result["drawdown_pct"] = round((hwm["hwm"] - equity) / hwm["hwm"] * 100, 1)
    except Exception:
        pass

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
