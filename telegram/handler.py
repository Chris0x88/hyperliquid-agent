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


def _send(token: str, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
    try:
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
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


WHITELIST_PATH = Path("data/daemon/whitelist.json")

def get_whitelist() -> list[str]:
    if not WHITELIST_PATH.exists():
        return ["BTC-PERP", "ETH-PERP", "xyz:BRENTOIL"]
    try:
        return json.loads(WHITELIST_PATH.read_text())
    except Exception:
        return []

def set_whitelist(wl: list[str]) -> None:
    WHITELIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WHITELIST_PATH.write_text(json.dumps(list(set(wl)), indent=2))
    
def _handle_whitelist_ui(token: str, chat_id: str, action: str = "", arg: str = "") -> str:
    wl = get_whitelist()
    
    if action == "add" and arg:
        sym = arg.upper()
        if not sym.endswith("-PERP") and not sym.startswith("xyz:"):
            sym = f"{sym}-PERP"
        if sym not in wl:
            wl.append(sym)
            set_whitelist(wl)
            _send(token, chat_id, f"✅ Added {sym} to whitelist.")
            
    elif action == "drop" and arg:
        if arg in wl:
            wl.remove(arg)
            set_whitelist(wl)
            _send(token, chat_id, f"🗑️ Dropped {arg} from whitelist.")

    # Render UI
    text = "🛡️ **Agent Market Whitelist**\nOpenClaw is restricted to researching and trading these markets only:\n"
    
    keyboard = {"inline_keyboard": []}
    for coin in sorted(wl):
        keyboard["inline_keyboard"].append([
            {"text": f"❌ Drop {coin}", "callback_data": f"wl_drop:{coin}"}
        ])
    
    keyboard["inline_keyboard"].append([
        {"text": "💡 Tip: Reply '/wl add <COIN>' to add", "callback_data": "ignore"}
    ])
    
    _send(token, chat_id, text, reply_markup=keyboard)
    return ""


def _get_portfolio_status(token: str, chat_id: str) -> str:
    """Build portfolio status message from live data."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from common.account_state import fetch_registered_account_state

    lines = []
    now = datetime.now(timezone.utc)
    lines.append(f"Portfolio Status ({now.strftime('%a %H:%M UTC')})")
    lines.append("")
    bundle = fetch_registered_account_state()
    account = bundle.get("account", {})

    lines.append(f"Total Equity: ${float(account.get('total_equity', 0)):,.2f}")
    lines.append(
        f"Native: ${float(account.get('native_equity', 0)):,.2f} | "
        f"xyz: ${float(account.get('xyz_equity', 0)):,.2f} | "
        f"Spot: ${float(account.get('spot_usdc', 0)):,.2f}"
    )

    for row in bundle.get("accounts", []):
        lines.append("")
        lines.append(f"{row['label'].upper()}: ${row['total_equity']:,.2f}")
        for bal in row.get("spot_balances", []):
            total = float(bal.get("total", 0))
            lines.append(f"  {bal['coin']}: ${total:,.2f}" if bal["coin"] == "USDC" else f"  {bal['coin']}: {total:.4f}")
        wallet_positions = [p for p in bundle.get("positions", []) if p.get("address") == row.get("address")]
        if wallet_positions:
            for pos in wallet_positions:
                lines.append(
                    f"  {pos.get('coin', '?')}: {pos.get('size', 0)} @ ${float(pos.get('entry', 0)):,.2f} "
                    f"| uPnL: ${float(pos.get('upnl', 0)):,.2f} | lev: {pos.get('leverage', '?')}"
                )
        else:
            lines.append("  No open positions")

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
    "/whitelist": ("Manage AI market whitelist", lambda t, c: _handle_whitelist_ui(t, c)),
    "/wl": ("Alias for whitelist (use /wl add <coin>)", None),
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

        if callback_query := update.get("callback_query"):
            _set_last_update_id(update.get("update_id", 0))
            cb_data = callback_query.get("data", "")
            cb_msg = callback_query.get("message", {})
            cb_chat_id = str(cb_msg.get("chat", {}).get("id", ""))
            
            if cb_chat_id == chat_id and cb_data.startswith("wl_drop:"):
                coin = cb_data.split(":", 1)[1]
                _handle_whitelist_ui(token, chat_id, "drop", coin)
                
            # Answer callback to remove loading state
            cb_id = callback_query.get("id")
            requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": cb_id})
            continue

        msg = update.get("message", {})
        msg_chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "").strip()

        # Only respond to authorized chat
        if msg_chat_id != chat_id:
            continue

        if not text:
            continue

        parts = text.split()
        cmd = parts[0].lower()

        if cmd == "/help":
            help_lines = ["Commands:", ""]
            for c, info in COMMANDS.items():
                if info:
                    desc = info[0] if isinstance(info, tuple) else "Command"
                    help_lines.append(f"  {c} — {desc}")
            help_lines.append("")
            help_lines.append("Anything else is forwarded to Claude for analysis/execution.")
            _send(token, chat_id, "\n".join(help_lines))

        elif cmd == "/wl" and len(parts) > 2 and parts[1].lower() == "add":
            sym = parts[2]
            _handle_whitelist_ui(token, chat_id, "add", sym)
            
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
