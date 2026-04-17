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


# ── Multi-wallet smoke tests (bug-fix audit 2026-04-17) ──────────────────────
# Verify that fixed commands expose BOTH positions (main + vault) and use the
# canonical total_equity from fetch_registered_account_state.

_MOCK_TWO_WALLET_BUNDLE = {
    "account": {
        "native_equity": 30.0,
        "xyz_equity": 21.0,
        "spot_usdc": 30.0,
        "total_equity": 631.0,
    },
    "accounts": [
        {
            "role": "main", "label": "Main", "address": "0xmain",
            "native_equity": 30.0, "xyz_equity": 21.0, "spot_usdc": 30.0, "total_equity": 81.0,
        },
        {
            "role": "vault", "label": "Vault", "address": "0xvault",
            "native_equity": 550.0, "xyz_equity": 0.0, "spot_usdc": 0.0, "total_equity": 550.0,
        },
    ],
    "positions": [
        {
            "coin": "xyz:SILVER", "size": 17.0, "entry": 32.0, "upnl": 50.0,
            "liq": "28.0", "leverage": 17, "dex": "xyz",
            "account_role": "main", "account_label": "Main",
        },
        {
            "coin": "BTC", "size": 0.5, "entry": 82000.0, "upnl": 1200.0,
            "liq": "75000", "leverage": 15, "dex": "native",
            "account_role": "vault", "account_label": "Vault",
        },
    ],
}


class TestCmdStatusTwoWallets:
    """cmd_status must show both positions and the correct total equity."""

    def _run(self):
        buf = BufferRenderer()
        with (
            patch("common.account_state.fetch_registered_account_state", return_value=_MOCK_TWO_WALLET_BUNDLE),
            patch("telegram.bot._get_current_price", return_value=33.0),
            patch("telegram.bot._get_market_oi", return_value=""),
            patch("telegram.bot._get_all_orders", return_value=[]),
        ):
            cmd_status(buf, "")
        return buf.messages[0]["text"]

    def test_shows_total_equity(self):
        text = self._run()
        assert "631.00" in text

    def test_shows_silver_position(self):
        text = self._run()
        assert "SILVER" in text

    def test_shows_btc_vault_position(self):
        text = self._run()
        assert "BTC" in text

    def test_shows_both_account_rows(self):
        text = self._run()
        assert "Main" in text
        assert "Vault" in text


class TestCmdOrdersTwoWallets:
    """cmd_orders must query all wallet addresses, not just MAIN_ADDR."""

    def test_fetches_from_both_accounts(self):
        """Verify _get_all_orders is called with vault address too."""
        buf = BufferRenderer()
        called_addrs: list = []

        def mock_orders(addr):
            called_addrs.append(addr)
            return []

        with (
            patch("common.account_state.fetch_registered_account_state", return_value=_MOCK_TWO_WALLET_BUNDLE),
            patch("telegram.bot._get_all_orders", side_effect=mock_orders),
        ):
            cmd_orders(buf, "")

        assert "0xmain" in called_addrs
        assert "0xvault" in called_addrs


class TestCmdPnlTwoWallets:
    """cmd_pnl must show all positions and total equity."""

    def test_shows_both_positions_and_equity(self):
        from telegram.commands.portfolio import cmd_pnl
        sent: list = []

        def mock_send(token, chat_id, text):
            sent.append(text)

        with (
            patch("telegram.commands.portfolio.fetch_registered_account_state", return_value=_MOCK_TWO_WALLET_BUNDLE),
            patch("telegram.bot.tg_send", mock_send),
        ):
            cmd_pnl("tok", "123", "")

        assert sent
        text = sent[0]
        assert "SILVER" in text
        assert "BTC" in text
        assert "631.00" in text


class TestCmdPositionVaultSlTp:
    """cmd_position must fetch orders for each wallet role, not main only."""

    def test_vault_position_gets_order_lookup(self):
        """Verify _get_all_orders is called for the vault address."""
        from telegram.commands.portfolio import cmd_position
        from exchange.helpers import _coin_matches as _cm

        called_addrs: list = []

        def mock_orders(addr):
            called_addrs.append(addr)
            if addr == "0xvault":
                # Simulate a stop-loss order on the vault BTC position
                return [{"coin": "BTC", "side": "S", "sz": "0", "limitPx": "75000",
                         "orderType": "Stop Market", "tpsl": "sl", "isTrigger": True,
                         "triggerPx": "75000", "oid": 9999}]
            return []

        sent: list = []

        def mock_send(token, chat_id, text):
            sent.append(text)

        with (
            patch("telegram.commands.portfolio.fetch_registered_account_state", return_value=_MOCK_TWO_WALLET_BUNDLE),
            patch("telegram.bot._get_all_orders", mock_orders),
            patch("telegram.bot._get_current_price", return_value=83000.0),
            patch("telegram.bot.tg_send", mock_send),
            patch("telegram.bot._liquidity_regime", return_value="NORMAL"),
            patch("common.authority.get_authority", return_value="manual"),
        ):
            cmd_position("tok", "123", "")

        assert "0xvault" in called_addrs, "vault orders were not fetched"
        assert sent
