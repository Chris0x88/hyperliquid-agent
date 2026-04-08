"""Shared formatting helpers for daemon iterator alerts.

BUG-FIX 2026-04-08 (alert-format): liquidation_monitor, protection_audit,
account_collector, and risk were emitting alert strings like
``mark=89500.0000 liq=82150.0000`` — no $ sign, no thousands separator,
4-decimal precision regardless of price magnitude. The operator received
unreadable key=value noise. This module centralises a small set of helpers
so every iterator emits consistent ``$X,XXX.XX`` numbers, comma-grouped
where appropriate, and with sensible decimal-precision-by-magnitude.

Helpers are pure functions with no I/O or daemon imports — safe to import
from any iterator without circular dependency risk.
"""
from __future__ import annotations

from typing import Any


def fmt_price(value: Any) -> str:
    """Format a numeric price as ``$X,XXX.XX`` with adaptive precision.

    Decimal precision adapts to magnitude so a $94 oil price reads as
    ``$94.93`` and a $89,500 BTC price reads as ``$89,500.00``, while a
    sub-dollar contract unit (e.g. SP500 at 0.2746) keeps enough digits
    to be useful (``$0.2746``). Negative values render with a leading
    minus sign.

    Returns ``$0.00`` for None/non-numeric input — never raises.
    """
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "$0.00"
    if x == 0:
        return "$0.00"
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1_000:
        body = f"{a:,.2f}"
    elif a >= 1:
        body = f"{a:,.2f}"
    elif a >= 0.01:
        body = f"{a:.4f}"
    else:
        body = f"{a:.6f}"
    return f"{sign}${body}"


def fmt_pnl(value: Any) -> str:
    """Format a P&L number with explicit sign: ``+$1,234.56`` or ``-$78.90``.

    Always includes a leading sign so ``+`` vs ``-`` is unambiguous in chat
    glance views. Returns ``+$0.00`` for None/non-numeric.
    """
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "+$0.00"
    if x >= 0:
        return f"+${x:,.2f}"
    return f"-${abs(x):,.2f}"


def fmt_pct(value: Any, decimals: int = 1) -> str:
    """Format a percentage value to N decimal places, e.g. ``3.1%``.

    Accepts a fraction (0.031) or whole number (3.1) — the caller is
    responsible for choosing units; this helper does NOT multiply by 100.
    """
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "0.0%"
    return f"{x:.{decimals}f}%"


def dir_dot(net_qty_or_direction: Any) -> str:
    """Return 🟢 for LONG, 🔴 for SHORT.

    Accepts a numeric net quantity (positive = long, negative = short) or
    a direction string (``"LONG"``/``"SHORT"`` or ``"long"``/``"short"``).
    Falls back to ⚪ for ambiguous input.
    """
    if isinstance(net_qty_or_direction, str):
        d = net_qty_or_direction.upper()
        if d == "LONG":
            return "🟢"
        if d == "SHORT":
            return "🔴"
        return "⚪"
    try:
        n = float(net_qty_or_direction)
    except (TypeError, ValueError):
        return "⚪"
    if n > 0:
        return "🟢"
    if n < 0:
        return "🔴"
    return "⚪"
