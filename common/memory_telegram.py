"""Direct Telegram Bot API wrapper for heartbeat alerts and position summaries."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("memory_telegram")

_DEFAULT_CHAT_ID = "5219304680"
_MAX_MESSAGE_LENGTH = 4096


def send_telegram(
    message: str,
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """Send a message via the Telegram Bot API.

    Returns True on success, False on any failure.  Never raises.
    """
    try:
        token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            log.warning("No Telegram bot token available — skipping send")
            return False

        chat = chat_id or _DEFAULT_CHAT_ID
        chunks = _split_message(message)

        for chunk in chunks:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id": chat,
                    "text": chunk,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                log.error("Telegram send failed: %s %s", resp.status_code, resp.text)
                return False

        return True
    except Exception:
        log.exception("Telegram send error")
        return False


def _split_message(text: str) -> list[str]:
    """Split *text* into chunks of at most _MAX_MESSAGE_LENGTH characters.

    Splits on newline boundaries when possible.
    """
    if len(text) <= _MAX_MESSAGE_LENGTH:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= _MAX_MESSAGE_LENGTH:
            chunks.append(remaining)
            break

        # Find the last newline within the limit
        split_at = remaining.rfind("\n", 0, _MAX_MESSAGE_LENGTH)
        if split_at == -1:
            # No newline found — hard split
            split_at = _MAX_MESSAGE_LENGTH
        else:
            split_at += 1  # include the newline in the current chunk

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    return chunks


def format_position_summary(positions: dict) -> str:
    """Format a positions dict into Telegram-friendly Markdown.

    Expected input shape per market::

        {
            "BTC": {"size": 0.5, "entry_price": 62000.0, "unrealized_pnl": 1500.0},
            ...
        }
    """
    if not positions:
        return "No open positions."

    lines: list[str] = []
    for market, info in positions.items():
        size = info.get("size", 0)
        entry = info.get("entry_price", 0)
        pnl = info.get("unrealized_pnl", 0)
        pnl_sign = "+" if pnl >= 0 else ""
        lines.append(
            f"*{market}*\n"
            f"  Size: `{size}`  Entry: `{entry}`\n"
            f"  PnL: `{pnl_sign}{pnl}`"
        )

    return "\n\n".join(lines)
