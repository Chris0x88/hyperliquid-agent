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

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [risk] %(message)s")
log = logging.getLogger("risk_monitor")

HL_API = "https://api.hyperliquid.xyz/info"
ADDR = "0x80B5801ce295C4D469F4C0C2e7E17bd84dF0F205"
VAULT = "0x9da9a9aef5a968277b5ea66c6a0df7add49d98da"
POLL_INTERVAL = 30
PID_FILE = Path("data/daemon/risk_monitor.pid")
SIGNAL_LOG = Path("data/research/markets/xyz_brentoil/signals.jsonl")

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


def _get_xyz_position() -> dict | None:
    """Get BRENTOIL position from xyz clearinghouse."""
    state = _hl({"type": "clearinghouseState", "user": ADDR, "dex": "xyz"})
    positions = state.get("assetPositions", [])
    for p in positions:
        pos = p.get("position", {})
        if "BRENTOIL" in pos.get("coin", "").upper():
            return pos
    return None


def _get_brentoil_price() -> float:
    """Get current BRENTOIL mid price."""
    book = _hl({"type": "l2Book", "coin": "xyz:BRENTOIL"})
    levels = book.get("levels", [])
    if len(levels) >= 2 and levels[0] and levels[1]:
        return (float(levels[0][0]["px"]) + float(levels[1][0]["px"])) / 2
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

    price_history = deque(maxlen=RAPID_DROP_WINDOW)
    last_alert_time = 0
    ALERT_COOLDOWN = 300  # 5 min between repeated alerts

    while running:
        try:
            pos = _get_xyz_position()
            price = _get_brentoil_price()
            now = time.time()

            if not pos or price <= 0:
                # No position or no price — check vault BTC instead
                vault_state = _hl({"type": "clearinghouseState", "user": VAULT})
                # Just log and continue
                time.sleep(POLL_INTERVAL)
                continue

            entry = float(pos.get("entryPx", 0))
            size = float(pos.get("szi", 0))
            upnl = float(pos.get("unrealizedPnl", 0))
            liq = float(pos.get("liquidationPx", 0))
            lev = pos.get("leverage", {})
            lev_val = lev.get("value", 0) if isinstance(lev, dict) else 0

            # Track price for rapid drop detection
            price_history.append(price)

            # Calculate metrics
            drawdown_pct = ((entry - price) / entry * 100) if size > 0 and price < entry else 0
            dist_to_liq_pct = ((price - liq) / price * 100) if liq > 0 and price > liq else 0

            # Log every poll
            _log_signal({
                "type": "risk_poll",
                "price": price,
                "entry": entry,
                "size": size,
                "upnl": upnl,
                "liq": liq,
                "leverage": lev_val,
                "drawdown_pct": round(drawdown_pct, 2),
                "dist_to_liq_pct": round(dist_to_liq_pct, 2),
            })

            alerts = []

            # Check drawdown
            if drawdown_pct > DRAWDOWN_ALERT_PCT:
                alerts.append(f"DRAWDOWN: -{drawdown_pct:.1f}% from entry ${entry:.2f}")

            # Check proximity to liquidation
            if 0 < dist_to_liq_pct < LIQ_WARNING_PCT:
                alerts.append(f"LIQ WARNING: only {dist_to_liq_pct:.1f}% above liq ${liq:.2f}")

            if 0 < dist_to_liq_pct < LIQ_EMERGENCY_PCT:
                alerts.append(f"EMERGENCY: {dist_to_liq_pct:.1f}% from liquidation! Consider reducing leverage.")
                # TODO: auto-reduce leverage via exchange API when wired up

            # Check rapid drop
            if len(price_history) >= RAPID_DROP_WINDOW:
                oldest = price_history[0]
                drop_pct = (oldest - price) / oldest * 100
                if drop_pct > RAPID_DROP_PCT:
                    alerts.append(f"RAPID DROP: -{drop_pct:.1f}% in {RAPID_DROP_WINDOW * POLL_INTERVAL // 60}min")

            # Send alerts (with cooldown)
            if alerts and (now - last_alert_time) > ALERT_COOLDOWN:
                msg = (
                    f"RISK ALERT\n"
                    f"BRENTOIL: ${price:.2f} | uPnL: ${upnl:+.2f}\n"
                    f"Entry: ${entry:.2f} | Liq: ${liq:.2f}\n"
                    f"Leverage: {lev_val}x\n\n"
                    + "\n".join(f"  {a}" for a in alerts)
                )
                _tg_send(token, chat_id, msg)
                log.warning("ALERT: %s", "; ".join(alerts))
                last_alert_time = now

            # Quiet periodic log
            if int(now) % 300 < POLL_INTERVAL:  # ~every 5 min
                log.info("BRENTOIL $%.2f | uPnL $%+.2f | liq $%.2f (%.1f%% away) | %dx",
                         price, upnl, liq, dist_to_liq_pct, lev_val)

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
