"""Tests for the Renderer-migrated command handlers.

Uses BufferRenderer so no real Telegram or HL API calls are made.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from common.renderer import BufferRenderer
from cli.telegram_bot import (
    cmd_status,
    cmd_price,
    cmd_orders,
    cmd_health,
    cmd_menu,
    RENDERER_COMMANDS,
)


# ── Minimal mock data ────────────────────────────────────────────────────────

MOCK_POSITION = {
    "coin": "BTC",
    "szi": "1.0",
    "entryPx": "50000",
    "unrealizedPnl": "500",
    "leverage": {"value": 2},
    "liquidationPx": "25000",
    "_dex": "",
}

MOCK_ORDER = {
    "coin": "BTC",
    "side": "B",
    "sz": "0.5",
    "limitPx": "49000",
    "orderType": "Limit",
    "tpsl": "",
    "isTrigger": False,
    "triggerPx": None,
}


# ── cmd_status ───────────────────────────────────────────────────────────────

class TestCmdStatus:
    def _run(self):
        buf = BufferRenderer()
        with (
            patch("cli.telegram_bot._hl_post", return_value={"balances": [{"coin": "USDC", "total": "1000"}]}),
            patch("cli.telegram_bot._get_all_positions", return_value=[MOCK_POSITION]),
            patch("cli.telegram_bot._get_current_price", return_value=51000.0),
            patch("cli.telegram_bot._get_market_oi", return_value="OI: $1.2B"),
            patch("cli.telegram_bot._get_account_values", return_value={"native": 2000.0, "xyz": 0.0}),
            patch("cli.telegram_bot._get_all_orders", return_value=[]),
        ):
            cmd_status(buf, "")
        return buf

    def test_sends_one_text_message(self):
        buf = self._run()
        assert len(buf.messages) == 1
        assert buf.messages[0]["type"] == "text"

    def test_output_contains_portfolio_header(self):
        buf = self._run()
        assert "Portfolio" in buf.messages[0]["text"]

    def test_output_contains_position(self):
        buf = self._run()
        assert "BTC" in buf.messages[0]["text"]

    def test_output_contains_equity(self):
        buf = self._run()
        assert "Equity" in buf.messages[0]["text"]

    def test_no_positions(self):
        buf = BufferRenderer()
        with (
            patch("cli.telegram_bot._hl_post", return_value={"balances": []}),
            patch("cli.telegram_bot._get_all_positions", return_value=[]),
            patch("cli.telegram_bot._get_account_values", return_value={"native": 0.0, "xyz": 0.0}),
            patch("cli.telegram_bot._get_all_orders", return_value=[]),
        ):
            cmd_status(buf, "")
        assert "No open positions" in buf.messages[0]["text"]


# ── cmd_price ────────────────────────────────────────────────────────────────

class TestCmdPrice:
    def _run(self):
        buf = BufferRenderer()
        with (
            patch("cli.telegram_bot._get_all_market_ctx", return_value={"BTC": {"prevDayPx": 50000}}),
            patch("cli.telegram_bot._get_current_price", return_value=51000.0),
            patch("cli.telegram_bot.WATCHLIST", [("Bitcoin", "BTC", [], "crypto")]),
        ):
            cmd_price(buf, "")
        return buf

    def test_sends_one_text_message(self):
        buf = self._run()
        assert len(buf.messages) == 1
        assert buf.messages[0]["type"] == "text"

    def test_output_contains_prices_header(self):
        buf = self._run()
        assert "Prices" in buf.messages[0]["text"]

    def test_output_contains_coin(self):
        buf = self._run()
        assert "Bitcoin" in buf.messages[0]["text"]

    def test_output_contains_price_value(self):
        buf = self._run()
        assert "51,000.00" in buf.messages[0]["text"]

    def test_output_shows_24h_change(self):
        buf = self._run()
        text = buf.messages[0]["text"]
        # 51000 vs 50000 = +2.0%
        assert "2.0%" in text or "2%" in text


# ── cmd_orders ───────────────────────────────────────────────────────────────

class TestCmdOrders:
    def test_no_orders(self):
        buf = BufferRenderer()
        with patch("cli.telegram_bot._get_all_orders", return_value=[]):
            cmd_orders(buf, "")
        assert len(buf.messages) == 1
        assert "No open orders" in buf.messages[0]["text"]

    def test_with_orders(self):
        buf = BufferRenderer()
        with patch("cli.telegram_bot._get_all_orders", return_value=[MOCK_ORDER]):
            cmd_orders(buf, "")
        assert len(buf.messages) == 1
        text = buf.messages[0]["text"]
        assert "Open Orders" in text
        assert "BTC" in text

    def test_order_grouped_by_coin(self):
        buf = BufferRenderer()
        orders = [
            {**MOCK_ORDER, "coin": "BTC"},
            {**MOCK_ORDER, "coin": "GOLD"},
        ]
        with patch("cli.telegram_bot._get_all_orders", return_value=orders):
            cmd_orders(buf, "")
        text = buf.messages[0]["text"]
        assert "BTC" in text
        assert "GOLD" in text


# ── cmd_health ───────────────────────────────────────────────────────────────

class TestCmdHealth:
    def test_sends_one_text_message(self):
        buf = BufferRenderer()
        with (
            patch("cli.telegram_bot._diag", None),
            patch("common.authority.get_all", return_value={}),
        ):
            cmd_health(buf, "")
        assert len(buf.messages) == 1
        assert buf.messages[0]["type"] == "text"

    def test_output_contains_app_health_header(self):
        buf = BufferRenderer()
        with (
            patch("cli.telegram_bot._diag", None),
            patch("common.authority.get_all", return_value={}),
        ):
            cmd_health(buf, "")
        assert "App Health" in buf.messages[0]["text"]

    def test_output_mentions_telegram_bot(self):
        buf = BufferRenderer()
        with (
            patch("cli.telegram_bot._diag", None),
            patch("common.authority.get_all", return_value={}),
        ):
            cmd_health(buf, "")
        assert "Telegram" in buf.messages[0]["text"]

    def test_output_has_diag_hint(self):
        buf = BufferRenderer()
        with (
            patch("cli.telegram_bot._diag", None),
            patch("common.authority.get_all", return_value={}),
        ):
            cmd_health(buf, "")
        assert "/diag" in buf.messages[0]["text"]


# ── cmd_menu ─────────────────────────────────────────────────────────────────

class TestCmdMenu:
    def test_main_menu_sends_grid(self):
        buf = BufferRenderer()
        mock_rows = [[{"text": "Status", "callback_data": "mn:status"}]]
        with patch("cli.telegram_bot._build_main_menu", return_value=("*Menu*", mock_rows)):
            cmd_menu(buf, "")
        assert len(buf.messages) == 1
        assert buf.messages[0]["type"] == "grid"
        assert buf.messages[0]["text"] == "*Menu*"
        assert buf.messages[0]["rows"] == mock_rows

    def test_coin_arg_sends_position_detail(self):
        buf = BufferRenderer()
        mock_rows = [[{"text": "Close", "callback_data": "mn:close:BTC"}]]
        with (
            patch("cli.telegram_bot._build_position_detail", return_value=("*BTC Position*", mock_rows)),
            patch("cli.telegram_bot.resolve_coin", return_value="BTC"),
        ):
            cmd_menu(buf, "btc")
        assert len(buf.messages) == 1
        assert buf.messages[0]["type"] == "grid"
        assert "BTC" in buf.messages[0]["text"]


# ── RENDERER_COMMANDS set ────────────────────────────────────────────────────

class TestRendererCommandsSet:
    def test_all_five_commands_registered(self):
        assert cmd_status in RENDERER_COMMANDS
        assert cmd_price in RENDERER_COMMANDS
        assert cmd_orders in RENDERER_COMMANDS
        assert cmd_health in RENDERER_COMMANDS
        assert cmd_menu in RENDERER_COMMANDS

    def test_legacy_commands_not_in_set(self):
        from cli.telegram_bot import cmd_pnl, cmd_diag
        assert cmd_pnl not in RENDERER_COMMANDS
        assert cmd_diag not in RENDERER_COMMANDS
