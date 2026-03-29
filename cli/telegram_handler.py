"""Telegram two-way command handler.

Polls for incoming messages from the authorized chat and writes them to
a command queue file. The scheduled task or daemon reads these commands
and executes them.

Also handles simple commands directly:
  /status  — portfolio status
  /price   — current prices for watched instruments
  /orders  — open orders
  /pnl     — P&L summary
  /help    — list commands

Complex commands (trade execution, analysis) are forwarded to the
Claude Code session via the command queue.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("telegram_handler")

COMMAND_QUEUE_PATH = Path("data/daemon/telegram_commands.jsonl")
LAST_UPDATE_PATH = Path("data/daemon/telegram_last_update_id.txt")


def _keychain_read(key_name: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", "hl-agent-telegram", "-a", key_name, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _send(token: str, chat_id: str, text: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        return resp.json().get("ok", False)
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return False


def _get_last_update_id() -> int:
    if LAST_UPDATE_PATH.exists():
        try:
            return int(LAST_UPDATE_PATH.read_text().strip())
        except (ValueError, OSError):
            pass
    return 0


def _set_last_update_id(update_id: int) -> None:
    LAST_UPDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_UPDATE_PATH.write_text(str(update_id))


def _get_portfolio_status(token: str, chat_id: str) -> str:
    """Build portfolio status message from live data."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    url = "https://api.hyperliquid.xyz/info"
    addr = "0x80B5801ce295C4D469F4C0C2e7E17bd84dF0F205"
    vault_addr = "0x9da9a9aef5a968277b5ea66c6a0df7add49d98da"

    lines = []
    now = datetime.now(timezone.utc)
    lines.append(f"Portfolio Status ({now.strftime('%a %H:%M UTC')})")
    lines.append("")

    # Main account
    try:
        resp = requests.post(url, json={"type": "spotClearinghouseState", "user": addr}, timeout=10)
        spot = resp.json()
        balances = spot.get("balances", [])
        for b in balances:
            total = float(b.get("total", 0))
            if total > 0.01:
                lines.append(f"  {b['coin']}: ${total:,.2f}" if b["coin"] == "USDC" else f"  {b['coin']}: {total:.4f}")
    except Exception:
        lines.append("  (spot data unavailable)")

    # Perps positions on main
    try:
        resp = requests.post(url, json={"type": "clearinghouseState", "user": addr}, timeout=10)
        state = resp.json()
        positions = state.get("assetPositions", [])
        if positions:
            lines.append("")
            lines.append("MAIN POSITIONS:")
            for p in positions:
                pos = p.get("position", {})
                coin = pos.get("coin", "?")
                size = pos.get("szi", "0")
                entry = pos.get("entryPx", "0")
                upnl = pos.get("unrealizedPnl", "0")
                lev = pos.get("leverage", {})
                lines.append(f"  {coin}: {size} @ ${entry} | uPnL: ${upnl} | lev: {lev}")
    except Exception:
        pass

    # Open orders
    try:
        resp = requests.post(url, json={"type": "openOrders", "user": addr}, timeout=10)
        orders = resp.json()
        if orders:
            lines.append("")
            lines.append("OPEN ORDERS:")
            for o in orders:
                side = "BUY" if o.get("side") == "B" else "SELL"
                lines.append(f"  {side} {o.get('sz')} {o.get('coin')} @ ${o.get('limitPx')}")
    except Exception:
        pass

    # Vault
    try:
        resp = requests.post(url, json={"type": "clearinghouseState", "user": vault_addr}, timeout=10)
        vstate = resp.json()
        vmargin = vstate.get("marginSummary", {})
        vpositions = vstate.get("assetPositions", [])
        lines.append("")
        lines.append(f"VAULT: ${float(vmargin.get('accountValue', 0)):,.2f}")
        for p in vpositions:
            pos = p.get("position", {})
            lines.append(f"  {pos.get('coin')}: {pos.get('szi')} @ ${pos.get('entryPx')} | uPnL: ${pos.get('unrealizedPnl')}")
    except Exception:
        lines.append("VAULT: (unavailable)")

    # Liquidity regime
    weekday = now.weekday()
    hour = now.hour
    is_weekend = weekday >= 5
    is_after_hours = hour >= 22 or hour < 6
    if is_weekend and is_after_hours:
        regime = "DANGEROUS"
    elif is_weekend:
        regime = "WEEKEND"
    elif is_after_hours:
        regime = "LOW"
    else:
        regime = "NORMAL"
    lines.append(f"\nLiquidity: {regime}")

    return "\n".join(lines)


def _get_prices(token: str, chat_id: str) -> str:
    """Get current prices for watched instruments."""
    url = "https://api.hyperliquid.xyz/info"
    watched = ["BTC", "ETH", "xyz:BRENTOIL", "xyz:GOLD", "xyz:NATGAS"]
    lines = ["Current Prices:"]

    resp = requests.post(url, json={"type": "allMids"}, timeout=10)
    mids = resp.json()

    for coin in watched:
        if coin in mids:
            lines.append(f"  {coin}: ${float(mids[coin]):,.2f}")
        else:
            # Try L2 book for xyz markets
            try:
                resp2 = requests.post(url, json={"type": "l2Book", "coin": coin}, timeout=5)
                book = resp2.json()
                levels = book.get("levels", [])
                if len(levels) >= 2 and levels[0] and levels[1]:
                    bid = float(levels[0][0]["px"])
                    ask = float(levels[1][0]["px"])
                    mid = (bid + ask) / 2
                    lines.append(f"  {coin}: ${mid:,.2f}")
            except Exception:
                lines.append(f"  {coin}: --")

    return "\n".join(lines)


COMMANDS = {
    "/status": ("Portfolio status", _get_portfolio_status),
    "/price": ("Current prices", _get_prices),
    "/help": None,  # handled inline
}


def poll_and_respond() -> list[dict]:
    """Poll Telegram for new messages, respond to commands, return unhandled messages.

    Returns list of messages that need Claude's attention (not simple commands).
    """
    token = _keychain_read("bot_token")
    chat_id = _keychain_read("chat_id")
    if not token or not chat_id:
        log.warning("Telegram credentials not configured")
        return []

    last_id = _get_last_update_id()
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": last_id + 1, "timeout": 5},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        log.warning("Telegram poll failed: %s", e)
        return []

    if not data.get("ok") or not data.get("result"):
        return []

    unhandled = []
    for update in data["result"]:
        update_id = update.get("update_id", 0)
        _set_last_update_id(update_id)

        msg = update.get("message", {})
        msg_chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "").strip()

        # Only respond to authorized chat
        if msg_chat_id != chat_id:
            continue

        if not text:
            continue

        cmd = text.split()[0].lower()

        if cmd == "/help":
            help_lines = ["Commands:", ""]
            for c, info in COMMANDS.items():
                desc = info[0] if info else "This help message"
                help_lines.append(f"  {c} — {desc}")
            help_lines.append("")
            help_lines.append("Anything else is forwarded to Claude for analysis/execution.")
            _send(token, chat_id, "\n".join(help_lines))

        elif cmd in COMMANDS and COMMANDS[cmd] is not None:
            handler = COMMANDS[cmd][1]
            try:
                response = handler(token, chat_id)
                _send(token, chat_id, response)
            except Exception as e:
                _send(token, chat_id, f"Error: {e}")

        else:
            # Not a simple command — forward to Claude
            entry = {
                "timestamp": int(time.time()),
                "message_id": msg.get("message_id"),
                "text": text,
                "user": msg.get("from", {}).get("first_name", ""),
            }
            COMMAND_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(COMMAND_QUEUE_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
            unhandled.append(entry)
            _send(token, chat_id, f"Received. Processing: {text[:100]}")

    return unhandled


def read_pending_commands() -> list[dict]:
    """Read and clear pending commands from the queue."""
    if not COMMAND_QUEUE_PATH.exists():
        return []
    commands = []
    for line in COMMAND_QUEUE_PATH.read_text().splitlines():
        try:
            commands.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    # Clear the queue
    COMMAND_QUEUE_PATH.unlink(missing_ok=True)
    return commands


def send_reply(text: str) -> bool:
    """Send a reply back to the user's Telegram."""
    token = _keychain_read("bot_token")
    chat_id = _keychain_read("chat_id")
    if not token or not chat_id:
        return False
    return _send(token, chat_id, text)
