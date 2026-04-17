"""Pure evaluator functions — one per checklist item.

Each function signature:
    evaluator(market: str, ctx: dict) -> EvalResult
    EvalResult = ("pass"|"warn"|"fail"|"skip", "one-line reason", optional_data)

ctx dict keys (populated by runner from live data):
    positions       list[dict]  — all open positions (account_state format)
    orders          list[dict]  — all open orders (frontendOpenOrders format)
    total_equity    float       — USD equity
    thesis          dict|None   — parsed thesis JSON for this market
    market_price    float|None  — current mid price
    atr             float|None  — 1-day ATR
    funding_rate    float|None  — current hourly funding rate (e.g. 0.000125)
    catalysts       list[dict]  — upcoming catalysts (from news/catalysts.jsonl)
    heatmap_zones   list[dict]  — recent zones from data/heatmap/zones.jsonl
    cascades        list[dict]  — recent cascades from data/heatmap/cascades.jsonl
    bot_patterns    list[dict]  — recent bot_patterns for this market
    closed_since    list[dict]  — positions closed in last 12-18h (from fill log)
    filled_orders   list[dict]  — orders filled in last 12-18h
    sweep_result    dict|None   — pre-computed detect_sweep_risk() output
    is_friday_brisbane bool     — whether it's Friday evening in Brisbane
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

EvalResult = Tuple[str, str, Optional[Dict[str, Any]]]

# ── Helpers ───────────────────────────────────────────────────


def _pos_for_market(market: str, positions: list) -> Optional[dict]:
    """Find position dict matching market (handles xyz: prefix)."""
    bare = market.replace("xyz:", "")
    for p in positions:
        coin = str(p.get("coin", ""))
        if coin == market or coin.replace("xyz:", "") == bare:
            return p
    return None


def _orders_for_market(market: str, orders: list) -> list:
    """Return orders whose coin matches market (handles xyz: prefix)."""
    bare = market.replace("xyz:", "")
    result = []
    for o in orders:
        coin = str(o.get("coin", ""))
        if coin == market or coin.replace("xyz:", "") == bare:
            result.append(o)
    return result


def _classify_order(o: dict) -> str:
    """Return 'sl', 'tp', or 'other'."""
    tpsl = o.get("tpsl", "")
    order_type = o.get("orderType", "")
    if tpsl == "sl" or order_type in ("Stop Market", "Stop Limit"):
        return "sl"
    if tpsl == "tp" or order_type in ("Take Profit Market", "Take Profit Limit"):
        return "tp"
    if o.get("reduceOnly") and tpsl not in ("sl",):
        return "tp"
    return "other"


# ── ① sl_on_exchange — FULLY IMPLEMENTED ─────────────────────


def eval_sl_on_exchange(market: str, ctx: dict) -> EvalResult:
    """FAIL if an open position has no stop-loss on exchange."""
    positions = ctx.get("positions", [])
    orders = ctx.get("orders", [])

    pos = _pos_for_market(market, positions)
    if pos is None:
        return ("skip", "No open position", None)

    mkt_orders = _orders_for_market(market, orders)
    has_sl = any(_classify_order(o) == "sl" for o in mkt_orders)

    if has_sl:
        return ("pass", "Stop-loss on exchange", None)

    size = float(pos.get("size", 0))
    direction = "LONG" if size > 0 else "SHORT"
    return ("fail", f"No SL on exchange — {direction} is UNPROTECTED overnight",
            {"coin": market, "direction": direction})


# ── ② tp_on_exchange — FULLY IMPLEMENTED ─────────────────────


def eval_tp_on_exchange(market: str, ctx: dict) -> EvalResult:
    """WARN if open position has no take-profit on exchange."""
    positions = ctx.get("positions", [])
    orders = ctx.get("orders", [])

    pos = _pos_for_market(market, positions)
    if pos is None:
        return ("skip", "No open position", None)

    mkt_orders = _orders_for_market(market, orders)
    has_tp = any(_classify_order(o) == "tp" for o in mkt_orders)

    if has_tp:
        return ("pass", "Take-profit on exchange", None)

    thesis = ctx.get("thesis") or {}
    tp_price = thesis.get("take_profit_price")
    hint = f" — thesis TP at ${tp_price:,.2f}" if tp_price else " — no thesis TP set"
    return ("warn", f"No TP on exchange{hint}", {"coin": market})


# ── ③ cumulative_risk — FULLY IMPLEMENTED ────────────────────


def eval_cumulative_risk(market: str, ctx: dict) -> EvalResult:
    """WARN at 8% open risk, FAIL at 10%.

    Open risk = sum of (margin_used) across all positions / total_equity.
    """
    positions = ctx.get("positions", [])
    total_equity = float(ctx.get("total_equity", 0))

    if total_equity <= 0:
        return ("skip", "Cannot compute — equity unknown", None)

    total_margin = sum(float(p.get("margin_used", 0)) for p in positions)
    risk_pct = total_margin / total_equity * 100

    data = {"total_margin_usd": round(total_margin, 2),
            "total_equity_usd": round(total_equity, 2),
            "open_risk_pct": round(risk_pct, 2)}

    if risk_pct >= 10.0:
        return ("fail",
                f"Open risk {risk_pct:.1f}% of equity — EXCEEDS 10% limit",
                data)
    if risk_pct >= 8.0:
        return ("warn",
                f"Open risk {risk_pct:.1f}% of equity — approaching 10% limit",
                data)
    return ("pass",
            f"Open risk {risk_pct:.1f}% of equity — within limits",
            data)


# ── ④ leverage_vs_thesis — FULLY IMPLEMENTED ─────────────────


def eval_leverage_vs_thesis(market: str, ctx: dict) -> EvalResult:
    """WARN if leverage 2-3x thesis recommended; FAIL if >3x."""
    positions = ctx.get("positions", [])
    thesis = ctx.get("thesis") or {}

    pos = _pos_for_market(market, positions)
    if pos is None:
        return ("skip", "No open position", None)

    recommended_lev = float(thesis.get("recommended_leverage", 0))
    if recommended_lev <= 0:
        return ("skip", "No thesis recommended_leverage to compare", None)

    actual_lev_raw = pos.get("leverage", "1")
    try:
        actual_lev = float(str(actual_lev_raw).replace("x", "").strip())
    except (ValueError, TypeError):
        return ("skip", f"Cannot parse leverage: {actual_lev_raw!r}", None)

    ratio = actual_lev / recommended_lev
    data = {"actual_leverage": actual_lev, "recommended_leverage": recommended_lev,
            "ratio": round(ratio, 2)}

    if ratio > 3.0:
        return ("fail",
                f"Leverage {actual_lev:.1f}x is >{3:.0f}x thesis ({recommended_lev:.1f}x) — DANGER",
                data)
    if ratio > 2.0:
        return ("warn",
                f"Leverage {actual_lev:.1f}x is 2-3x thesis ({recommended_lev:.1f}x) — elevated",
                data)
    return ("pass",
            f"Leverage {actual_lev:.1f}x within 2x of thesis ({recommended_lev:.1f}x)",
            data)


# ── ⑤ funding_cost — FULLY IMPLEMENTED ───────────────────────


def eval_funding_cost(market: str, ctx: dict) -> EvalResult:
    """WARN if annualised funding > 30%; FAIL if > 60%.

    Uses funding_rate from ctx (hourly rate). Annualized = rate * 8760.
    """
    funding_rate = ctx.get("funding_rate")
    if funding_rate is None:
        return ("skip", "Funding rate unavailable", None)

    positions = ctx.get("positions", [])
    pos = _pos_for_market(market, positions)
    if pos is None:
        return ("skip", "No open position", None)

    size = float(pos.get("size", 0))
    is_long = size > 0
    # Positive funding_rate means longs pay shorts.
    # For longs: cost is positive when rate > 0.
    # For shorts: cost is positive when rate < 0.
    effective_rate = funding_rate if is_long else -funding_rate
    # HL funding field is 8-hour rate (paid 3x/day = 1095x/year)
    annualized_pct = effective_rate * 3 * 365 * 100  # 8h rate -> annual %

    data = {
        "funding_rate_hourly": funding_rate,
        "annualized_pct": round(annualized_pct, 2),
        "direction": "long" if is_long else "short",
    }

    if annualized_pct > 60.0:
        return ("fail",
                f"Funding cost {annualized_pct:.1f}% annualised — EXCEEDS 60% threshold",
                data)
    if annualized_pct > 30.0:
        return ("warn",
                f"Funding cost {annualized_pct:.1f}% annualised — above 30% warn level",
                data)
    if annualized_pct < -5.0:
        # Receiving significant funding — positive signal
        return ("pass",
                f"Receiving funding {abs(annualized_pct):.1f}% annualised — tailwind",
                data)
    return ("pass",
            f"Funding cost {annualized_pct:.1f}% annualised — acceptable",
            data)


# ── ⑥ weekend_leverage — STUB (Phase 2.5) ────────────────────


def eval_weekend_leverage(market: str, ctx: dict) -> EvalResult:
    """FAIL if it's Friday Brisbane evening and position leverage > thesis weekend_leverage_cap."""
    is_friday = ctx.get("is_friday_brisbane", False)
    if not is_friday:
        return ("pass", "Not Friday evening — weekend cap N/A", None)

    positions = ctx.get("positions", [])
    thesis = ctx.get("thesis") or {}

    pos = _pos_for_market(market, positions)
    if pos is None:
        return ("skip", "No open position", None)

    weekend_cap = float(thesis.get("weekend_leverage_cap", 0))
    if weekend_cap <= 0:
        return ("skip", "No weekend_leverage_cap in thesis", None)

    actual_lev_raw = pos.get("leverage", "1")
    try:
        actual_lev = float(str(actual_lev_raw).replace("x", "").strip())
    except (ValueError, TypeError):
        return ("skip", f"Cannot parse leverage: {actual_lev_raw!r}", None)

    data = {"actual_leverage": actual_lev, "weekend_cap": weekend_cap}
    if actual_lev > weekend_cap:
        return ("fail",
                f"Friday: leverage {actual_lev:.1f}x EXCEEDS weekend cap {weekend_cap:.1f}x",
                data)
    return ("pass",
            f"Friday: leverage {actual_lev:.1f}x within weekend cap {weekend_cap:.1f}x",
            data)


# ── ⑦ news_catalyst_12h — STUB (Phase 2.5) ──────────────────


def eval_news_catalyst_12h(market: str, ctx: dict) -> EvalResult:
    """WARN if high-impact catalyst within 12h that could invalidate thesis."""
    # TODO Phase 2.5: parse catalysts list, match to thesis invalidation conditions,
    # check timestamp within 12h window.
    catalysts = ctx.get("catalysts", [])
    now = time.time()
    window = 12 * 3600

    relevant = []
    for c in catalysts:
        ts = c.get("timestamp", 0) or c.get("ts", 0)
        if isinstance(ts, str):
            try:
                import datetime
                ts = datetime.datetime.fromisoformat(ts).timestamp()
            except Exception:
                ts = 0
        severity = str(c.get("severity", "")).lower()
        market_str = str(c.get("market", "")).lower()
        bare = market.replace("xyz:", "").lower()
        in_window = 0 < (ts - now) < window
        is_relevant = bare in market_str or not market_str
        if in_window and is_relevant and severity in ("high", "critical"):
            relevant.append(c)

    if relevant:
        titles = "; ".join(c.get("title", "catalyst")[:40] for c in relevant[:2])
        return ("warn", f"{len(relevant)} high-impact catalyst(s) in next 12h: {titles}",
                {"count": len(relevant)})
    return ("pass", "No high-impact catalysts in next 12h", None)


# ── ⑧ sweep_risk — wired to sweep_detector ───────────────────


def eval_sweep_risk(market: str, ctx: dict) -> EvalResult:
    """WARN at score 1, FAIL at score 2-3."""
    sweep_result = ctx.get("sweep_result")
    if sweep_result is None:
        return ("skip", "Sweep detector not run or data unavailable", None)

    score = sweep_result.get("score", 0)
    flags = sweep_result.get("flags", [])
    reasoning = sweep_result.get("reasoning", "")
    data = {"score": score, "flags": flags}

    if score >= 2:
        flag_str = ", ".join(flags[:2]) if flags else reasoning
        return ("fail", f"Sweep risk ELEVATED (score {score}/3): {flag_str}", data)
    if score == 1:
        flag_str = flags[0] if flags else reasoning
        return ("warn", f"Sweep risk building (score 1/3): {flag_str}", data)
    return ("pass", "No sweep risk signals", data)


# ── Morning evaluators ────────────────────────────────────────


def eval_overnight_fills(market: str, ctx: dict) -> EvalResult:
    """Report what orders filled overnight. Informational."""
    filled = ctx.get("filled_orders", [])
    mkt_fills = [f for f in filled
                 if market.replace("xyz:", "") in str(f.get("coin", "")).replace("xyz:", "")]
    if not mkt_fills:
        return ("pass", "No fills overnight", None)
    sides = [f.get("side", "?") for f in mkt_fills]
    summary = f"{len(mkt_fills)} fills: {', '.join(sides)}"
    return ("pass", summary, {"fills": mkt_fills})


def eval_overnight_closed(market: str, ctx: dict) -> EvalResult:
    """Report any positions closed (SL/TP hit) overnight."""
    closed = ctx.get("closed_since", [])
    mkt_closed = [c for c in closed
                  if market.replace("xyz:", "") in str(c.get("coin", "")).replace("xyz:", "")]
    if not mkt_closed:
        return ("pass", "No positions closed overnight", None)
    reasons = [c.get("close_reason", "closed") for c in mkt_closed]
    return ("warn", f"Position(s) closed overnight: {', '.join(reasons)}",
            {"closed": mkt_closed})


def eval_cascade_events(market: str, ctx: dict) -> EvalResult:
    """Warn if liquidation cascades hit this market overnight."""
    cascades = ctx.get("cascades", [])
    bare = market.replace("xyz:", "")
    mkt_cascades = [
        c for c in cascades
        if bare in str(c.get("instrument", "")).replace("xyz:", "")
    ]
    if not mkt_cascades:
        return ("pass", "No cascade events overnight", None)
    total_notional = sum(float(c.get("notional_usd", 0)) for c in mkt_cascades)
    return ("warn",
            f"{len(mkt_cascades)} cascade event(s) overnight — ${total_notional / 1e6:.2f}M notional",
            {"count": len(mkt_cascades), "total_notional_usd": total_notional})


def eval_new_catalysts(market: str, ctx: dict) -> EvalResult:
    """Report new catalysts since last evening run."""
    # TODO Phase 2.5: diff catalysts since last_evening_ts stored in state
    catalysts = ctx.get("catalysts", [])
    if catalysts:
        return ("pass", f"{len(catalysts)} catalyst(s) tracked", {"count": len(catalysts)})
    return ("pass", "No catalysts to report", None)


def eval_pending_actions(market: str, ctx: dict) -> EvalResult:
    """Warn if there are pending decisions in action_queue for this market."""
    # TODO Phase 2.5: read data/research/action_queue.jsonl and filter by market
    return ("pass", "stub — pending actions check not yet wired", None)


def eval_asia_setup(market: str, ctx: dict) -> EvalResult:
    """Informational: current price vs yesterday's close for Asia setup."""
    price = ctx.get("market_price")
    if price is None:
        return ("skip", "Price unavailable for Asia setup", None)
    return ("pass", f"Current: ${price:,.4f} — review overnight range manually", None)


# ── Registry ──────────────────────────────────────────────────

EVALUATOR_REGISTRY: Dict[str, Any] = {
    "sl_on_exchange":    eval_sl_on_exchange,
    "tp_on_exchange":    eval_tp_on_exchange,
    "cumulative_risk":   eval_cumulative_risk,
    "leverage_vs_thesis": eval_leverage_vs_thesis,
    "weekend_leverage":  eval_weekend_leverage,
    "news_catalyst_12h": eval_news_catalyst_12h,
    "funding_cost":      eval_funding_cost,
    "sweep_risk":        eval_sweep_risk,
    # Morning
    "overnight_fills":   eval_overnight_fills,
    "overnight_closed":  eval_overnight_closed,
    "cascade_events":    eval_cascade_events,
    "new_catalysts":     eval_new_catalysts,
    "pending_actions":   eval_pending_actions,
    "asia_setup":        eval_asia_setup,
}
