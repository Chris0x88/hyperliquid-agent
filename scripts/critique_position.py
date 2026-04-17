#!/usr/bin/env python3
"""One-shot trade entry critic — runs the same grading the daemon iterator
does, on demand, for any open position. Persists the critique row to
data/research/entry_critiques.jsonl exactly like the iterator would.

Why this exists:
  - The daemon iterator (`daemon/iterators/entry_critic.py`) only sees
    positions it sees in `ctx.positions`. If the daemon hasn't restarted
    since the multi-wallet account_state fix, it's still consuming a
    main-only position list — so vault positions (the BTC vault long, in
    particular) never get critiqued.
  - This script reads positions from the SAME source the dashboard uses
    (`fetch_registered_account_state`) so it sees ALL wallets correctly.
  - Output is identical to the iterator's: same grade, same JSONL row,
    same Telegram-style summary.

Usage:
  scripts/critique_position.py                # critique every open position
  scripts/critique_position.py --coin BTC     # critique just BTC
  scripts/critique_position.py --coin SILVER  # critique just SILVER
  scripts/critique_position.py --dry-run      # print but don't persist

The fingerprint dedup that the iterator uses is also honoured — running
twice on the same entry won't write duplicate rows.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Resolve project root so common.* imports work
_AGENT = Path(__file__).resolve().parent.parent
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from common.account_state import fetch_registered_account_state  # noqa: E402
from engines.protection.entry_critic import (  # noqa: E402
    SignalStack,
    format_critique_jsonl,
    format_critique_telegram,
    gather_signal_stack,
    grade_entry,
)

CRITIQUES_JSONL = _AGENT / "data" / "research" / "entry_critiques.jsonl"
STATE_PATH = _AGENT / "data" / "daemon" / "entry_critic_state.json"


def _load_fingerprints() -> set:
    if not STATE_PATH.exists():
        return set()
    try:
        return set(json.loads(STATE_PATH.read_text()).get("fingerprints", []))
    except Exception:
        return set()


def _save_fingerprints(fps: set) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"fingerprints": sorted(fps)}, indent=2))


def _fingerprint(p: dict) -> str:
    """Match daemon iterator fingerprint shape: instrument | direction |
    rounded entry | rounded entry_ts_sec."""
    return "|".join([
        str(p.get("instrument", "")),
        str(p.get("direction", "")),
        f"{round(float(p.get('entry_price', 0)), 2)}",
        f"{int(float(p.get('entry_ts_ms', 0))) // 1000}",
    ])


def _bundle_position_to_critic_dict(p: dict, equity: float) -> dict:
    """Map common.account_state position dict → entry_critic input shape."""
    size = float(p.get("size") or 0)
    direction = "long" if size > 0 else "short"
    entry = float(p.get("entry") or 0)
    qty = abs(size)
    notional = entry * qty
    leverage_raw = p.get("leverage")
    try:
        leverage = float(leverage_raw) if leverage_raw not in (None, "?") else None
    except (TypeError, ValueError):
        leverage = None
    liq = p.get("liq")
    try:
        liq_price = float(liq) if liq is not None else None
    except (TypeError, ValueError):
        liq_price = None
    return {
        "instrument": p["coin"],
        "direction": direction,
        "entry_price": entry,
        "entry_qty": qty,
        # The bundle doesn't carry an entry_ts — we don't have it from the HL
        # API on a per-position basis. Use 0 here; the gather path tolerates
        # missing entry_ts (catalyst window will return empty list).
        "entry_ts_ms": 0,
        "leverage": leverage,
        "notional_usd": notional,
        "liquidation_price": liq_price,
        "equity_usd": equity,
    }


def _persist_jsonl(row: dict) -> None:
    CRITIQUES_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with CRITIQUES_JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def _enrich_critique(p: dict, grade, equity: float, all_positions_by_coin: dict) -> tuple[list[str], dict]:
    """Build extra actionable observations for the critique using live data.

    The base entry_critic engine is oil/PM-focused — it returns mostly
    UNKNOWN/NO_THESIS for crypto. This adds concrete numbers that ARE
    available regardless of asset class:
      - Position size as % of equity (concentration risk)
      - Liquidation cushion in %, $ and ATRs (overnight survivability)
      - Funding rate vs position direction (carry cost)
      - Technical state: RSI 1h/4h/1d, BB squeeze flag, vs-VWAP, vs-EMA200
      - Market session (US / Asia / EU / weekend) — operator wants to know
        which session he's exposed across

    Returns (extra_suggestions, enriched_dict). The suggestions list gets
    appended to grade.suggestions (which the chart card surfaces). The
    enriched_dict is added to the JSONL row under key "enriched" so the
    full numbers persist for the dashboard.
    """
    suggestions: list[str] = []
    enriched: dict = {}

    coin = p.get("instrument", "").replace("xyz:", "")
    side = p.get("direction", "").lower()
    is_long = side == "long"
    entry = float(p.get("entry_price") or 0)
    qty = float(p.get("entry_qty") or 0)
    notional = float(p.get("notional_usd") or 0)
    liq = p.get("liquidation_price")
    leverage = p.get("leverage")

    # ── Concentration ──
    if equity > 0 and notional > 0:
        notional_pct = notional / equity * 100
        enriched["notional_pct_of_equity"] = round(notional_pct, 1)
        if notional_pct > 200:
            suggestions.append(f"Position notional {notional_pct:.0f}% of equity — high concentration; one move kills the account.")
        elif notional_pct > 100:
            suggestions.append(f"Position notional {notional_pct:.0f}% of equity — leveraged but bounded.")
        elif notional_pct > 50:
            suggestions.append(f"Position notional {notional_pct:.0f}% of equity — meaningful exposure.")

    # ── Live mark price + liquidation cushion in % AND ATRs ──
    mark_price = None
    try:
        from agent.tool_functions import live_price
        prices = live_price(coin)
        if "prices" in prices:
            for k, v in prices["prices"].items():
                # match either bare or xyz: form
                if k.replace("xyz:", "").upper() == coin.upper():
                    mark_price = float(v)
                    break
    except Exception:
        pass
    if mark_price:
        enriched["mark_price"] = mark_price

    if liq and float(liq) > 0 and mark_price:
        liq_f = float(liq)
        cushion_pct = abs((mark_price - liq_f) / mark_price * 100)
        cushion_usd = abs(mark_price - liq_f) * qty
        enriched["liq_cushion_pct"] = round(cushion_pct, 2)
        enriched["liq_cushion_usd"] = round(cushion_usd, 2)
        if cushion_pct < 3:
            suggestions.append(f"⚠ Liq cushion only {cushion_pct:.1f}% (${cushion_usd:.0f}) — one bad print = liquidation.")
        elif cushion_pct < 6:
            suggestions.append(f"Liq cushion {cushion_pct:.1f}% (${cushion_usd:.0f}) — thin for an overnight hold.")

    # ── Technicals via market_snapshot ──
    try:
        from engines.data.candle_cache import CandleCache
        from engines.analysis.market_snapshot import build_snapshot
        cache = CandleCache()
        if mark_price:
            snap = build_snapshot(coin, cache, mark_price, intervals=["1h", "4h", "1d"])
            tf_summary = []
            for iv in ["1h", "4h", "1d"]:
                tfd = snap.timeframes.get(iv)
                if not tfd or not tfd.trend:
                    continue
                rsi = float(tfd.trend.rsi or 0)
                tf_summary.append({"tf": iv, "rsi": round(rsi, 1), "atr_pct": round(tfd.atr_pct or 0, 2)})
                # ATRs to liq
                if liq and float(liq) > 0 and tfd.atr_value and iv == "1d":
                    atrs_to_liq = abs(mark_price - float(liq)) / tfd.atr_value
                    enriched["atrs_to_liq_1d"] = round(atrs_to_liq, 2)
                    if atrs_to_liq < 1.5:
                        suggestions.append(f"⚠ Only {atrs_to_liq:.1f} 1d-ATRs to liq — a single average daily move = stopout.")
                    elif atrs_to_liq < 3:
                        suggestions.append(f"{atrs_to_liq:.1f} 1d-ATRs to liq — within normal vol range.")
                # RSI extremes
                if iv == "4h":
                    if is_long and rsi >= 75:
                        suggestions.append(f"4h RSI {rsi:.0f} — overbought entering a LONG; chasing the move.")
                    elif is_long and rsi <= 30:
                        suggestions.append(f"4h RSI {rsi:.0f} — oversold; counter-trend or knife-catch.")
                    elif (not is_long) and rsi <= 25:
                        suggestions.append(f"4h RSI {rsi:.0f} — oversold entering a SHORT; chasing the move.")
            enriched["timeframes"] = tf_summary
            # BB squeeze flag from snapshot
            for f in (snap.flags or []):
                if "squeeze" in f.lower():
                    enriched.setdefault("flags", []).append(f)
                    suggestions.append(f"BB squeeze ({f}) — vol expansion likely; direction unknown.")
                if "bullish_div" in f.lower() and is_long:
                    suggestions.append(f"Bullish divergence ({f}) — supports the long.")
                if "bearish_div" in f.lower() and not is_long:
                    suggestions.append(f"Bearish divergence ({f}) — supports the short.")
    except Exception as exc:
        enriched["technicals_error"] = str(exc)[:120]

    # ── Funding rate (live HL API) ──
    try:
        from agent.tool_functions import check_funding
        funding = check_funding(coin)
        if isinstance(funding, dict) and "funding_rate" in funding:
            fr = float(funding["funding_rate"] or 0)  # per-hour fraction
            annualized = fr * 24 * 365 * 100
            enriched["funding_pct_annualized"] = round(annualized, 2)
            adverse = (is_long and fr > 0) or ((not is_long) and fr < 0)
            mag = abs(annualized)
            if adverse and mag > 50:
                suggestions.append(f"⚠ Funding {annualized:+.1f}%/yr against {side.upper()} — bleed > 50%/yr.")
            elif adverse and mag > 20:
                suggestions.append(f"Funding {annualized:+.1f}%/yr against {side.upper()} — meaningful carry cost.")
            elif (not adverse) and mag > 20:
                suggestions.append(f"Funding {annualized:+.1f}%/yr in your favour — paid to hold.")
    except Exception:
        pass

    # ── Session context ──
    try:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        h = now.hour
        wd = now.weekday()
        # Brisbane = UTC+10
        local_h = (h + 10) % 24
        is_weekend = wd >= 5 or (wd == 4 and h >= 22) or (wd == 0 and h < 22)
        if is_weekend:
            suggestions.append(f"Entered during WEEKEND session — thin liq, sweep risk elevated.")
        # Brisbane evening / overnight = US session
        if 18 <= local_h or local_h < 6:
            enriched["session_at_entry"] = "brisbane_overnight (US active)"
        elif 6 <= local_h < 14:
            enriched["session_at_entry"] = "brisbane_morning (Asia + early EU)"
        else:
            enriched["session_at_entry"] = "brisbane_afternoon (EU active)"
    except Exception:
        pass

    return suggestions, enriched


def critique_one(p: dict, equity: float, all_positions_by_coin: dict, *, dry_run: bool = False, force: bool = False) -> None:
    """Run the full critic on one position dict (already in critic shape)."""
    fp = _fingerprint(p)
    seen = _load_fingerprints()
    if fp in seen and not force:
        print(f"\n[SKIP] {p['instrument']} {p['direction']} — already critiqued (fingerprint dedup). Use --force to re-run.")
        return

    print(f"\n══════ CRITIQUE: {p['instrument']} {p['direction'].upper()} ══════")
    stack: SignalStack = gather_signal_stack(p)
    grade = grade_entry(stack)

    # Telegram-formatted summary (the same one the daemon would have sent)
    print(format_critique_telegram(grade, stack))

    # Enrich with live technicals + funding + position health (asset-class
    # agnostic; works for crypto where the oil/PM-focused engine returns
    # mostly UNKNOWN). Append the new observations to grade.suggestions so
    # the chart card and Telegram both see them automatically.
    extra_suggestions, enriched = _enrich_critique(p, grade, equity, all_positions_by_coin)
    if extra_suggestions:
        # grade.suggestions is a list[str] on the dataclass — extend in place.
        try:
            grade.suggestions.extend(extra_suggestions)
        except Exception:
            pass
        print("\n--- ENRICHED OBSERVATIONS ---")
        for s in extra_suggestions:
            print(f"  • {s}")
    if enriched:
        print("\n--- ENRICHED DATA ---")
        for k, v in enriched.items():
            print(f"  {k}: {v}")

    if dry_run:
        print("\n[DRY-RUN] not persisting to entry_critiques.jsonl")
        return

    row = format_critique_jsonl(grade, stack)
    if enriched:
        row["enriched"] = enriched
    _persist_jsonl(row)
    seen.add(fp)
    _save_fingerprints(seen)
    print(f"\n[OK] critique persisted to {CRITIQUES_JSONL.relative_to(_AGENT)} (1 row)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--coin", help="Critique only this coin (matches with or without xyz: prefix)")
    ap.add_argument("--dry-run", action="store_true", help="Print but don't persist")
    ap.add_argument("--force", action="store_true", help="Re-run even if fingerprint already in state")
    args = ap.parse_args()

    bundle = fetch_registered_account_state()
    positions = bundle.get("positions", [])
    if not positions:
        print("No open positions found.")
        return 0

    equity = float(bundle.get("account", {}).get("total_equity") or 0)

    target_coin = (args.coin or "").upper().replace("XYZ:", "")
    targets = []
    for p in positions:
        coin_norm = p["coin"].upper().replace("XYZ:", "")
        if not target_coin or coin_norm == target_coin:
            targets.append(p)

    if not targets:
        print(f"No open position matched coin filter: {args.coin}")
        return 1

    print(f"Found {len(targets)} position(s) to critique. Account total_equity: ${equity:,.2f}")
    by_coin = {p["coin"]: p for p in positions}
    for p in targets:
        critic_input = _bundle_position_to_critic_dict(p, equity)
        critique_one(critic_input, equity, by_coin, dry_run=args.dry_run, force=args.force)

    return 0


if __name__ == "__main__":
    sys.exit(main())
