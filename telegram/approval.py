"""Approval flow and pending-input handlers for the Telegram bot.

Extracted mechanically from cli/telegram_bot.py (2026-04-11).
No behaviour changes — just a file split for maintainability.

Contains:
- _lock_approval_message
- _handle_tool_approval
- _handle_pending_input
- _handle_trade_size_prompt
- _find_position
- _handle_close_position
- _handle_sl_prompt
- _handle_tp_prompt
- _pending_inputs state dict
"""
from __future__ import annotations

import logging
import time

import requests

from telegram.api import tg_send, tg_send_buttons, tg_answer_callback
from exchange.helpers import _get_current_price, _get_account_values, _coin_matches

log = logging.getLogger("telegram_bot")

# ── Module-level state ──────────────────────────────────────
_pending_inputs: dict = {}  # chat_id -> {type, coin, size, side, entry, current, ts}


def _lock_approval_message(token: str, chat_id: str, message_id: int, approved: bool) -> None:
    """Replace Approve/Reject buttons with a single locked indicator button.

    Gives the user clear visual confirmation that their tap registered:
    the button row changes to a single locked label (\u2705 Approved or \u274c Rejected)
    with callback_data='noop' so further taps do nothing. editMessageReplyMarkup
    is cheaper than editMessageText \u2014 no need to re-send the original text.
    """
    if message_id is None:
        return
    label = "\u2705  Approved" if approved else "\u274c  Rejected"
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": [[
                    {"text": label, "callback_data": "noop"},
                ]]},
            },
            timeout=5,
        )
    except Exception as e:
        log.warning("Lock approval message failed: %s", e)


def _handle_tool_approval(token: str, chat_id: str, callback_id: str,
                           action_id: str, approved: bool, message_id: int = None) -> None:
    """Handle approve/reject of a pending write tool action."""
    from agent.tools import pop_pending, execute_tool

    # 1. Answer callback IMMEDIATELY — dismisses spinner and shows toast.
    toast = "\u2705 Approved" if approved else "\u274c Rejected"
    tg_answer_callback(token, callback_id, toast)

    # 2. Lock the button row so the user sees which was pressed.
    _lock_approval_message(token, chat_id, message_id, approved)

    action = pop_pending(action_id)
    if action is None:
        tg_send(token, chat_id, "Action expired or already handled.")
        return

    if not approved:
        tg_send(token, chat_id, "\u274c Action rejected.")
        return

    try:
        result = execute_tool(action["tool"], action["arguments"])
        tg_send(token, chat_id, f"\u2705 *{action['tool']}*\n\n{result}")
    except Exception as e:
        tg_send(token, chat_id, f"\u274c *{action['tool']} failed*\n\n{e}")


def _find_position(coin: str) -> dict | None:
    """Find a position by coin name (handles xyz: prefix matching)."""
    from telegram.menu import _cached_positions
    for p in _cached_positions():
        if _coin_matches(p.get("coin", ""), coin):
            return p
    return None


def _handle_trade_size_prompt(token: str, chat_id: str, coin: str, side: str) -> None:
    """Prompt user for trade size, store pending input state."""
    from telegram.menu import _active_account, _get_active_addr

    coin_name = coin
    current = _get_current_price(coin_name)
    px_str = f"${current:,.2f}" if current else "\u2014"
    display = coin.replace("xyz:", "")
    side_label = "BUY (LONG)" if side == "buy" else "SELL (SHORT)"
    side_icon = "\U0001f7e2" if side == "buy" else "\U0001f534"

    # Check existing position
    pos = _find_position(coin)
    pos_line = ""
    if pos:
        sz = float(pos.get("size", pos.get("szi", 0)))
        direction = "LONG" if sz > 0 else "SHORT"
        pos_line = f"\nExisting position: {direction} `{abs(sz):.1f}`"

    # Active account
    acct_label = "Vault" if _active_account == "vault" else "Main"
    values = _get_account_values(_get_active_addr())
    equity = values['native'] + values['xyz'] + values.get('spot', 0)

    _pending_inputs[chat_id] = {
        "type": "trade",
        "coin": coin_name,
        "side": side,
        "current": current,
        "account": _active_account,
        "ts": time.time(),
    }

    tg_send(token, chat_id,
        f"{side_icon} *{side_label} {display}*\n\n"
        f"Price: `{px_str}`\n"
        f"Account: *{acct_label}* (`${equity:,.2f}`)"
        f"{pos_line}\n\n"
        f"Reply with size (number of contracts):")


def _handle_close_position(token: str, chat_id: str, coin: str) -> None:
    """Build close-position confirmation with approval buttons."""
    from agent.tools import store_pending, format_confirmation

    pos = _find_position(coin)
    if not pos:
        tg_send(token, chat_id, f"No open position for `{coin}`")
        return

    size = float(pos.get("size", pos.get("szi", 0)))
    coin_name = pos.get("coin", coin)
    close_side = "sell" if size > 0 else "buy"
    current = _get_current_price(coin_name)

    args = {"coin": coin_name, "side": close_side, "size": abs(size), "dex": pos.get("dex", pos.get("_dex", ""))}
    action_id = store_pending("close_position", args, chat_id)

    direction = "LONG" if size > 0 else "SHORT"
    px_str = f" @ ~`${current:,.2f}`" if current else ""
    text = f"\u26a0\ufe0f *Close Position*\n\n{direction} `{abs(size):.1f}` {coin_name}{px_str}\n\nApprove or reject:"
    buttons = [
        {"text": "\u2705 Approve", "callback_data": f"approve:{action_id}"},
        {"text": "\u274c Reject", "callback_data": f"reject:{action_id}"},
    ]
    tg_send_buttons(token, chat_id, text, buttons)


def _handle_sl_prompt(token: str, chat_id: str, coin: str) -> None:
    """Prompt user for SL price, store pending input state."""
    pos = _find_position(coin)
    if not pos:
        tg_send(token, chat_id, f"No open position for `{coin}`")
        return

    size = float(pos.get("size", pos.get("szi", 0)))
    entry = float(pos.get("entry", pos.get("entryPx", 0)))
    coin_name = pos.get("coin", coin)
    current = _get_current_price(coin_name)
    px_str = f"${current:,.2f}" if current else "\u2014"

    _pending_inputs[chat_id] = {
        "type": "sl",
        "coin": coin_name,
        "size": abs(size),
        "side": "sell" if size > 0 else "buy",
        "entry": entry,
        "current": current,
        "dex": pos.get("dex", pos.get("_dex", "")),
        "ts": time.time(),
    }

    direction = "LONG" if size > 0 else "SHORT"
    close_side = "SELL" if size > 0 else "BUY"
    # SL should be BELOW entry for longs, ABOVE for shorts
    sl_hint = "below" if size > 0 else "above"

    tg_send(token, chat_id,
        f"\U0001f6e1 *Set Stop-Loss for {coin_name}*\n\n"
        f"Position: {direction} `{abs(size):.1f}` @ `${entry:,.2f}`\n"
        f"Now: `{px_str}`\n\n"
        f"Order type: *Stop Market* (reduce-only)\n"
        f"Side: {close_side} | Size: whole position\n"
        f"Trigger should be _{sl_hint}_ current price\n\n"
        f"Reply with trigger price:")


def _handle_tp_prompt(token: str, chat_id: str, coin: str) -> None:
    """Prompt user for TP price, store pending input state."""
    pos = _find_position(coin)
    if not pos:
        tg_send(token, chat_id, f"No open position for `{coin}`")
        return

    size = float(pos.get("size", pos.get("szi", 0)))
    entry = float(pos.get("entry", pos.get("entryPx", 0)))
    coin_name = pos.get("coin", coin)
    current = _get_current_price(coin_name)
    px_str = f"${current:,.2f}" if current else "\u2014"

    _pending_inputs[chat_id] = {
        "type": "tp",
        "coin": coin_name,
        "size": abs(size),
        "side": "sell" if size > 0 else "buy",
        "entry": entry,
        "current": current,
        "dex": pos.get("dex", pos.get("_dex", "")),
        "ts": time.time(),
    }

    direction = "LONG" if size > 0 else "SHORT"
    close_side = "SELL" if size > 0 else "BUY"
    # TP should be ABOVE entry for longs, BELOW for shorts
    tp_hint = "above" if size > 0 else "below"

    tg_send(token, chat_id,
        f"\U0001f3af *Set Take-Profit for {coin_name}*\n\n"
        f"Position: {direction} `{abs(size):.1f}` @ `${entry:,.2f}`\n"
        f"Now: `{px_str}`\n\n"
        f"Order type: *Take Profit Market* (reduce-only)\n"
        f"Side: {close_side} | Size: whole position\n"
        f"Trigger should be _{tp_hint}_ current price\n\n"
        f"Reply with trigger price:")


def _handle_pending_input(token: str, chat_id: str, text: str) -> bool:
    """Check if text is a pending SL/TP price reply. Returns True if handled."""
    pending = _pending_inputs.get(chat_id)
    if not pending:
        return False

    # 60-second TTL
    if time.time() - pending["ts"] > 60:
        del _pending_inputs[chat_id]
        return False

    # Try to parse as a number
    try:
        value = float(text.strip().replace("$", "").replace(",", ""))
    except ValueError:
        # Re-prompt instead of silently dropping — user is mid-flow
        label = "price" if pending["type"] in ("sl", "tp") else "size"
        tg_send(token, chat_id,
                f"Please enter a valid {label} (number). Got: `{text}`\n"
                f"Or type /cancel to abort.")
        return True  # consumed the message — don't route to command handler

    # Clear pending state
    del _pending_inputs[chat_id]

    from agent.tools import store_pending

    if pending["type"] == "trade":
        # Trade: value is size (contracts)
        size = value
        args = {
            "coin": pending["coin"],
            "side": pending["side"],
            "size": size,
        }
        action_id = store_pending("place_trade", args, chat_id)

        side_icon = "\U0001f7e2" if pending["side"] == "buy" else "\U0001f534"
        side_label = "BUY" if pending["side"] == "buy" else "SELL"
        current = pending.get("current")
        px_str = f" @ ~`${current:,.2f}`" if current else ""
        acct = pending.get("account", "main").title()
        text_msg = (
            f"{side_icon} *Confirm Trade*\n\n"
            f"*{side_label} `{size:.1f}` {pending['coin']}*{px_str}\n"
            f"Account: *{acct}*\n"
            f"Type: Market order\n\n"
            f"Approve or reject:"
        )
    else:
        # SL/TP: value is trigger price
        price = value
        tool_name = "set_sl" if pending["type"] == "sl" else "set_tp"
        args = {
            "coin": pending["coin"],
            "trigger_price": price,
            "side": pending["side"],
            "size": pending["size"],
            "dex": pending.get("dex", ""),
        }
        action_id = store_pending(tool_name, args, chat_id)

        label = "Stop-Loss" if pending["type"] == "sl" else "Take-Profit"
        icon = "\U0001f6e1" if pending["type"] == "sl" else "\U0001f3af"
        order_type = "Stop Market" if pending["type"] == "sl" else "Take Profit Market"
        text_msg = (
            f"{icon} *Confirm {label}*\n\n"
            f"*{pending['coin']}*\n"
            f"Type: `{order_type}` (reduce-only)\n"
            f"Trigger: `${price:,.2f}`\n"
            f"Side: `{pending['side'].upper()}` | Size: whole position\n\n"
            f"Approve or reject:"
        )
    buttons = [
        {"text": "\u2705 Approve", "callback_data": f"approve:{action_id}"},
        {"text": "\u274c Reject", "callback_data": f"reject:{action_id}"},
    ]
    tg_send_buttons(token, chat_id, text_msg, buttons)
    return True
