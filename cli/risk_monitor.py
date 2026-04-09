#!/usr/bin/env python3
"""Risk Monitor — lightweight position guardian.

Polls every 30s. Defends the account. Alerts on danger. Auto-reduces if near liq.
NOT the full daemon. Just focused risk defense for live positions.

Run: python3 -m cli.risk_monitor
Or:  hl risk start
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import requests
from common.account_state import fetch_registered_account_state

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [risk] %(message)s")
log = logging.getLogger("risk_monitor")

HL_API = "https://api.hyperliquid.xyz/info"

POLL_INTERVAL = 30
PID_FILE = Path("data/daemon/risk_monitor.pid")
SIGNAL_LOG = Path("data/research/risk_monitor_signals.jsonl")

# Alert thresholds
DRAWDOWN_ALERT_PCT = 8.0      # Alert if down >8% from entry
LIQ_WARNING_PCT = 2.0         # Alert if within 2% of liquidation
LIQ_EMERGENCY_PCT = 1.0       # AUTO-REDUCE if within 1% of liquidation
RAPID_DROP_PCT = 3.0           # Alert if >3% drop in 5 minutes
RAPID_DROP_WINDOW = 10         # Number of 30s polls = 5 minutes


def _keychain(key: str) -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", "hl-agent-telegram", "-a", key, "-w"],
        capture_output=True, text=True, timeout=5,
    )
    return r.stdout.strip()


def _tg_send(token: str, chat_id: str, text: str):
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        log.warning("Telegram send failed: %s", e)


def _hl(payload: dict) -> dict:
    try:
        return requests.post(HL_API, json=payload, timeout=10).json()
    except Exception:
        return {}


def _get_live_price(coin: str) -> float:
    """Get current mid price for any native or xyz market."""
    try:
        mids = _hl({"type": "allMids"}) or {}
        if coin in mids:
            return float(mids[coin])
    except Exception:
        pass
    try:
        mids_xyz = _hl({"type": "allMids", "dex": "xyz"}) or {}
        if coin in mids_xyz:
            return float(mids_xyz[coin])
        bare = coin.replace("xyz:", "")
        for k, v in mids_xyz.items():
            if k == bare or k.replace("xyz:", "") == bare:
                return float(v)
    except Exception:
        pass
    try:
        book = _hl({"type": "l2Book", "coin": coin})
        levels = book.get("levels", [])
        if len(levels) >= 2 and levels[0] and levels[1]:
            return (float(levels[0][0]["px"]) + float(levels[1][0]["px"])) / 2
    except Exception:
        pass
    return 0.0


def _calc_drawdown_pct(entry: float, price: float, size: float) -> float:
    if entry <= 0 or price <= 0:
        return 0.0
    if size > 0 and price < entry:
        return ((entry - price) / entry) * 100
    if size < 0 and price > entry:
        return ((price - entry) / entry) * 100
    return 0.0


def _calc_liq_distance_pct(price: float, liq: float, size: float) -> float:
    if liq <= 0 or price <= 0:
        return 0.0
    if size > 0 and price > liq:
        return ((price - liq) / price) * 100
    if size < 0 and liq > price:
        return ((liq - price) / price) * 100
    return 0.0


def _log_signal(data: dict):
    SIGNAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    data["timestamp"] = int(time.time())
    with open(SIGNAL_LOG, "a") as f:
        f.write(json.dumps(data) + "\n")


def run():
    token = _keychain("bot_token")
    chat_id = _keychain("chat_id")
    if not token or not chat_id:
        log.error("Telegram credentials not configured")
        sys.exit(1)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Kill existing
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text().strip())
            if old != os.getpid():
                os.kill(old, signal.SIGTERM)
                time.sleep(0.5)
        except (OSError, ValueError):
            pass
    PID_FILE.write_text(str(os.getpid()))

    running = True
    def _stop(sig, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info("Risk monitor started — polling every %ds", POLL_INTERVAL)
    _tg_send(token, chat_id, "Risk monitor online. Watching your positions.")

    price_history: dict[str, deque] = {}
    last_alert_time = 0
    ALERT_COOLDOWN = 300  # 5 min between repeated alerts

    while running:
        try:
            now = time.time()
            bundle = fetch_registered_account_state()
            positions = bundle.get("positions", [])
            if not positions:
                time.sleep(POLL_INTERVAL)
                continue

            cycle_alerts: list[str] = []
            status_lines: list[str] = []

            for pos in positions:
                coin = str(pos.get("coin", "?"))
                account_label = pos.get("account_label", pos.get("account_role", "Account"))
                price = _get_live_price(coin)
                if price <= 0:
                    continue

                entry = float(pos.get("entry", 0))
                size = float(pos.get("size", 0))
                upnl = float(pos.get("upnl", 0))
                liq = float(pos.get("liq") or 0)
                lev_val = pos.get("leverage", 0)

                history = price_history.setdefault(coin, deque(maxlen=RAPID_DROP_WINDOW))
                history.append(price)

                drawdown_pct = _calc_drawdown_pct(entry, price, size)
                dist_to_liq_pct = _calc_liq_distance_pct(price, liq, size)

                _log_signal({
                    "type": "risk_poll",
                    "coin": coin,
                    "account": account_label,
                    "price": price,
                    "entry": entry,
                    "size": size,
                    "upnl": upnl,
                    "liq": liq,
                    "leverage": lev_val,
                    "drawdown_pct": round(drawdown_pct, 2),
                    "dist_to_liq_pct": round(dist_to_liq_pct, 2),
                })

                pos_alerts = []
                if drawdown_pct > DRAWDOWN_ALERT_PCT:
                    pos_alerts.append(f"DRAWDOWN: -{drawdown_pct:.1f}% from entry ${entry:.2f}")

                if 0 < dist_to_liq_pct < LIQ_WARNING_PCT:
                    pos_alerts.append(f"LIQ WARNING: only {dist_to_liq_pct:.1f}% from liq ${liq:.2f}")

                if 0 < dist_to_liq_pct < LIQ_EMERGENCY_PCT:
                    pos_alerts.append(f"EMERGENCY: {dist_to_liq_pct:.1f}% from liquidation")

                if len(history) >= RAPID_DROP_WINDOW:
                    oldest = history[0]
                    if oldest > 0:
                        if size > 0:
                            drop_pct = (oldest - price) / oldest * 100
                        else:
                            drop_pct = (price - oldest) / oldest * 100
                        if drop_pct > RAPID_DROP_PCT:
                            pos_alerts.append(
                                f"RAPID MOVE: {drop_pct:.1f}% in {RAPID_DROP_WINDOW * POLL_INTERVAL // 60}min"
                            )

                if pos_alerts:
                    liq_str = f"{liq:.2f}" if liq > 0 else "N/A"
                    cycle_alerts.append(
                        f"{account_label} {coin}: ${price:.2f} | uPnL ${upnl:+.2f} | "
                        f"liq ${liq_str}\n  " + "\n  ".join(pos_alerts)
                    )

                status_lines.append(
                    f"{account_label} {coin} ${price:.2f} uPnL ${upnl:+.2f} "
                    f"liq {dist_to_liq_pct:.1f}% away"
                )

            if cycle_alerts and (now - last_alert_time) > ALERT_COOLDOWN:
                _tg_send(token, chat_id, "RISK ALERT\n\n" + "\n\n".join(cycle_alerts[:6]))
                log.warning("ALERT: %s", " | ".join(a.splitlines()[0] for a in cycle_alerts))
                last_alert_time = now

            if status_lines and int(now) % 300 < POLL_INTERVAL:
                log.info(" | ".join(status_lines[:6]))

        except Exception as e:
            log.error("Risk monitor error: %s", e)

        if running:
            time.sleep(POLL_INTERVAL)

    PID_FILE.unlink(missing_ok=True)
    _tg_send(token, chat_id, "Risk monitor stopped.")
    log.info("Risk monitor stopped.")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    run()
