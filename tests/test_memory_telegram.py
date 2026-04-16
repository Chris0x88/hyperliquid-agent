"""Tests for common.memory_telegram — direct Telegram Bot API wrapper."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call

import pytest

from telegram.memory import send_telegram, format_position_summary


# ---------------------------------------------------------------------------
# send_telegram
# ---------------------------------------------------------------------------

class TestSendTelegramSuccess:
    """Posts correct JSON and returns True on 200."""

    @patch("telegram.memory.requests.post")
    def test_send_telegram_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        result = send_telegram("hello world", bot_token="TOKEN123", chat_id="999")

        assert result is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "TOKEN123" in args[0]
        assert kwargs["json"]["chat_id"] == "999"
        assert kwargs["json"]["text"] == "hello world"


class TestSendTelegramFailure:
    """Exception during post returns False, never raises."""

    @patch("telegram.memory.requests.post", side_effect=Exception("network down"))
    def test_send_telegram_failure_returns_false(self, mock_post):
        result = send_telegram("boom", bot_token="TOKEN123")
        assert result is False


class TestSendTelegramLongMessageSplits:
    """A 5000-char message must be split into 2 sends."""

    @patch("telegram.memory.requests.post")
    def test_send_telegram_long_message_splits(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        # Build a message with many lines totalling ~5000 chars
        line = "A" * 99 + "\n"  # 100 chars per line
        message = line * 50  # 5000 chars total
        assert len(message) == 5000

        result = send_telegram(message, bot_token="TOKEN123", chat_id="999")

        assert result is True
        assert mock_post.call_count == 2
        # Verify all text was sent (combined)
        sent_texts = [c.kwargs["json"]["text"] for c in mock_post.call_args_list]
        combined = "".join(sent_texts)
        assert combined == message


class TestSendTelegramNoToken:
    """No token set returns False with no HTTP call."""

    @patch.dict(os.environ, {}, clear=True)
    @patch("telegram.memory.requests.post")
    def test_send_telegram_no_token(self, mock_post):
        # Ensure TELEGRAM_BOT_TOKEN is not in env
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)

        result = send_telegram("hello")
        assert result is False
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# format_position_summary
# ---------------------------------------------------------------------------

class TestFormatPositionSummary:
    """Produces readable Telegram markdown with market, size, entry, PnL."""

    def test_format_position_summary(self):
        positions = {
            "BTC": {
                "size": 0.5,
                "entry_price": 62000.0,
                "unrealized_pnl": 1500.0,
            },
            "BRENTOIL": {
                "size": 20,
                "entry_price": 74.50,
                "unrealized_pnl": -120.0,
            },
        }
        result = format_position_summary(positions)

        # Must contain market names in bold (single asterisk for Telegram)
        assert "*BTC*" in result
        assert "*BRENTOIL*" in result
        # Must contain numbers in backticks
        assert "`0.5`" in result or "`62000" in result
        # Must contain PnL values
        assert "1500" in result
        assert "-120" in result
        # Basic readability — has newlines
        assert "\n" in result
