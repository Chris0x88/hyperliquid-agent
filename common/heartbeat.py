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
    if liq_price is not None and liq_price > 0:
        if is_long:
            liq_floor = liq_price * (1 + liq_buffer_pct / 100)
            # Only apply if the floor is still below entry — never push stop above entry
            if liq_floor < entry:
                stop = max(stop, liq_floor)
        else:
            liq_ceil = liq_price * (1 - liq_buffer_pct / 100)
            if liq_ceil > entry:
                stop = min(stop, liq_ceil)

    # Final safety: NEVER place stop on the wrong side of entry
    if is_long and stop >= entry:
        # Stop above entry for a long = instant close. Skip stop placement.
        return 0.0  # Caller should check for 0 and skip
    if not is_long and stop <= entry:
        return 0.0

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

def account_risk_adjusted_escalation(
    raw_level: str,
    margin_used: float,
    account_equity: float,
    min_risk_pct: float = 15.0,
) -> str:
    """Downgrade escalation if the position is small relative to the account.

    If losing the entire margin would cost less than ``min_risk_pct`` of
    account equity, the position is not account-threatening and escalation
    is downgraded.

    Example: $50 margin on $600 account = 8.3% at risk.
    Even if liq distance is 5% (raw L3), losing the position is only 8.3%
    of equity — downgrade to L1 (alert only, don't panic-deleverage).

    Args:
        raw_level: The escalation level from liq_distance or drawdown check.
        margin_used: Margin allocated to this position in USD.
        account_equity: Total account equity in USD.
        min_risk_pct: Minimum account-risk % to keep the escalation level.
            Positions risking less than this get downgraded.

    Returns:
        Adjusted escalation level (may be lower than raw_level).
    """
    if account_equity <= 0 or margin_used <= 0:
        return raw_level

    risk_pct = (margin_used / account_equity) * 100

    if risk_pct >= min_risk_pct:
        return raw_level  # position IS material to the account — keep level

    # Downgrade: small position, don't panic
    downgrade = {"L3": "L1", "L2": "L1", "L1": "L0", "L0": "L0"}
    adjusted = downgrade.get(raw_level, raw_level)
    if adjusted != raw_level:
        log.info(
            "Escalation downgraded %s→%s: margin $%.0f is only %.1f%% of $%.0f equity",
            raw_level, adjusted, margin_used, risk_pct, account_equity,
        )
    return adjusted


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
    import requests as _req
    from common.heartbeat_state import compute_atr
    from common.thesis import ThesisState
    from common.conviction_engine import (
        conviction_to_target_pct,
        modulate_dip_add_pct,
        modulate_spike_take_pct,
        is_near_roll_window,
        can_execute_add,
    )

    start_ms = int(time.time() * 1000)
    errors: list[str] = []
    actions: list[dict] = []
    position_summaries: list[dict] = []
    escalation_levels: list[str] = []

    # 1. Load working state
    kw = {"path": state_path} if state_path else {}
    state = load_working_state(**kw)

    # 2. Fetch account state
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

    # Build trigger order lookup: coin → list of existing trigger orders
    trigger_orders = account_state.get("trigger_orders", [])
    existing_stops: dict[str, list] = {}
    for trig in trigger_orders:
        tcoin = trig.get("coin", "")
        existing_stops.setdefault(tcoin, []).append(trig)

    # ── Conviction Engine: load thesis states ────────────────────────────────
    conviction_enabled = config.conviction_bands.enabled
    thesis_states: dict = {}
    if conviction_enabled:
        try:
            thesis_states = ThesisState.load_all()
            state.last_thesis_load_ms = now_ms
            if thesis_states:
                log.info("Conviction engine: loaded %d thesis(es) — %s",
                         len(thesis_states),
                         ", ".join(f"{m}={t.effective_conviction():.2f}" for m, t in thesis_states.items()))
            # Thesis review reminders (once every 6h, not every cycle)
            review_cooldown_ms = 6 * 3600 * 1000
            last_review_alert = getattr(state, '_last_thesis_review_ms', 0)
            if now_ms - last_review_alert > review_cooldown_ms:
                for market, ts in thesis_states.items():
                    if ts.needs_review and not ts.is_stale:
                        age_d = ts.age_hours / 24
                        try:
                            send_telegram(
                                f"[Thesis Review] {market}: conviction {ts.conviction:.2f}, "
                                f"last reviewed {age_d:.1f}d ago. "
                                f"Run /thesis to confirm or update."
                            )
                            state._last_thesis_review_ms = now_ms
                        except Exception:
                            pass
        except Exception as e:
            log.warning("Failed to load thesis states: %s", e)
            conviction_enabled = False

    # 3. For each position
    positions = account_state.get("positions", [])
    for pos in positions:
        coin = pos.get("coin", "?")
        side = pos.get("side", "long")
        entry = pos.get("entry_price", 0)
        size = pos.get("size", 0)
        current_price = pos.get("current_price", entry)
        liq_price = pos.get("liq_price")
        liq_dist = pos.get("liq_distance_pct", 0)
        upnl_pct = pos.get("upnl_pct", 0)
        margin_used = pos.get("margin_used", 0)
        account_label = pos.get("account", "main")

        pos_summary = {"coin": coin, "side": side, "size": size, "entry": entry}

        # Liq distance (use pre-computed from API, fallback to 100 if no liq price)
        if liq_dist <= 0 and (not liq_price or liq_price <= 0):
            liq_dist = 100.0  # No liq info (cross-margin vault) => assume safe

        raw_liq_level = check_liq_distance(liq_dist, config)
        liq_level = account_risk_adjusted_escalation(raw_liq_level, margin_used, equity)
        escalation_levels.append(liq_level)
        pos_summary["liq_distance_pct"] = liq_dist
        pos_summary["liq_level"] = liq_level

        # Fetch ATR (cached for 1 hour in working state)
        atr_val = 0.0
        cache_key = coin
        cached = state.atr_cache.get(cache_key, {})
        if cached and (now_ms - cached.get("cached_at_ms", 0)) < config.atr_cache_seconds * 1000:
            atr_val = cached.get("value", 0)
        else:
            try:
                # Determine dex for candle query
                dex = None
                if coin.startswith("xyz:"):
                    dex = "xyz"
                candle_coin = coin
                end_ms = now_ms
                start_candle_ms = end_ms - (config.atr_period + 2) * 4 * 3600 * 1000
                payload = {
                    "type": "candleSnapshot",
                    "req": {"coin": candle_coin, "interval": config.atr_interval,
                            "startTime": start_candle_ms, "endTime": end_ms},
                }
                resp = _req.post("https://api.hyperliquid.xyz/info", json=payload, timeout=10)
                candles = resp.json()
                if isinstance(candles, list) and len(candles) >= 2:
                    atr_val = compute_atr(candles, period=config.atr_period) or 0.0
                    state.atr_cache[cache_key] = {"value": atr_val, "cached_at_ms": now_ms}
            except Exception as e:
                log.debug("ATR fetch failed for %s: %s", coin, e)

        # ── Thesis lookup (needed for TP placement below) ─────────────────
        canonical_id = _find_canonical_id(coin, config)
        # Try coin first (e.g. "xyz:GOLD"), then canonical_id (e.g. "BTC-PERP" for vault "BTC")
        thesis = None
        if conviction_enabled:
            thesis = thesis_states.get(coin) or thesis_states.get(canonical_id)

        # Check if stop-loss already exists on exchange
        has_stop = bool(existing_stops.get(coin))
        pos_summary["has_stop"] = has_stop

        # Compute stop price and place if needed
        if atr_val > 0 and not has_stop:
            stop = compute_stop_price(
                entry=entry, side=side, atr=atr_val,
                current_price=current_price, liq_price=liq_price if liq_price else None,
            )
            pos_summary["computed_stop"] = stop

            if stop <= 0:
                # Stop would be on wrong side of entry — position too close to liq for ATR stop
                log.info("Skipping stop for %s: ATR stop would be above entry (liq too close)", coin)
                pos_summary["stop_skipped"] = "liq_too_close_for_atr_stop"
            elif not dry_run:
                # Place the stop via HL Exchange API
                try:
                    from parent.hl_proxy import HLProxy
                    from cli.hl_adapter import DirectHLProxy

                    # Determine which proxy to use based on account
                    if account_label == "vault":
                        hl = HLProxy(testnet=False, vault_address=VAULT_ADDRESS)
                    else:
                        hl = HLProxy(testnet=False, account_address=MAIN_ACCOUNT)
                    proxy = DirectHLProxy(hl)

                    # Stop side is opposite of position: long pos → sell stop
                    stop_side = "sell" if side == "long" else "buy"
                    oid = proxy.place_trigger_order(
                        instrument=coin, side=stop_side,
                        size=size, trigger_price=round(stop, 2),
                    )
                    if oid:
                        actions.append({
                            "market": coin, "action": "stop_placed",
                            "stop_price": round(stop, 2), "oid": oid,
                            "reason": f"ATR-based stop ({config.atr_period}x{config.atr_interval}, 3x ATR=${atr_val:.2f})",
                        })
                        log.info("Placed stop on %s: %s @ $%.2f (OID %s)", coin, stop_side, stop, oid)
                    else:
                        errors.append(f"Stop placement returned no OID for {coin}")
                except Exception as e:
                    errors.append(f"Stop placement failed for {coin}: {e}")
                    log.warning("Failed to place stop for %s: %s", coin, e, exc_info=True)
        elif has_stop:
            pos_summary["existing_stop"] = "yes"

        # Take-profit order placement
        # - With thesis + TP price: use thesis target (e.g. gold→$10k)
        # - With thesis + no TP price: thesis controls exit, no mechanical TP
        # - No thesis at all: ALWAYS place mechanical TP (5x ATR above entry)
        tp_price = None
        tp_reason = ""
        if thesis and thesis.take_profit_price:
            tp_price = thesis.take_profit_price
            tp_reason = f"Thesis TP: {thesis.thesis_summary[:60]}"
        elif not thesis and atr_val > 0:
            # No thesis = unmanaged position. Set mechanical TP at 5x ATR from entry.
            if side == "long":
                tp_price = entry + (5.0 * atr_val)
            else:
                tp_price = entry - (5.0 * atr_val)
            tp_reason = f"Mechanical TP (no thesis): 5x ATR=${atr_val:.2f}"

        if tp_price and not dry_run:
            # Check if TP already exists for this coin (trigger above entry for longs)
            existing_tps = [
                t for t in existing_stops.get(coin, [])
                if (side == "long" and float(t.get("triggerPx", 0)) > entry)
                or (side != "long" and float(t.get("triggerPx", 0)) < entry)
            ]
            if not existing_tps:
                valid_tp = (side == "long" and tp_price > entry) or (side != "long" and tp_price < entry)
                if valid_tp:
                    try:
                        from parent.hl_proxy import HLProxy
                        from cli.hl_adapter import DirectHLProxy
                        if account_label == "vault":
                            hl = HLProxy(testnet=False, vault_address=VAULT_ADDRESS)
                        else:
                            hl = HLProxy(testnet=False, account_address=MAIN_ACCOUNT)
                        proxy = DirectHLProxy(hl)
                        tp_side = "sell" if side == "long" else "buy"
                        tp_oid = proxy.place_tp_trigger_order(
                            instrument=coin, side=tp_side,
                            size=size, trigger_price=round(tp_price, 2),
                        )
                        if tp_oid:
                            actions.append({
                                "market": coin, "action": "tp_placed",
                                "tp_price": round(tp_price, 2), "oid": tp_oid,
                                "reason": tp_reason,
                            })
                            log.info("Placed TP on %s: %s @ $%.2f (OID %s)", coin, tp_side, tp_price, tp_oid)
                    except Exception as e:
                        errors.append(f"TP placement failed for {coin}: {e}")
                        log.warning("Failed to place TP for %s: %s", coin, e, exc_info=True)
            else:
                pos_summary["existing_tp"] = "yes"

        # Spike/dip detection
        last_price = state.last_prices.get(coin, current_price)
        spike_dip = detect_spike_or_dip(
            current_price, last_price, side,
            spike_threshold_pct=config.spike_config.spike_profit_threshold_pct,
            dip_threshold_pct=config.spike_config.dip_threshold_pct,
        )
        pos_summary["spike_dip"] = spike_dip
        state.last_prices[coin] = current_price

        # Profit check (spike-based quick profit)
        profit_rules = config.get_profit_rules(canonical_id)
        # min_size: for high-value instruments (>$1000/contract), allow full close.
        # For cheap instruments (oil, silver), keep at least 1 contract.
        instrument_min_size = 0 if current_price > 1000 else 1
        profit_check = should_take_profit(upnl_pct, 0, profit_rules, current_size=size, min_size=instrument_min_size)
        pos_summary["profit_check"] = profit_check

        # ── Conviction Engine: modulation (thesis already loaded above) ────
        effective_conv = thesis.effective_conviction() if thesis else 0.0
        thesis_direction = thesis.direction if thesis else "flat"
        allow_tactical = thesis.allow_tactical_trades if thesis else False
        pos_summary["conviction"] = effective_conv
        pos_summary["thesis_direction"] = thesis_direction

        # Modulate thresholds by conviction
        adj_spike_take_pct = config.spike_config.spike_take_pct
        adj_dip_add_pct = config.spike_config.dip_add_pct
        if thesis and effective_conv > 0 and conviction_enabled:
            adj_spike_take_pct = modulate_spike_take_pct(config.spike_config.spike_take_pct, effective_conv)
            adj_dip_add_pct = modulate_dip_add_pct(config.spike_config.dip_add_pct, effective_conv)

        # Roll window: BRENTOIL monthly roll between 5th-10th bday
        near_roll = False
        if "BRENTOIL" in coin and is_near_roll_window():
            near_roll = True
            adj_dip_add_pct *= 0.5
            adj_spike_take_pct = min(adj_spike_take_pct * 1.5, 30.0)
            pos_summary["near_roll"] = True

        # Profit-take: fires for ALL positions when should_take_profit triggers.
        # With thesis: conviction modulates take size. Without thesis: uses base take_pct.
        if profit_check["take"] and not dry_run:
            mod_take_pct = modulate_spike_take_pct(profit_check["take_pct"], effective_conv) if (thesis and effective_conv > 0) else profit_check["take_pct"]
            take_size = round(size * mod_take_pct / 100, 6)

            if account_label == "vault" and not allow_tactical:
                pos_summary["profit_take_blocked"] = "vault tactical disabled"
            elif take_size >= 0.001:
                try:
                    from parent.hl_proxy import HLProxy
                    from cli.hl_adapter import DirectHLProxy
                    if account_label == "vault":
                        hl = HLProxy(testnet=False, vault_address=VAULT_ADDRESS)
                    else:
                        hl = HLProxy(testnet=False, account_address=MAIN_ACCOUNT)
                    proxy = DirectHLProxy(hl)
                    close_side = "sell" if side == "long" else "buy"
                    fill = proxy.place_order(
                        instrument=coin, side=close_side, size=take_size,
                        price=current_price, tif="Ioc",
                    )
                    if fill:
                        actions.append({
                            "market": coin, "action": "conviction_profit_take",
                            "size_closed": take_size, "price": current_price,
                            "conviction": effective_conv,
                            "reason": profit_check["reason"],
                        })
                        state.conviction_at_last_action[canonical_id] = effective_conv
                        log.info("Conviction profit-take %s: %.4f @ $%.2f (conv=%.2f)", coin, take_size, current_price, effective_conv)
                except Exception as e:
                    errors.append(f"Conviction profit take failed for {coin}: {e}")

        # Underweight flag (informational only)
        if conviction_enabled and thesis and effective_conv > 0.3:
            target_pct = conviction_to_target_pct(effective_conv, config.conviction_bands)
            target_notional = equity * target_pct
            current_notional = abs(size * current_price)
            if current_notional < target_notional * 0.7:
                pos_summary["underweight"] = True
                pos_summary["target_notional"] = round(target_notional, 2)
                pos_summary["current_notional"] = round(current_notional, 2)
            state.position_target_cache[canonical_id] = round(target_notional, 2)

        # Funding signal
        funding_rate = pos.get("funding_rate", 0.0)
        if thesis and funding_rate != 0:
            if thesis_direction == "long" and funding_rate < 0:
                pos_summary["funding_signal"] = "confirming"
            elif thesis_direction == "long" and funding_rate > 0.0005:
                pos_summary["funding_signal"] = "warning_carry_cost"

        if spike_dip["type"] == "spike" and spike_dip["pct"] >= config.spike_config.spike_profit_threshold_pct:
            take_pct = adj_spike_take_pct  # conviction-modulated
            take_size = round(size * take_pct / 100, 6)
            if take_size >= 0.001 and not dry_run:
                try:
                    from parent.hl_proxy import HLProxy
                    from cli.hl_adapter import DirectHLProxy
                    if account_label == "vault":
                        hl = HLProxy(testnet=False, vault_address=VAULT_ADDRESS)
                    else:
                        hl = HLProxy(testnet=False, account_address=MAIN_ACCOUNT)
                    proxy = DirectHLProxy(hl)
                    close_side = "sell" if side == "long" else "buy"
                    fill = proxy.place_order(
                        instrument=coin, side=close_side, size=take_size,
                        price=current_price, tif="Ioc",
                    )
                    if fill:
                        actions.append({
                            "market": coin, "action": "spike_profit",
                            "size_closed": take_size, "price": current_price,
                            "spike_pct": spike_dip["pct"],
                            "reason": f"Spike +{spike_dip['pct']:.1f}% detected, took {take_pct}%",
                        })
                except Exception as e:
                    errors.append(f"Spike profit-take failed for {coin}: {e}")

        # Dip add check — conviction engine activates actual execution
        if spike_dip["type"] == "dip":
            dd_pct = (state.session_peak_equity - equity) / max(state.session_peak_equity, 1) * 100
            last_add = state.last_add_ms.get(coin, 0)
            if should_add_on_dip(liq_dist, dd_pct, last_add, now_ms, config.spike_config):
                pos_summary["dip_add"] = True

                if conviction_enabled and not dry_run:
                    # Compute add size (conviction-modulated, capped at base dip_add_pct)
                    add_size = round(size * adj_dip_add_pct / 100, 6)
                    max_add = size * config.spike_config.dip_add_pct / 100
                    add_size = min(add_size, round(max_add, 6))
                    add_notional = add_size * current_price

                    # Total notional across all positions
                    total_notional = sum(
                        abs(p.get("size", 0) * p.get("current_price", 0))
                        for p in positions
                    )

                    current_esc = resolve_escalation(escalation_levels)
                    is_oil = "BRENTOIL" in coin or "OIL" in coin
                    is_vault_no_tac = (account_label == "vault" and not allow_tactical)

                    ok, block = can_execute_add(
                        thesis_exists=thesis is not None,
                        effective_conv=effective_conv,
                        escalation=current_esc,
                        is_oil=is_oil,
                        thesis_direction=thesis_direction,
                        is_vault_no_tactical=is_vault_no_tac,
                        total_notional=total_notional,
                        add_notional=add_notional,
                        equity=equity,
                        max_notional_pct=config.conviction_bands.max_total_notional_pct,
                    )

                    if ok and add_size >= 0.001:
                        try:
                            from parent.hl_proxy import HLProxy
                            from cli.hl_adapter import DirectHLProxy
                            hl = HLProxy(testnet=False, account_address=MAIN_ACCOUNT)
                            proxy = DirectHLProxy(hl)
                            add_side = "buy" if side == "long" else "sell"
                            fill = proxy.place_order(
                                instrument=coin, side=add_side, size=add_size,
                                price=current_price, tif="Ioc",
                            )
                            if fill:
                                actions.append({
                                    "market": coin, "action": "conviction_dip_add",
                                    "size_added": add_size, "price": current_price,
                                    "conviction": effective_conv,
                                    "reason": f"Dip add: conv={effective_conv:.2f}, adj_pct={adj_dip_add_pct:.1f}%",
                                })
                                state.last_add_ms[coin] = now_ms
                                state.conviction_at_last_action[canonical_id] = effective_conv
                                log.info("Conviction dip-add %s: +%.4f @ $%.2f (conv=%.2f)",
                                         coin, add_size, current_price, effective_conv)
                        except Exception as e:
                            errors.append(f"Conviction dip add failed for {coin}: {e}")
                    else:
                        pos_summary["dip_add_blocked"] = block or "size too small"
                elif not conviction_enabled and not dry_run:
                    # Phase 1 fallback: log but don't trade
                    actions.append({
                        "market": coin, "action": "dip_add_signal",
                        "add_pct": config.spike_config.dip_add_pct,
                        "reason": "Conviction engine disabled — signal only",
                    })
                    state.last_add_ms[coin] = now_ms

        position_summaries.append(pos_summary)

    # 5. Resolve escalation
    final_escalation = resolve_escalation(escalation_levels)
    prev_escalation = state.escalation_level

    # 6. Deleverage actions for L2/L3
    if final_escalation in ("L2", "L3") and not dry_run:
        for pos in positions:
            lev = pos.get("leverage", 1)
            if lev <= 1:
                continue  # can't deleverage below 1x
            target_lev = max(1, lev - config.escalation.liq_L2_deleverage_amount) if final_escalation == "L2" else config.escalation.liq_L3_target_leverage
            target_lev = max(1, min(target_lev, lev))
            if target_lev >= lev:
                continue
            account_label = pos.get("account", "main")
            coin = pos.get("coin", "")
            try:
                from parent.hl_proxy import HLProxy
                if account_label == "vault":
                    hl = HLProxy(testnet=False, vault_address=VAULT_ADDRESS)
                else:
                    hl = HLProxy(testnet=False, account_address=MAIN_ACCOUNT)
                hl._ensure_client()
                # xyz markets need the full "xyz:COIN" format for the SDK
                hl._exchange.update_leverage(int(target_lev), coin, is_cross=True)
                actions.append({
                    "market": coin, "action": "deleverage",
                    "prev_leverage": lev, "new_leverage": target_lev,
                    "level": final_escalation,
                    "reason": f"Escalation {final_escalation}: leverage {lev}x→{target_lev}x",
                })
                log.info("Delevered %s: %sx→%sx (%s)", coin, lev, target_lev, final_escalation)
            except Exception as e:
                errors.append(f"Deleverage failed for {coin}: {e}")
                log.warning("Deleverage failed for %s: %s", coin, e)

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

    # 9. Log execution trace — only if something happened (actions, new errors, or escalation change)
    duration_ms = int(time.time() * 1000) - start_ms
    something_happened = actions or (final_escalation != prev_escalation) or (errors and not state.heartbeat_consecutive_failures)
    if not dry_run and something_happened:
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


# ═══════════════════════════════════════════════════════════════════════════════
# 12. detect_btc_trade
# ═══════════════════════════════════════════════════════════════════════════════

def detect_btc_trade(current_position: dict, last_position: dict) -> dict:
    """Detect if BTC vault position changed between heartbeat runs.

    Args:
        current_position: Current position dict with at least ``size``.
        last_position: Previous position dict with at least ``size``.

    Returns:
        Dict with ``trade_detected`` bool and, if True, ``direction``,
        ``delta``, ``new_size``, ``entry``, ``mark``.
    """
    current_size = current_position.get("size", 0)
    last_size = last_position.get("size", 0)
    if abs(current_size - last_size) < 0.0001:
        return {"trade_detected": False}
    delta = current_size - last_size
    return {
        "trade_detected": True,
        "direction": "buy" if delta > 0 else "sell",
        "delta": abs(delta),
        "new_size": current_size,
        "entry": current_position.get("entry", 0),
        "mark": current_position.get("mark", 0),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 13. btc_liq_gate
# ═══════════════════════════════════════════════════════════════════════════════

def btc_liq_gate(
    liq_distance_pct: float,
    direction: str,
    min_liq_pct: float = 15.0,
) -> bool:
    """Gate BTC rebalance increases by liq distance. Reductions always allowed.

    Args:
        liq_distance_pct: Current distance to liquidation (%).
        direction: ``"buy"`` (position increase) or ``"sell"`` (reduction).
        min_liq_pct: Minimum liq distance required for buys.

    Returns:
        ``True`` if the trade is permitted.
    """
    if direction == "sell":
        return True  # reductions always ok
    return liq_distance_pct >= min_liq_pct


# ═══════════════════════════════════════════════════════════════════════════════
# 14. should_send_status_summary
# ═══════════════════════════════════════════════════════════════════════════════

def should_send_status_summary(
    last_summary_ms: int,
    now_ms: int,
    interval_hours: int = 6,
) -> bool:
    """True if it's been >= interval_hours since last status summary.

    Args:
        last_summary_ms: Epoch-ms of last summary sent. 0 means never sent.
        now_ms: Current epoch-ms.
        interval_hours: Minimum hours between summaries.

    Returns:
        ``True`` if a summary is due.
    """
    if last_summary_ms == 0:
        return True
    elapsed_ms = now_ms - last_summary_ms
    return elapsed_ms >= interval_hours * 3600 * 1000


# ── Internal helpers (used only by run_heartbeat) ─────────────────────────────

# Wallet addresses for multi-account monitoring
MAIN_ACCOUNT = "0x80B5801ce295C4D469F4C0C2e7E17bd84dF0F205"
VAULT_ADDRESS = "0x9da9a9aef5a968277b5ea66c6a0df7add49d98da"


def _parse_positions_from_raw(raw: dict, account_label: str) -> list[dict]:
    """Parse position dicts from raw HL clearinghouseState response.

    Follows Hummingbot's parsing pattern:
    - Side from sign of `szi` (positive=long, negative=short)
    - Leverage from `leverage.value`
    - Cumulative funding from `cumFunding`
    """
    positions = []
    for ap in raw.get("assetPositions", raw.get("positions", [])):
        pos_data = ap.get("position", ap) if isinstance(ap, dict) else ap
        szi = float(pos_data.get("szi", 0))
        if abs(szi) < 1e-9:
            continue

        entry_px = float(pos_data.get("entryPx", 0))
        coin = pos_data.get("coin", "")
        leverage_info = pos_data.get("leverage", {})
        leverage_val = float(leverage_info.get("value", 1)) if isinstance(leverage_info, dict) else float(leverage_info or 1)
        liq_px = float(pos_data.get("liquidationPx", 0) or 0)

        upnl = float(pos_data.get("unrealizedPnl", 0))
        notional = float(pos_data.get("positionValue", abs(szi) * entry_px))

        # Mark price: prefer positionValue / size (more accurate than uPnL back-calc)
        if notional > 0 and abs(szi) > 0:
            mark_px = notional / abs(szi)
        elif abs(szi) > 0 and entry_px > 0:
            mark_px = entry_px + (upnl / abs(szi)) if szi > 0 else entry_px - (upnl / abs(szi))
        else:
            mark_px = entry_px

        liq_distance_pct = 0.0
        if liq_px > 0 and mark_px > 0:
            if szi > 0:
                liq_distance_pct = (mark_px - liq_px) / mark_px * 100
            else:
                liq_distance_pct = (liq_px - mark_px) / mark_px * 100

        # PnL% relative to POSITION (entry notional), not account equity
        # This is what HL shows: (mark - entry) / entry * 100 * leverage_direction
        entry_notional = abs(szi) * entry_px
        upnl_pct = (upnl / entry_notional * 100) if entry_notional > 0 else 0
        # Also compute ROE (return on equity/margin used)
        margin = float(pos_data.get("marginUsed", 0))
        roe_pct = (upnl / margin * 100) if margin > 0 else 0

        # Cumulative funding from position data
        # NOTE: HL's cumFunding is from the exchange's perspective (opposite sign).
        # cumFunding.sinceOpen = -0.047 means the USER received +$0.047.
        # We negate to show the user's perspective: positive = you earned, negative = you paid.
        cum_funding = pos_data.get("cumFunding", {})
        raw_all_time = float(cum_funding.get("allTime", 0)) if isinstance(cum_funding, dict) else 0.0
        raw_since_open = float(cum_funding.get("sinceOpen", 0)) if isinstance(cum_funding, dict) else 0.0
        cum_funding_all_time = -raw_all_time  # negate: user's perspective
        cum_funding_since_open = -raw_since_open  # negate: user's perspective

        positions.append({
            "coin": coin,
            "side": "long" if szi > 0 else "short",
            "entry_price": entry_px,
            "size": abs(szi),
            "current_price": round(mark_px, 2),
            "liq_price": liq_px,
            "liq_distance_pct": round(liq_distance_pct, 2),
            "upnl": round(upnl, 2),
            "upnl_pct": round(upnl_pct, 2),  # PnL% vs position entry (not vs account)
            "roe_pct": round(roe_pct, 2),     # return on margin (what HL shows as ROE)
            "leverage": leverage_val,
            "notional": round(abs(notional), 2),
            "funding_rate": 0.0,  # current rate filled from metaAndAssetCtxs
            "cum_funding_since_open": round(cum_funding_since_open, 6),
            "cum_funding_all_time": round(cum_funding_all_time, 6),
            "margin_used": round(float(pos_data.get("marginUsed", 0)), 2),
            "account": account_label,
        })
    return positions


def _get_equity_from_state(raw: dict) -> float:
    """Extract account equity from clearinghouseState, using crossMarginSummary
    (total including cross margin) with fallback to marginSummary."""
    cross = raw.get("crossMarginSummary", {})
    if cross and float(cross.get("accountValue", 0)) > 0:
        return float(cross["accountValue"])
    margin = raw.get("marginSummary", {})
    return float(margin.get("accountValue", 0))


def _fetch_open_trigger_orders(address: str, dex: str = None) -> list[dict]:
    """Fetch open trigger orders (stops, take-profits) from HL frontendOpenOrders.

    This is the API that returns trigger orders — `openOrders` only returns limit orders.
    """
    import requests as _req
    payload: dict = {"type": "frontendOpenOrders", "user": address}
    if dex:
        payload["dex"] = dex
    try:
        resp = _req.post("https://api.hyperliquid.xyz/info", json=payload, timeout=10)
        orders = resp.json()
        if not isinstance(orders, list):
            return []
        # Filter for trigger orders (stop-loss / take-profit).
        # HL returns orderType="Stop Market" with isTrigger=True — NOT "Trigger" in orderType.
        trigger_orders = []
        for order in orders:
            order_type = order.get("orderType", "")
            if (
                order.get("isTrigger")
                or order.get("triggerCondition")
                or order.get("tpsl")
                or "Trigger" in str(order_type)
                or "Stop" in str(order_type)
            ):
                trigger_orders.append(order)
        return trigger_orders
    except Exception as e:
        log.debug("frontendOpenOrders query failed: %s", e)
        return []


def _fetch_funding_rates(dex: str = None) -> dict[str, float]:
    """Fetch current funding rates from metaAndAssetCtxs.

    Returns {coin: funding_rate} dict.
    """
    import requests as _req
    payload: dict = {"type": "metaAndAssetCtxs"}
    if dex:
        payload["dex"] = dex
    try:
        resp = _req.post("https://api.hyperliquid.xyz/info", json=payload, timeout=10)
        data = resp.json()
        # Response is [meta_dict, [asset_ctx_list]]
        if isinstance(data, list) and len(data) >= 2:
            meta = data[0]
            asset_ctxs = data[1]
            universe = meta.get("universe", [])
            rates = {}
            for i, ctx in enumerate(asset_ctxs):
                if i < len(universe):
                    coin = universe[i].get("name", "")
                    funding = float(ctx.get("funding", 0))
                    rates[coin] = funding
            return rates
    except Exception as e:
        log.debug("metaAndAssetCtxs query failed: %s", e)
    return {}


def _fetch_account_state(config: HeartbeatConfig) -> dict:
    """Fetch account state from BOTH wallets on HL API.

    Checks:
      - Main account (0x80B5...) — oil positions
      - Vault (0x9da9...) — BTC positions

    Returns a dict with keys: main_equity, vault_equity, total_equity,
    positions (combined list from both accounts).
    """
    from parent.hl_proxy import HLProxy
    from cli.hl_adapter import DirectHLProxy

    all_positions = []
    main_equity = 0.0
    vault_equity = 0.0

    import requests as _req

    # 1. Fetch main account — default clearinghouse
    try:
        resp = _req.post("https://api.hyperliquid.xyz/info", json={
            "type": "clearinghouseState", "user": MAIN_ACCOUNT
        }, timeout=10)
        raw_main = resp.json()
        main_equity = _get_equity_from_state(raw_main)
        all_positions.extend(_parse_positions_from_raw(raw_main, "main"))
    except Exception as e:
        log.warning("Main account default clearinghouse failed: %s", e)

    # 2. Fetch main account — xyz clearinghouse (oil positions)
    try:
        resp = _req.post("https://api.hyperliquid.xyz/info", json={
            "type": "clearinghouseState", "user": MAIN_ACCOUNT, "dex": "xyz"
        }, timeout=10)
        xyz_data = resp.json()
        xyz_equity = _get_equity_from_state(xyz_data)
        if xyz_equity > 0:
            main_equity += xyz_equity
        xyz_positions = _parse_positions_from_raw(xyz_data, "main_xyz")
        all_positions.extend(xyz_positions)
        if xyz_positions:
            log.info("Found %d xyz position(s)", len(xyz_positions))
    except Exception as e:
        log.debug("XYZ clearinghouse query failed: %s", e)

    # 3. Fetch spot balances (USDC may be idle in spot)
    try:
        resp = _req.post("https://api.hyperliquid.xyz/info", json={
            "type": "spotClearinghouseState", "user": MAIN_ACCOUNT
        }, timeout=10)
        spot_data = resp.json()
        spot_usdc = 0.0
        for bal in spot_data.get("balances", []):
            if bal.get("coin") == "USDC":
                spot_usdc = float(bal.get("total", 0))
        if spot_usdc > 0:
            main_equity += spot_usdc
            log.info("Main spot USDC: $%.2f", spot_usdc)
    except Exception as e:
        log.debug("Spot balance query failed: %s", e)

    # 4. Fetch trigger orders for stop-loss detection (main + xyz)
    main_triggers = _fetch_open_trigger_orders(MAIN_ACCOUNT)
    xyz_triggers = _fetch_open_trigger_orders(MAIN_ACCOUNT, dex="xyz")
    all_triggers = main_triggers + xyz_triggers

    # 5. Fetch funding rates
    default_rates = _fetch_funding_rates()
    xyz_rates = _fetch_funding_rates(dex="xyz")

    # Attach funding rates to positions
    for pos in all_positions:
        coin = pos["coin"]
        if pos["account"] == "main_xyz":
            pos["funding_rate"] = xyz_rates.get(coin, 0.0)
        else:
            pos["funding_rate"] = default_rates.get(coin, 0.0)

    # 6. Fetch vault (BTC Power Law)
    try:
        resp = _req.post("https://api.hyperliquid.xyz/info", json={
            "type": "clearinghouseState", "user": VAULT_ADDRESS
        }, timeout=10)
        raw_vault = resp.json()
        vault_equity = _get_equity_from_state(raw_vault)
        vault_positions = _parse_positions_from_raw(raw_vault, "vault")
        all_positions.extend(vault_positions)

        # Attach funding rates to vault positions
        for pos in vault_positions:
            pos["funding_rate"] = default_rates.get(pos["coin"], 0.0)

        # Fetch vault trigger orders
        vault_triggers = _fetch_open_trigger_orders(VAULT_ADDRESS)
        all_triggers.extend(vault_triggers)
    except Exception as e:
        log.warning("Failed to fetch vault state: %s", e)

    if not all_positions and main_equity == 0 and vault_equity == 0:
        raise RuntimeError("Empty account state from both HL wallets")

    return {
        "equity": main_equity + vault_equity,
        "main_equity": main_equity,
        "vault_equity": vault_equity,
        "positions": all_positions,
        "trigger_orders": all_triggers,
        "funding_rates": {**default_rates, **xyz_rates},
    }


def _find_canonical_id(coin: str, config: HeartbeatConfig) -> str:
    """Map an HL coin name back to its canonical market id."""
    for market_id, mapping in config.markets.items():
        if mapping.hl_coin == coin:
            return market_id
    return coin
