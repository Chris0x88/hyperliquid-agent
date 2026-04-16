"""Tests for the Renderer-migrated command handlers.

Uses BufferRenderer so no real Telegram or HL API calls are made.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from common.renderer import BufferRenderer
from telegram.bot import (
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

_MOCK_BUNDLE = {
    "account": {
        "native_equity": 1000.0,
        "xyz_equity": 0.0,
        "spot_usdc": 0.0,
        "total_equity": 1000.0,
    },
    "accounts": [
        {"label": "Main", "native_equity": 1000.0, "xyz_equity": 0.0, "spot_usdc": 0.0, "total_equity": 1000.0},
    ],
    "positions": [
        {
            "coin": "BTC", "size": 1.0, "entry": 50000.0, "upnl": 500.0,
            "liq": "25000", "leverage": 2, "dex": "", "account_role": "main",
            "account_label": "Main",
        },
    ],
}

_EMPTY_BUNDLE = {
    "account": {"native_equity": 0.0, "xyz_equity": 0.0, "spot_usdc": 0.0, "total_equity": 0.0},
    "accounts": [{"label": "Main", "native_equity": 0.0, "xyz_equity": 0.0, "spot_usdc": 0.0, "total_equity": 0.0}],
    "positions": [],
}


class TestCmdStatus:
    def _run(self):
        buf = BufferRenderer()
        with (
            patch("common.account_state.fetch_registered_account_state", return_value=_MOCK_BUNDLE),
            patch("telegram.bot._get_current_price", return_value=51000.0),
            patch("telegram.bot._get_market_oi", return_value="OI: $1.2B"),
            patch("telegram.bot._get_all_orders", return_value=[]),
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
            patch("common.account_state.fetch_registered_account_state", return_value=_EMPTY_BUNDLE),
            patch("telegram.bot._get_all_orders", return_value=[]),
        ):
            cmd_status(buf, "")
        assert "No open positions" in buf.messages[0]["text"]

    def test_fetch_failure_shows_diagnostic(self):
        buf = BufferRenderer()
        with patch("common.account_state.fetch_registered_account_state", return_value={}):
            cmd_status(buf, "")
        assert "unavailable" in buf.messages[0]["text"].lower()


# ── cmd_price ────────────────────────────────────────────────────────────────

class TestCmdPrice:
    def _run(self):
        buf = BufferRenderer()
        with (
            patch("telegram.bot._get_all_market_ctx", return_value={"BTC": {"prevDayPx": 50000}}),
            patch("telegram.bot._get_current_price", return_value=51000.0),
            patch("telegram.bot.WATCHLIST", [("Bitcoin", "BTC", [], "crypto")]),
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
        with patch("telegram.bot._get_all_orders", return_value=[]):
            cmd_orders(buf, "")
        assert len(buf.messages) == 1
        assert "No open orders" in buf.messages[0]["text"]

    def test_with_orders(self):
        buf = BufferRenderer()
        with patch("telegram.bot._get_all_orders", return_value=[MOCK_ORDER]):
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
        with patch("telegram.bot._get_all_orders", return_value=orders):
            cmd_orders(buf, "")
        text = buf.messages[0]["text"]
        assert "BTC" in text
        assert "GOLD" in text


# ── cmd_health ───────────────────────────────────────────────────────────────

class TestCmdHealth:
    def test_sends_one_text_message(self):
        buf = BufferRenderer()
        with (
            patch("telegram.bot._diag", None),
            patch("common.authority.get_all", return_value={}),
        ):
            cmd_health(buf, "")
        assert len(buf.messages) == 1
        assert buf.messages[0]["type"] == "text"

    def test_output_contains_app_health_header(self):
        buf = BufferRenderer()
        with (
            patch("telegram.bot._diag", None),
            patch("common.authority.get_all", return_value={}),
        ):
            cmd_health(buf, "")
        assert "App Health" in buf.messages[0]["text"]

    def test_output_mentions_telegram_bot(self):
        buf = BufferRenderer()
        with (
            patch("telegram.bot._diag", None),
            patch("common.authority.get_all", return_value={}),
        ):
            cmd_health(buf, "")
        assert "Telegram" in buf.messages[0]["text"]

    def test_output_has_diag_hint(self):
        buf = BufferRenderer()
        with (
            patch("telegram.bot._diag", None),
            patch("common.authority.get_all", return_value={}),
        ):
            cmd_health(buf, "")
        assert "/diag" in buf.messages[0]["text"]


# ── cmd_menu ─────────────────────────────────────────────────────────────────

class TestCmdMenu:
    def test_main_menu_sends_grid(self):
        buf = BufferRenderer()
        mock_rows = [[{"text": "Status", "callback_data": "mn:status"}]]
        with patch("telegram.bot._build_main_menu", return_value=("*Menu*", mock_rows)):
            cmd_menu(buf, "")
        assert len(buf.messages) == 1
        assert buf.messages[0]["type"] == "grid"
        assert buf.messages[0]["text"] == "*Menu*"
        assert buf.messages[0]["rows"] == mock_rows

    def test_coin_arg_sends_position_detail(self):
        buf = BufferRenderer()
        mock_rows = [[{"text": "Close", "callback_data": "mn:close:BTC"}]]
        with (
            patch("telegram.bot._build_position_detail", return_value=("*BTC Position*", mock_rows)),
            patch("telegram.bot.resolve_coin", return_value="BTC"),
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
        from telegram.bot import cmd_pnl, cmd_diag
        assert cmd_pnl not in RENDERER_COMMANDS
        assert cmd_diag not in RENDERER_COMMANDS
