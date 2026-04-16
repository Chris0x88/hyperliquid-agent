"""Portfolio Telegram commands — PnL, position detail, etc.

Wedge 2 of the cli/telegram_bot.py monolith split (2026-04-09). After
the lessons.py extraction (Wedge 1), this submodule moves the
deterministic portfolio-view commands. Bodies are unchanged from the
inline versions in telegram_bot.py — only their physical location moved.

Handlers exported:
    cmd_pnl       — profit & loss summary across main + vault
    cmd_position  — detailed position report with risk metrics + SL/TP audit

NOT moved in this wedge (keeping it small + safe):
- cmd_status     — uses the Renderer abstraction, different signature
- cmd_price      — uses Renderer too
- cmd_orders     — uses Renderer too

Those move in a future wedge that also handles the Renderer migration
or accepts the inconsistency. Per CLAUDE.md "minimal changes" — this
wedge ships only the (token, chat_id, args)-shaped handlers.

The lazy imports of `tg_send` + the `_get_*` helpers + the `MAIN_ADDR`
/ `VAULT_ADDR` constants inside each function avoid a circular
dependency with telegram_bot.py — same pattern lessons.py uses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from common.account_state import fetch_registered_account_state


def cmd_pnl(token: str, chat_id: str, _args: str) -> None:
    """Summarise unrealized PnL across all positions (main + vault)."""
    from telegram.bot import (
        tg_send,
    )

    lines = ["📈 *P&L Summary*", ""]
    bundle = fetch_registered_account_state()
    positions = bundle.get("positions", [])
    account = bundle.get("account", {})

    total_upnl = 0.0
    for pos in positions:
        upnl = float(pos.get('upnl', 0))
        total_upnl += upnl
        pnl_sign = "+" if upnl >= 0 else ""
        emoji = "✅" if upnl >= 0 else "🔻"
        label = pos.get("account_label", pos.get("account_role", "Account"))
        lines.append(f"{emoji} {label} {pos.get('coin')}: `{pnl_sign}${upnl:,.2f}`")

    upnl_emoji = "✅" if total_upnl >= 0 else "🔻"
    upnl_sign = "+" if total_upnl >= 0 else ""
    lines.append(f"\n{upnl_emoji} *Unrealized*")
    lines.append(f"  `{upnl_sign}${total_upnl:,.2f}`")
    lines.append(f"\n💎 *Balances*")
    lines.append(
        f"  Native: `${float(account.get('native_equity', 0)):,.2f}`"
        f" | xyz: `${float(account.get('xyz_equity', 0)):,.2f}`"
        f" | Spot: `${float(account.get('spot_usdc', 0)):,.2f}`"
    )
    for row in bundle.get("accounts", []):
        lines.append(f"  {row['label']}: `${row['total_equity']:,.2f}`")
    lines.append(f"  Total: `${float(account.get('total_equity', 0)):,.2f}`")

    # Profit lock ledger
    ledger = Path("data/daemon/profit_locks.jsonl")
    if ledger.exists():
        total_locked = sum(
            json.loads(line).get("locked_usd", 0)
            for line in ledger.read_text().splitlines()
            if line.strip()
        )
        if total_locked > 0:
            lines.append(f"🔒 Locked profits: `${total_locked:,.2f}`")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_position(token: str, chat_id: str, _args: str) -> None:
    """Detailed position report with risk metrics + per-asset authority +
    SL/TP audit. Deterministic — no AI."""
    from telegram.bot import (
        _coin_matches,
        _get_all_orders,
        _get_current_price,
        _liquidity_regime,
        tg_send,
    )
    from common.authority import get_authority

    bundle = fetch_registered_account_state()
    positions = bundle.get("positions", [])
    total_equity = float(bundle.get("account", {}).get("total_equity", 0))

    if not positions:
        tg_send(token, chat_id, "No open positions.")
        return

    ts = datetime.now(timezone.utc).strftime('%H:%M UTC')
    lines = [f"*Positions* — {ts}", ""]

    # Fetch orders once (not per-position)
    all_orders = _get_all_orders(next((a["address"] for a in bundle.get("accounts", []) if a.get("role") == "main"), ""))

    for pos in positions:
        coin = pos.get('coin', '?')
        size = float(pos.get('size', 0))
        entry = float(pos.get('entry', 0))
        upnl = float(pos.get('upnl', 0))
        liq = pos.get('liq')
        lev_val = pos.get('leverage', '?')
        margin_used = float(pos.get('margin_used', 0))
        account_label = pos.get("account_label", pos.get("account_role", "Account"))

        direction = "LONG" if size > 0 else "SHORT"
        dir_dot = "🟢" if size > 0 else "🔴"
        pnl_sign = "+" if upnl >= 0 else ""

        # Current price
        current = _get_current_price(coin)
        px_str = f"`${current:,.2f}`" if current else "—"

        # Authority
        auth = get_authority(coin)
        auth_icon = {"agent": "🤖", "manual": "👤", "off": "⬛"}.get(auth, "")

        lines.append(f"{dir_dot} *{coin}* — {direction} {auth_icon} {auth} • _{account_label}_")
        lines.append(f"  Entry `${entry:,.2f}` → Now {px_str}")
        lines.append(f"  Size `{abs(size):.1f}` | `{lev_val}x` | Margin `${margin_used:,.2f}`")
        lines.append(f"  uPnL `{pnl_sign}${upnl:,.2f}`")

        if liq and liq != "N/A":
            liq_f = float(liq)
            ref_price = current if current else entry
            if ref_price > 0 and liq_f > 0:
                liq_dist = abs(ref_price - liq_f) / ref_price * 100
                lines.append(f"  Liq `${liq_f:,.2f}` (`{liq_dist:.1f}%` away)")
            else:
                lines.append(f"  Liq `${liq_f:,.2f}`")

        # SL/TP check
        sl_found = False
        tp_found = False
        for o in all_orders if pos.get("account_role") == "main" else []:
            if not _coin_matches(o.get('coin', ''), coin):
                continue
            tpsl = o.get('tpsl', '')
            order_type = o.get('orderType', '')
            is_sl = tpsl == 'sl' or order_type in ('Stop Market', 'Stop Limit')
            is_tp = tpsl == 'tp' or order_type in ('Take Profit Market', 'Take Profit Limit')
            if not is_tp and o.get('reduceOnly') and not is_sl:
                is_tp = True
            if is_sl:
                sl_found = True
            elif is_tp:
                tp_found = True
        sl_str = "SET" if sl_found else "MISSING"
        tp_str = "SET" if tp_found else "MISSING"
        warn = ""
        if not sl_found or not tp_found:
            warn = " ⚠"
        lines.append(f"  SL: {sl_str} | TP: {tp_str}{warn}")
        lines.append("")

    lines.append(f"Equity: `${total_equity:,.2f}` | {_liquidity_regime()}")
    tg_send(token, chat_id, "\n".join(lines))
