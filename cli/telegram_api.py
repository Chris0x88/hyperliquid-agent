"""Low-level Telegram Bot API helpers.

Extracted mechanically from cli/telegram_bot.py (2026-04-11).
No behaviour changes — just a file split for maintainability.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger("telegram_bot")

# ── Telegram API helpers ─────────────────────────────────────

def tg_send(token: str, chat_id: str, text: str, markdown: bool = True) -> bool:
    """Send a Telegram message. Uses Markdown by default, falls back to plain text."""
    try:
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if markdown:
            payload["parse_mode"] = "Markdown"
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=10,
        )
        result = r.json()
        if result.get("ok"):
            return True
        # Markdown failed — retry as plain text
        if markdown:
            payload.pop("parse_mode", None)
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload, timeout=10,
            )
            return r.json().get("ok", False)
        return False
    except Exception as e:
        log.warning("Send failed: %s", e)
        return False


def tg_send_buttons(token: str, chat_id: str, text: str, buttons: list) -> bool:
    """Send a message with inline keyboard buttons.

    buttons: list of dicts with 'text' and 'callback_data' keys.
    Laid out one button per row.
    """
    try:
        keyboard = [[btn] for btn in buttons]
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": keyboard},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=10,
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.warning("Send buttons failed: %s", e)
        return False


def tg_remove_buttons(token: str, chat_id: str, message_id: int) -> bool:
    """Remove inline keyboard buttons from a message."""
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": {"inline_keyboard": []},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
            json=payload, timeout=5,
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.warning("Remove buttons failed: %s", e)
        return False


def tg_answer_callback(token: str, callback_id: str, text: str = "") -> None:
    """Answer a callback query (dismisses the loading spinner on the button)."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=5,
        )
    except Exception:
        pass


def tg_send_grid(token: str, chat_id: str, text: str, rows: list) -> dict:
    """Send a message with inline keyboard grid. rows = [[btn, btn], [btn], ...]."""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": rows},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=10,
        )
        return r.json()
    except Exception as e:
        log.warning("Send grid failed: %s", e)
        return {}


def tg_edit_grid(token: str, chat_id: str, message_id: int, text: str, rows: list) -> bool:
    """Edit an existing message text + inline keyboard in-place."""
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": rows},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/editMessageText",
            json=payload, timeout=10,
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.warning("Edit grid failed: %s", e)
        return False


_poll_fail_count = 0  # consecutive polling failures


def tg_get_updates(token: str, offset: int) -> list:
    global _poll_fail_count
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": 2},
            timeout=10,
        )
        data = r.json()
        result = data.get("result", []) if data.get("ok") else []
        if _poll_fail_count > 0:
            log.info("Telegram API recovered after %d failures", _poll_fail_count)
        _poll_fail_count = 0
        return result
    except Exception as e:
        _poll_fail_count += 1
        log.warning("Telegram poll failed (%d consecutive): %s", _poll_fail_count, e)
        return []
