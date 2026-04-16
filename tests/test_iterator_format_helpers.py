"""Tests for cli/daemon/iterators/_format.py helpers.

These helpers were introduced 2026-04-08 to centralise human-friendly
``$X,XXX.XX`` price formatting across alert-emitting iterators
(liquidation_monitor, protection_audit, account_collector, journal).
The previous per-iterator ``:.4f`` format strings produced unreadable
key=value noise like ``mark=89500.0000 liq=82150.0000``.
"""
from __future__ import annotations

import pytest

from daemon.iterators._format import dir_dot, fmt_pct, fmt_pnl, fmt_price


class TestFmtPrice:

    def test_thousands_grouping_for_btc_scale(self):
        """BTC at $89,500 → ``$89,500.00`` with comma grouping."""
        assert fmt_price(89500) == "$89,500.00"
        assert fmt_price(89500.55) == "$89,500.55"

    def test_two_decimals_for_dollar_scale(self):
        """Oil at $94.93 → ``$94.93``, no extra zeros."""
        assert fmt_price(94.93) == "$94.93"
        assert fmt_price(112.19) == "$112.19"

    def test_four_decimals_for_sub_dollar(self):
        """SP500 contract unit at 0.2746 → keep precision."""
        assert fmt_price(0.2746) == "$0.2746"

    def test_six_decimals_for_micro_prices(self):
        """Sub-cent prices keep six decimals (e.g. SHIB-style)."""
        assert fmt_price(0.000123) == "$0.000123"

    def test_negative_renders_with_leading_minus(self):
        assert fmt_price(-1234.5) == "-$1,234.50"

    def test_zero_is_clean(self):
        assert fmt_price(0) == "$0.00"
        assert fmt_price(0.0) == "$0.00"

    def test_none_is_safe(self):
        assert fmt_price(None) == "$0.00"

    def test_string_garbage_is_safe(self):
        assert fmt_price("not-a-number") == "$0.00"

    def test_decimal_input_is_handled(self):
        from decimal import Decimal
        assert fmt_price(Decimal("89500.123")) == "$89,500.12"


class TestFmtPnl:

    def test_positive_has_explicit_plus(self):
        assert fmt_pnl(1234.56) == "+$1,234.56"

    def test_negative_has_minus(self):
        assert fmt_pnl(-78.9) == "-$78.90"

    def test_zero_is_plus_zero(self):
        assert fmt_pnl(0) == "+$0.00"

    def test_none_is_safe(self):
        assert fmt_pnl(None) == "+$0.00"


class TestFmtPct:

    def test_default_one_decimal(self):
        assert fmt_pct(3.1) == "3.1%"

    def test_custom_decimals(self):
        assert fmt_pct(3.14159, decimals=2) == "3.14%"

    def test_negative(self):
        assert fmt_pct(-15.0) == "-15.0%"


class TestDirDot:

    def test_long_string(self):
        assert dir_dot("LONG") == "🟢"
        assert dir_dot("long") == "🟢"

    def test_short_string(self):
        assert dir_dot("SHORT") == "🔴"

    def test_positive_qty_is_long(self):
        assert dir_dot(0.5) == "🟢"

    def test_negative_qty_is_short(self):
        assert dir_dot(-0.5) == "🔴"

    def test_zero_qty_is_neutral(self):
        assert dir_dot(0) == "⚪"

    def test_garbage_is_neutral(self):
        assert dir_dot("nonsense") == "⚪"
        assert dir_dot(None) == "⚪"
