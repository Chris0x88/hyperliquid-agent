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

        # xyz open orders — use frontendOpenOrders which correctly includes
        # orderType for trigger orders (openOrders shows them as plain "limit")
        xyz_orders = requests.post(url, json={"type": "frontendOpenOrders", "user": addr, "dex": "xyz"}, timeout=10).json()

        # xyz market data: metaAndAssetCtxs gives us markPx, funding, OI in one call
        # NOTE: allMids does NOT include xyz markets. This is the correct endpoint.
        xyz_meta = requests.post(url, json={"type": "metaAndAssetCtxs", "dex": "xyz"}, timeout=10).json()
        xyz_universe = xyz_meta[0].get("universe", []) if isinstance(xyz_meta, list) and len(xyz_meta) > 0 and isinstance(xyz_meta[0], dict) else []
        xyz_asset_ctxs = xyz_meta[1] if isinstance(xyz_meta, list) and len(xyz_meta) > 1 else []

        # Build name→index lookup for xyz markets
        xyz_prices = {}   # coin_name -> markPx
        xyz_funding = {}  # coin_name -> funding rate
        for i, asset_info in enumerate(xyz_universe):
            name = asset_info.get("name", "")   # e.g. "xyz:BRENTOIL"
            short_name = name.replace("xyz:", "")  # e.g. "BRENTOIL"
            if i < len(xyz_asset_ctxs):
                ctx = xyz_asset_ctxs[i]
                mark = float(ctx.get("markPx", 0))
                fund = float(ctx.get("funding", 0))
                xyz_prices[name] = mark
                xyz_prices[short_name] = mark
                xyz_funding[name] = fund
                xyz_funding[short_name] = fund

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

            # Use xyz_prices from metaAndAssetCtxs (allMids does NOT include xyz markets)
            current_price = xyz_prices.get("BRENTOIL", xyz_prices.get("xyz:BRENTOIL", entry_px))
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

            funding = xyz_funding.get("BRENTOIL", xyz_funding.get("xyz:BRENTOIL", 0))
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
                "funding_rate": funding,
                "funding_annualized_pct": round(funding * 8760 * 100, 2),
                "funding_direction": "longs earn" if funding < 0 else "longs pay",
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

        # --- 4. Funding rate (already fetched from xyz_meta above) ---
        brentoil_funding = xyz_funding.get("BRENTOIL", xyz_funding.get("xyz:BRENTOIL"))
        if brentoil_funding is not None:
            result["brentoil_funding"] = brentoil_funding
            result["brentoil_funding_annualized_pct"] = round(brentoil_funding * 8760 * 100, 2)

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

    # --- 6. Market research context (README + recent notes + memory timeline) ---
    # This is the "memory" layer — ensures temporal accuracy and accumulated knowledge
    # are always in context. Prevents errors like confusing "military campaign duration"
    # with "strait closure duration" because the README explicitly states key dates.
    try:
        import glob as _glob
        from pathlib import Path

        market_context = {}

        markets_dir = Path("data/research/markets")
        if markets_dir.exists():
            for market_dir in sorted(markets_dir.iterdir()):
                if not market_dir.is_dir():
                    continue
                market_name = market_dir.name  # e.g. "xyz_brentoil", "btc"
                ctx_parts = []

                # Load README (key thesis, dates, physical facts)
                readme = market_dir / "README.md"
                if readme.exists():
                    content = readme.read_text()
                    ctx_parts.append(f"### {market_name.upper()} README\n{content[:3000]}")

                # Load recent notes (last 7 days by filename date prefix YYYY-MM-DD)
                notes_dir = market_dir / "notes"
                if notes_dir.exists():
                    # Sort by filename — YYYY-MM-DD prefix gives chronological order
                    note_files = sorted(notes_dir.glob("*.md"), reverse=True)[:3]
                    for nf in reversed(note_files):
                        note_content = nf.read_text()
                        ctx_parts.append(
                            f"### NOTE: {nf.name}\n{note_content[:1500]}"
                        )

                if ctx_parts:
                    market_context[market_name] = "\n\n".join(ctx_parts)

        if market_context:
            result["market_research"] = market_context

    except Exception as e:
        result["market_research_error"] = str(e)

    # --- 6b. SQLite memory timeline ---
    try:
        from common.memory import get_market_context as _mem_ctx
        mem = {}
        for mk in ["xyz:BRENTOIL", "BTC-PERP"]:
            ctx = _mem_ctx(mk, days=60)
            if ctx:
                mem[mk] = ctx
        if mem:
            result["memory_context"] = mem
    except Exception:
        pass

    # --- 6c. Recent operational learnings (markdown log) ---
    try:
        lf = "data/research/learnings.md"
        if os.path.exists(lf):
            with open(lf) as f:
                content = f.read()
            result["recent_learnings"] = content[-1500:] if len(content) > 1500 else content
    except Exception:
        pass

    # --- 7. Open issues ---
    try:
        from common.issues import get_open_issues
        open_issues = get_open_issues()
        if open_issues:
            result["open_issues"] = [
                {"severity": i.severity, "category": i.category, "title": i.title}
                for i in open_issues[:10]  # max 10
            ]
            result["open_issues_count"] = len(open_issues)
    except Exception:
        pass

    # --- 8. HWM + drawdown ---
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

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["json", "digest", "harness"], default="json")
    parser.add_argument("--market", default=None, help="Single market for harness mode")
    parser.add_argument("--budget", type=int, default=4000, help="Token budget for harness mode")
    args = parser.parse_args()

    if args.format == "harness":
        # ── NEW: Context harness mode ──
        # Uses relevance-scored, token-budgeted context assembly
        # instead of flat-dumping everything.
        try:
            from common.context_harness import build_thesis_context, build_multi_market_context
            from common.market_snapshot import build_snapshot, render_snapshot
            from modules.candle_cache import CandleCache

            # Build market snapshots if candle data is available
            snapshot_texts = {}
            try:
                cache = CandleCache()
                markets = [args.market] if args.market else ["xyz:BRENTOIL", "BTC-PERP"]
                for mk in markets:
                    price = 0.0
                    # Try to get price from result
                    if "brentoil" in mk.lower() and result.get("brentoil"):
                        price = result["brentoil"].get("current_price", 0)
                    snap = build_snapshot(mk, cache, current_price=price)
                    snapshot_texts[mk] = render_snapshot(snap, detail="standard")
                cache.close()
            except Exception as e:
                log_msg = f"Candle cache unavailable for snapshots: {e}"
                # Silently continue — snapshots are enhancement, not required

            if args.market:
                # Single market mode
                thesis_key = args.market.replace(":", "_").replace("-", "_").lower()
                current_thesis = result.get(f"thesis_{thesis_key}")
                ctx = build_thesis_context(
                    market=args.market,
                    account_state=result,
                    market_snapshot_text=snapshot_texts.get(args.market),
                    current_thesis=current_thesis,
                    alerts=result.get("alerts"),
                    token_budget=args.budget,
                )
            else:
                # Multi-market mode
                markets = ["xyz:BRENTOIL", "BTC-PERP"]
                ctx = build_multi_market_context(
                    markets=markets,
                    account_state=result,
                    market_snapshots=snapshot_texts,
                    token_budget=args.budget,
                )

            print(ctx.text)
            print(f"\n--- ASSEMBLY META ---")
            print(f"Included: {ctx.blocks_included}")
            print(f"Dropped: {ctx.blocks_dropped}")
            print(f"Tokens: ~{ctx.estimated_tokens} ({ctx.budget_used_pct}% of budget)")

        except ImportError as e:
            print(f"ERROR: Context harness not available: {e}", file=sys.stderr)
            print(json.dumps(result, indent=2))

    elif args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        # Generate human-readable / AI-readable digest
        lines = []
        lines.append(f"📆 **Market Time**: {result.get('timestamp')}")
        
        try:
            from cli.telegram_handler import get_whitelist
            wl = get_whitelist()
            lines.append(f"🛡️ **Active Whitelist**: {', '.join(wl)}")
        except Exception:
            pass

        acc = result.get('account', {})
        if acc:
            lines.append(f"💰 **Equity**: ${acc.get('total_equity', 0):,.2f} (Main: ${acc.get('native_equity',0):.2f}, Vault: ${acc.get('xyz_equity',0):.2f})")
        
        if result.get("drawdown_pct"):
            lines.append(f"📉 **Drawdown**: {result['drawdown_pct']}% from HWM")

        oil = result.get("brentoil")
        if oil:
            stat = f"🛢️ **BRENTOIL**: {oil['size']} @ ${oil['entry']:.2f} (Current: ${oil['current_price']:.2f}, uPnL: ${oil['upnl']:.2f})"
            stat += f"\n  - Liq: ${oil['liq_price']:.2f} ({oil['liq_dist_pct']}% away) | Lev: {oil['leverage']}x"
            stat += f"\n  - SL: {'🟢 ' + str(oil['sl_price']) if oil['has_sl'] else '🔴 NONE'} | TP: {'🟢 Yes' if oil['has_tp'] else '🔴 NONE'}"
            stat += f"\n  - Funding: {oil['funding_rate']:.5f} ({oil['funding_annualized_pct']}% ann, {oil['funding_direction']})"
            lines.append(stat)
        
        if result.get("alerts"):
            lines.append(f"⚠️ **ALERTS**:")
            for a in result["alerts"]:
                lines.append(f"  - {a}")
                
        if result.get("open_issues_count"):
            lines.append(f"🚨 **Open Issues**: {result['open_issues_count']}")
            for issue in result.get("open_issues", []):
                lines.append(f"  - [{issue['severity']}] {issue['title']}")

        thesis_keys = [k for k in result.keys() if k.startswith("thesis_") and k != "thesis_error"]
        if thesis_keys:
            lines.append("🧠 **Active Theses**:")
            for tk in thesis_keys:
                t = result[tk]
                lines.append(f"  - {tk.replace('thesis_', '')}: Conviction {t['conviction']:.2f} ({t['direction']}) [Age: {t['age_hours']}h]")

        print("\n".join(lines))

if __name__ == "__main__":
    main()
