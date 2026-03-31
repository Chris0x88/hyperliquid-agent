"""Core heartbeat position auditor — stops, escalation, spike/dip, funding, trading hours.

All functions except ``run_heartbeat()`` are pure and testable without mocks.
``run_heartbeat()`` is the sole entry point that touches external systems
(HL API, Telegram, SQLite).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from common.heartbeat_config import (
    HeartbeatConfig,
    ProfitRules,
    SpikeConfig,
)
from common.heartbeat_state import (
    WorkingState,
    load_working_state,
    save_working_state,
)

log = logging.getLogger("heartbeat")

_ET = ZoneInfo("America/New_York")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. compute_stop_price
# ═══════════════════════════════════════════════════════════════════════════════

def compute_stop_price(
    entry: float,
    side: str,
    atr: float,
    multiplier: float = 3.0,
    current_price: Optional[float] = None,
    min_distance_pct: float = 2.0,
    liq_price: Optional[float] = None,
    liq_buffer_pct: float = 3.0,
) -> float:
    """Compute a stop-loss price from ATR, respecting min-distance and liquidation buffer.

    For longs the stop is below price; for shorts it is above.
    The returned value is the *most conservative* (safest) stop that satisfies
    all constraints — i.e. furthest from current price.

    Args:
        entry: Position entry price.
        side: ``"long"`` or ``"short"``.
        atr: Current Average True Range value.
        multiplier: ATR multiplier for base stop distance.
        current_price: Live price (used for min-distance constraint).
        min_distance_pct: Minimum distance from *current_price* as a percentage.
        liq_price: Liquidation price (used for liq-buffer constraint).
        liq_buffer_pct: Minimum buffer above/below liquidation as a percentage.

    Returns:
        The computed stop price.
    """
    is_long = side.lower() == "long"

    # Base ATR stop
    if is_long:
        atr_stop = entry - (multiplier * atr)
    else:
        atr_stop = entry + (multiplier * atr)

    stop = atr_stop

    # Min-distance constraint: stop must be at least min_distance_pct away
    if current_price is not None:
        if is_long:
            # Stop must be at or below current_price * (1 - pct)
            min_dist_stop = current_price * (1 - min_distance_pct / 100)
            stop = min(stop, min_dist_stop)
        else:
            # Stop must be at or above current_price * (1 + pct)
            min_dist_stop = current_price * (1 + min_distance_pct / 100)
            stop = max(stop, min_dist_stop)

    # Liquidation buffer constraint: stop must stay away from liq price
    if liq_price is not None:
        if is_long:
            # Stop must NOT be below this floor
            liq_floor = liq_price * (1 + liq_buffer_pct / 100)
            stop = max(stop, liq_floor)
        else:
            # Stop must NOT be above this ceiling
            liq_ceil = liq_price * (1 - liq_buffer_pct / 100)
            stop = min(stop, liq_ceil)

    return stop


# ═══════════════════════════════════════════════════════════════════════════════
# 2. check_liq_distance
# ═══════════════════════════════════════════════════════════════════════════════

def check_liq_distance(liq_distance_pct: float, config: HeartbeatConfig) -> str:
    """Return escalation level based on distance to liquidation.

    Args:
        liq_distance_pct: Percentage distance from current price to liquidation.
        config: Heartbeat configuration with escalation thresholds.

    Returns:
        ``"L0"`` (safe), ``"L1"`` (alert), ``"L2"`` (deleverage), or ``"L3"`` (emergency).
    """
    esc = config.escalation
    if liq_distance_pct >= esc.liq_L1_alert_pct:
        return "L0"
    if liq_distance_pct >= esc.liq_L2_deleverage_pct:
        return "L1"
    if liq_distance_pct >= esc.liq_L3_emergency_pct:
        return "L2"
    return "L3"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. check_drawdown
# ═══════════════════════════════════════════════════════════════════════════════

def check_drawdown(
    current_equity: float,
    session_peak: float,
    config: HeartbeatConfig,
) -> str:
    """Return escalation level based on drawdown from session peak.

    Args:
        current_equity: Current account equity.
        session_peak: Session peak equity.
        config: Heartbeat configuration with drawdown thresholds.

    Returns:
        ``"L0"`` through ``"L3"`` escalation level string.
    """
    if session_peak <= 0:
        return "L0"
    drawdown_pct = (session_peak - current_equity) / session_peak * 100
    esc = config.escalation
    if drawdown_pct < esc.drawdown_L1_pct:
        return "L0"
    if drawdown_pct < esc.drawdown_L2_pct:
        return "L1"
    if drawdown_pct < esc.drawdown_L3_pct:
        return "L2"
    return "L3"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. detect_spike_or_dip
# ═══════════════════════════════════════════════════════════════════════════════

def detect_spike_or_dip(
    current_price: float,
    last_price: float,
    side: str,
    spike_threshold_pct: float = 3.0,
    dip_threshold_pct: float = 2.0,
) -> dict:
    """Detect whether price moved enough to be a spike or dip relative to position side.

    Spike = price moved *in favor* of position; dip = *against*.

    Args:
        current_price: Current market price.
        last_price: Previous price observation.
        side: ``"long"`` or ``"short"``.
        spike_threshold_pct: Minimum move % for a spike.
        dip_threshold_pct: Minimum move % for a dip.

    Returns:
        ``{"type": "spike"|"dip"|"none", "pct": float}``
    """
    if last_price == 0:
        return {"type": "none", "pct": 0.0}

    change_pct = abs(current_price - last_price) / last_price * 100
    is_long = side.lower() == "long"
    price_went_up = current_price > last_price

    favorable = (is_long and price_went_up) or (not is_long and not price_went_up)

    if favorable and change_pct >= spike_threshold_pct:
        return {"type": "spike", "pct": change_pct}
    if not favorable and change_pct >= dip_threshold_pct:
        return {"type": "dip", "pct": change_pct}
    return {"type": "none", "pct": change_pct}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. should_take_profit
# ═══════════════════════════════════════════════════════════════════════════════

def should_take_profit(
    upnl_pct: float,
    position_age_min: float,
    rules: ProfitRules,
    current_size: Optional[float] = None,
    min_size: float = 2,
) -> dict:
    """Decide whether to take partial profit.

    Checks quick-profit and extended-profit windows. If ``current_size`` is
    provided the function also verifies the remaining position would not drop
    below ``min_size``.

    Args:
        upnl_pct: Unrealised PnL as a percentage of entry.
        position_age_min: How long the position has been open (minutes).
        rules: Profit-taking rules.
        current_size: Current position size in contracts (optional).
        min_size: Minimum position size to keep.

    Returns:
        ``{"take": bool, "take_pct": float, "reason": str}``
    """
    take_pct = 0.0
    reason = ""

    # Check quick profit first
    if upnl_pct >= rules.quick_profit_pct and position_age_min <= rules.quick_profit_window_min:
        take_pct = rules.quick_profit_take_pct
        reason = f"Quick profit: {upnl_pct:.1f}% in {position_age_min:.0f}min"
    # Then extended profit
    elif upnl_pct >= rules.extended_profit_pct and position_age_min <= rules.extended_profit_window_min:
        take_pct = rules.extended_profit_take_pct
        reason = f"Extended profit: {upnl_pct:.1f}% in {position_age_min:.0f}min"
    else:
        return {"take": False, "take_pct": 0.0, "reason": "No profit trigger met"}

    # Size guard
    if current_size is not None:
        remaining = current_size * (1 - take_pct / 100)
        if remaining < min_size:
            return {
                "take": False,
                "take_pct": 0.0,
                "reason": f"Would leave {remaining:.1f} < min_size {min_size}",
            }

    return {"take": True, "take_pct": take_pct, "reason": reason}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. should_add_on_dip
# ═══════════════════════════════════════════════════════════════════════════════

def should_add_on_dip(
    liq_distance_pct: float,
    daily_drawdown_pct: float,
    last_add_ms: int,
    now_ms: int,
    config: SpikeConfig,
) -> bool:
    """Decide whether it is safe to add to a position on a dip.

    All conditions must pass:
    - Liquidation distance >= minimum threshold
    - Daily drawdown <= maximum allowed
    - Cooldown period elapsed since last add

    Args:
        liq_distance_pct: Current distance to liquidation (%).
        daily_drawdown_pct: Today's drawdown from peak (%).
        last_add_ms: Epoch-ms of last position add.
        now_ms: Current epoch-ms.
        config: Spike/dip configuration.

    Returns:
        ``True`` if adding is permitted.
    """
    if liq_distance_pct < config.dip_add_min_liq_pct:
        return False
    if daily_drawdown_pct > config.dip_add_max_drawdown_pct:
        return False
    cooldown_ms = config.dip_add_cooldown_min * 60 * 1000
    if (now_ms - last_add_ms) < cooldown_ms:
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 7. check_funding_rate
# ═══════════════════════════════════════════════════════════════════════════════

def check_funding_rate(
    current_rate: float,
    recent_rates: list[float],
    position_notional: float,
    cumulative_pct: float = 0.0,
) -> dict:
    """Check whether funding rates warrant an alert.

    Alerts when:
    - The last 3 rates all exceed 0.1% (0.001 as decimal), OR
    - Cumulative funding drag exceeds 1%.

    Args:
        current_rate: Most recent funding rate (decimal, e.g. 0.001 = 0.1%).
        recent_rates: Last N funding rates (newest last).
        position_notional: Position notional value in USD.
        cumulative_pct: Cumulative funding paid as a percentage.

    Returns:
        ``{"alert": bool, "message": str}``
    """
    HIGH_RATE_THRESHOLD = 0.001  # 0.1%
    CUMULATIVE_THRESHOLD = 1.0   # 1%

    # Check last 3 rates
    last_3 = recent_rates[-3:] if len(recent_rates) >= 3 else recent_rates
    all_high = len(last_3) >= 3 and all(r > HIGH_RATE_THRESHOLD for r in last_3)

    # Check cumulative
    high_cumulative = cumulative_pct > CUMULATIVE_THRESHOLD

    if all_high:
        daily_drag = current_rate * position_notional * 3  # 3 funding periods/day
        return {
            "alert": True,
            "message": (
                f"High funding: last 3 rates all > 0.1%. "
                f"Est. daily drag: ${daily_drag:.2f}"
            ),
        }

    if high_cumulative:
        return {
            "alert": True,
            "message": (
                f"Cumulative funding drag {cumulative_pct:.2f}% exceeds 1% threshold"
            ),
        }

    return {"alert": False, "message": "Funding rates normal"}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. is_oil_market_open
# ═══════════════════════════════════════════════════════════════════════════════

def is_oil_market_open(dt: Optional[datetime] = None) -> bool:
    """Check whether the oil futures market is open.

    Oil trades Sunday 6 PM ET through Friday 5 PM ET, with a daily
    maintenance break (ignored here for simplicity).

    Args:
        dt: Datetime to check (UTC-aware). Defaults to now.

    Returns:
        ``True`` if the market is open.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    et = dt.astimezone(_ET)
    weekday = et.weekday()  # Mon=0 .. Sun=6
    hour = et.hour

    # Saturday: always closed
    if weekday == 5:
        return False

    # Sunday: open from 6 PM ET onward
    if weekday == 6:
        return hour >= 18

    # Friday: open until 5 PM ET
    if weekday == 4:
        return hour < 17

    # Monday-Thursday: open all day (within the Sun-Fri window)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 9. resolve_escalation
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_escalation(levels: list[str]) -> str:
    """Return the highest escalation level from a list.

    Ordering: L3 > L2 > L1 > L0.

    Args:
        levels: List of escalation level strings.

    Returns:
        The highest level, or ``"L0"`` if list is empty.
    """
    if not levels:
        return "L0"
    order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    return max(levels, key=lambda x: order.get(x, 0))


# ═══════════════════════════════════════════════════════════════════════════════
# 10. fetch_with_retry
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_with_retry(
    fn: Callable[[], Any],
    retries: int = 3,
    delay_ms: int = 100,
) -> Any:
    """Call *fn* with retry logic.

    Args:
        fn: Zero-argument callable to invoke.
        retries: Maximum number of attempts.
        delay_ms: Milliseconds to sleep between retries.

    Returns:
        The return value of *fn*, or ``None`` if all retries fail.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            log.warning(
                "fetch_with_retry attempt %d/%d failed: %s",
                attempt, retries, exc,
            )
            if attempt < retries and delay_ms > 0:
                time.sleep(delay_ms / 1000)

    log.error("fetch_with_retry: all %d attempts failed. Last error: %s", retries, last_exc)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 11. run_heartbeat (orchestrator — the ONLY function that does I/O)
# ═══════════════════════════════════════════════════════════════════════════════

def run_heartbeat(
    config: HeartbeatConfig,
    dry_run: bool = False,
    state_path: Optional[str] = None,
) -> dict:
    """Top-level heartbeat orchestrator.

    This is the **only** function that touches external systems: HL API,
    Telegram, and SQLite.

    Steps:
        1. Load working state
        2. Fetch account state from HL API (via fetch_with_retry)
        3. For each position: compute liq distance, check stops, check profit,
           check spike/dip
        4. Check drawdown
        5. Resolve escalation (highest from all checks)
        6. If not dry_run: execute actions (place stops, take profit, deleverage)
        7. Send Telegram alerts for any actions taken or escalation changes
        8. Log actions to action_log table
        9. Log execution trace
        10. Save working state
        11. Return summary dict

    Args:
        config: Heartbeat configuration.
        dry_run: If ``True``, compute everything but skip trade execution and Telegram.
        state_path: Path to working-state JSON. ``None`` uses the default.

    Returns:
        Summary dict with keys: ``escalation``, ``actions``, ``positions``,
        ``errors``, ``dry_run``.
    """
    # Lazy imports — only this function touches I/O modules
    from common.memory import _conn
    from common.memory_telegram import send_telegram, format_position_summary

    start_ms = int(time.time() * 1000)
    errors: list[str] = []
    actions: list[dict] = []
    position_summaries: list[dict] = []
    escalation_levels: list[str] = []

    # 1. Load working state
    kw = {"path": state_path} if state_path else {}
    state = load_working_state(**kw)

    # 2. Fetch account state (placeholder — real HL API call goes here)
    account_state = fetch_with_retry(lambda: _fetch_account_state(config), retries=3, delay_ms=500)
    if account_state is None:
        errors.append("Failed to fetch account state after 3 retries")
        state.heartbeat_consecutive_failures += 1
        save_working_state(state, **(kw or {}))
        return {
            "escalation": "L0",
            "actions": [],
            "positions": [],
            "errors": errors,
            "dry_run": dry_run,
        }

    state.heartbeat_consecutive_failures = 0
    now_ms = int(time.time() * 1000)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Update session peak
    equity = account_state.get("equity", 0)
    state.maybe_reset_peak(today_str, equity)

    # 4. Check drawdown
    dd_level = check_drawdown(equity, state.session_peak_equity, config)
    escalation_levels.append(dd_level)

    # 3. For each position
    positions = account_state.get("positions", [])
    for pos in positions:
        coin = pos.get("coin", "?")
        side = pos.get("side", "long")
        entry = pos.get("entry_price", 0)
        size = pos.get("size", 0)
        current_price = pos.get("current_price", entry)
        liq_price = pos.get("liq_price")
        upnl_pct = pos.get("upnl_pct", 0)
        position_age_min = pos.get("position_age_min", 0)
        notional = pos.get("notional", 0)
        atr_val = pos.get("atr", 0)

        pos_summary = {"coin": coin, "side": side, "size": size, "entry": entry}

        # Liq distance
        if liq_price and current_price:
            liq_dist = abs(current_price - liq_price) / current_price * 100
        else:
            liq_dist = 100.0  # No liq info => assume safe

        liq_level = check_liq_distance(liq_dist, config)
        escalation_levels.append(liq_level)
        pos_summary["liq_distance_pct"] = liq_dist
        pos_summary["liq_level"] = liq_level

        # Spike/dip detection
        last_price = state.last_prices.get(coin, current_price)
        spike_dip = detect_spike_or_dip(
            current_price, last_price, side,
            spike_threshold_pct=config.spike_config.spike_profit_threshold_pct,
            dip_threshold_pct=config.spike_config.dip_threshold_pct,
        )
        pos_summary["spike_dip"] = spike_dip
        state.last_prices[coin] = current_price

        # Profit check
        canonical_id = _find_canonical_id(coin, config)
        profit_rules = config.get_profit_rules(canonical_id)
        profit_check = should_take_profit(upnl_pct, position_age_min, profit_rules, current_size=size)
        pos_summary["profit_check"] = profit_check

        if profit_check["take"] and not dry_run:
            actions.append({
                "market": coin,
                "action": "take_profit",
                "take_pct": profit_check["take_pct"],
                "reason": profit_check["reason"],
            })

        # Dip add check
        if spike_dip["type"] == "dip":
            dd_pct = (state.session_peak_equity - equity) / max(state.session_peak_equity, 1) * 100
            last_add = state.last_add_ms.get(coin, 0)
            if should_add_on_dip(liq_dist, dd_pct, last_add, now_ms, config.spike_config):
                pos_summary["dip_add"] = True
                if not dry_run:
                    actions.append({
                        "market": coin,
                        "action": "dip_add",
                        "add_pct": config.spike_config.dip_add_pct,
                    })
                    state.last_add_ms[coin] = now_ms

        # Stop price
        if atr_val > 0:
            stop = compute_stop_price(
                entry=entry, side=side, atr=atr_val,
                current_price=current_price, liq_price=liq_price,
            )
            pos_summary["stop_price"] = stop

        position_summaries.append(pos_summary)

    # 5. Resolve escalation
    final_escalation = resolve_escalation(escalation_levels)
    prev_escalation = state.escalation_level

    # 6. Deleverage actions for L2/L3
    if final_escalation in ("L2", "L3") and not dry_run:
        actions.append({
            "action": "deleverage",
            "level": final_escalation,
            "reason": f"Escalation reached {final_escalation}",
        })

    state.escalation_level = final_escalation
    state.last_updated_ms = now_ms

    # 7. Telegram alerts
    if not dry_run and (actions or final_escalation != prev_escalation):
        try:
            msg_parts = [f"Heartbeat [{final_escalation}]"]
            if final_escalation != prev_escalation:
                msg_parts.append(f"Escalation: {prev_escalation} -> {final_escalation}")
            for a in actions:
                msg_parts.append(f"Action: {a.get('action')} {a.get('market', '')} — {a.get('reason', '')}")
            send_telegram("\n".join(msg_parts))
        except Exception as exc:
            errors.append(f"Telegram send failed: {exc}")

    # 8. Log actions to action_log
    if not dry_run and actions:
        try:
            con = _conn()
            for a in actions:
                con.execute(
                    "INSERT INTO action_log (timestamp_ms, market, action_type, detail, source) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (now_ms, a.get("market", "PORTFOLIO"), a["action"],
                     json.dumps(a), "heartbeat"),
                )
            con.commit()
            con.close()
        except Exception as exc:
            errors.append(f"action_log write failed: {exc}")

    # 9. Log execution trace
    duration_ms = int(time.time() * 1000) - start_ms
    if not dry_run:
        try:
            con = _conn()
            con.execute(
                "INSERT INTO execution_traces "
                "(timestamp_ms, process, duration_ms, success, actions_taken, errors) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (now_ms, "heartbeat", duration_ms,
                 1 if not errors else 0,
                 json.dumps(actions), json.dumps(errors) if errors else None),
            )
            con.commit()
            con.close()
        except Exception as exc:
            errors.append(f"execution_trace write failed: {exc}")

    # 10. Save working state
    save_working_state(state, **(kw or {}))

    # 11. Return summary
    return {
        "escalation": final_escalation,
        "actions": actions,
        "positions": position_summaries,
        "errors": errors,
        "dry_run": dry_run,
        "duration_ms": duration_ms,
    }


# ── Internal helpers (used only by run_heartbeat) ─────────────────────────────

def _fetch_account_state(config: HeartbeatConfig) -> dict:
    """Fetch account state from HL API. Placeholder for real implementation.

    Returns a dict with keys: equity, positions (list of position dicts).
    Each position dict has: coin, side, entry_price, size, current_price,
    liq_price, upnl_pct, position_age_min, notional, atr.
    """
    # This will be wired to the real HL adapter in a later task.
    # For now, raise so that fetch_with_retry returns None in tests.
    raise NotImplementedError("HL API adapter not yet wired")


def _find_canonical_id(coin: str, config: HeartbeatConfig) -> str:
    """Map an HL coin name back to its canonical market id."""
    for market_id, mapping in config.markets.items():
        if mapping.hl_coin == coin:
            return market_id
    return coin
