"""Interactive inline-button menu system for the Telegram bot.

Extracted mechanically from cli/telegram_bot.py (2026-04-11).
No behaviour changes — just a file split for maintainability.

Contains:
- Menu builders (_build_main_menu, _build_position_detail, etc.)
- _cached_positions, _pos_cache
- _active_account, _get_active_addr
- _btn helper
- _menu_dispatch
- _handle_menu_callback (central mn: router)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from telegram.api import (
    tg_send, tg_send_grid, tg_edit_grid, tg_answer_callback,
)
from exchange.helpers import (
    _get_all_orders, _get_current_price, _get_account_values,
    _coin_matches, resolve_coin,
)
from common.account_resolver import resolve_main_wallet, resolve_vault_address as _resolve_vault

log = logging.getLogger("telegram_bot")

# ── Address constants (mirror telegram_bot.py) ──────────────
MAIN_ADDR = resolve_main_wallet(required=True)
VAULT_ADDR = _resolve_vault(required=False) or ""

# ── Module-level state ──────────────────────────────────────
_pos_cache: dict = {"ts": 0, "data": []}
_active_account = "main"  # "main" or "vault"


def _get_active_addr() -> str:
    """Return address for the active account context."""
    if _active_account == "vault" and VAULT_ADDR:
        return VAULT_ADDR
    return MAIN_ADDR


def _cached_positions() -> list:
    """Get positions with 5-second cache."""
    from common.account_state import fetch_registered_account_state

    now = time.time()
    if now - _pos_cache["ts"] < 5:
        return _pos_cache["data"]
    bundle = fetch_registered_account_state(include_vault=True, include_subs=True)
    if _active_account == "vault":
        result = [p for p in bundle.get("positions", []) if p.get("account_role") == "vault"]
    else:
        result = [
            p for p in bundle.get("positions", [])
            if p.get("account_role") == "main" or str(p.get("account_role", "")).startswith("sub")
        ]
    _pos_cache["ts"] = now
    _pos_cache["data"] = result
    return result


def _btn(text: str, data: str) -> dict:
    """Shorthand for inline keyboard button."""
    return {"text": text, "callback_data": data}


def _build_main_menu() -> tuple:
    """Build main menu text + button grid. Returns (text, rows)."""
    from common.account_state import fetch_registered_account_state

    ts = datetime.now(timezone.utc).strftime('%H:%M UTC')
    positions = _cached_positions()
    orders = _get_all_orders(_get_active_addr())
    bundle = fetch_registered_account_state()
    active_row = next(
        (row for row in bundle.get("accounts", []) if row["address"] == _get_active_addr()),
        {"total_equity": 0},
    )
    total = float(active_row.get("total_equity", 0))

    acct_label = "Vault" if _active_account == "vault" else "Main"
    lines = [f"\U0001f4ca *Trading Terminal* \u2014 {ts}", f"Account: *{acct_label}* | Equity: `${total:,.2f}`", ""]

    rows = []

    if positions:
        lines.append(f"*Positions* ({len(positions)})")
        # Position buttons: 2 per row
        pos_btns = []
        for pos in positions[:6]:
            coin = pos.get("coin", "?")
            size = float(pos.get("size", 0))
            upnl = float(pos.get("upnl", 0))
            direction = "L" if size > 0 else "S"
            pnl_icon = "\U0001f7e2" if upnl >= 0 else "\U0001f534"
            label = f"{pnl_icon} {coin} {direction} {upnl:+.0f}"
            pos_btns.append(_btn(label, f"mn:p:{coin}"))
        # Lay out 2 per row
        for i in range(0, len(pos_btns), 2):
            rows.append(pos_btns[i:i+2])
        if len(positions) > 6:
            lines.append(f"  _...and {len(positions) - 6} more_")
        lines.append("")
    else:
        lines.append("_No open positions_\n")

    # Trade + utility rows
    order_count = len(orders)
    rows.append([
        _btn("\U0001f4c8 New Trade", "mn:trade"),
        _btn(f"\U0001f4cb Orders ({order_count})", "mn:ord"),
    ])
    rows.append([
        _btn("\U0001f4b0 PnL", "mn:pnl"),
        _btn("\U0001f4ca Watchlist", "mn:watch"),
    ])
    rows.append([
        _btn("\u2699\ufe0f Tools", "mn:tools"),
    ])

    return "\n".join(lines), rows


def _build_position_detail(coin: str) -> tuple:
    """Build position detail view. Returns (text, rows)."""
    positions = _cached_positions()
    pos = None
    for p in positions:
        if _coin_matches(p.get("coin", ""), coin):
            pos = p
            break

    if not pos:
        return f"No open position for `{coin}`", [[_btn("\u00ab Back", "mn:main")]]

    size = float(pos.get("size", pos.get("szi", 0)))
    entry = float(pos.get("entry", pos.get("entryPx", 0)))
    upnl = float(pos.get("upnl", pos.get("unrealizedPnl", 0)))
    lev = pos.get("leverage", {})
    lev_val = lev.get("value", "?") if isinstance(lev, dict) else lev
    liq = pos.get("liq", pos.get("liquidationPx"))
    coin_name = pos.get("coin", coin)

    direction = "LONG" if size > 0 else "SHORT"
    dir_icon = "\U0001f7e2" if size > 0 else "\U0001f534"
    pnl_sign = "+" if upnl >= 0 else ""
    current = _get_current_price(coin_name)
    px_str = f"${current:,.2f}" if current else "\u2014"
    notional = abs(size * entry)

    lines = [
        f"{dir_icon} *{coin_name}* \u2014 {direction}",
        f"Entry `${entry:,.2f}` \u2192 Now `{px_str}`",
        f"Size `{abs(size):.1f}` | `{lev_val}x` | Notional `${notional:,.0f}`",
        f"uPnL `{pnl_sign}${upnl:,.2f}`",
    ]

    if liq and liq != "N/A":
        liq_f = float(liq)
        if current and current > 0:
            dist = abs(current - liq_f) / current * 100
            lines.append(f"Liq `${liq_f:,.2f}` ({dist:.1f}% away)")

    # Check SL/TP from orders — smart grouping
    orders = _get_all_orders(_get_active_addr())
    sl_orders = []
    tp_orders = []
    pos_size = abs(size)

    for o in orders:
        if not _coin_matches(o.get("coin", ""), coin_name):
            continue
        tpsl = o.get("tpsl", "")
        order_type = o.get("orderType", "")

        is_sl = tpsl == "sl" or order_type in ("Stop Market", "Stop Limit")
        is_tp = tpsl == "tp" or order_type in ("Take Profit Market", "Take Profit Limit")
        if not is_tp and o.get("reduceOnly") and not is_sl:
            is_tp = True  # reduceOnly non-SL = TP

        o_sz = float(o.get("sz", 0))
        o_px = o.get("triggerPx") or o.get("limitPx", "?")

        if is_sl:
            sl_orders.append({"px": o_px, "sz": o_sz, "type": order_type})
        elif is_tp:
            tp_orders.append({"px": o_px, "sz": o_sz, "type": order_type})

    # Display SL orders
    lines.append("")
    if sl_orders:
        for sl in sl_orders:
            if sl["sz"] == 0:
                lines.append(f"\U0001f6e1 SL: `${sl['px']}` (whole position)")
            else:
                lines.append(f"\U0001f6e1 SL: `${sl['px']}` ({sl['sz']:.1f} units)")
    else:
        lines.append("\U0001f6e1 SL: \u26a0\ufe0f *MISSING*")

    # Display TP orders — smart: check coverage
    if tp_orders:
        # Sort by price (ascending for longs, descending for shorts)
        tp_orders.sort(key=lambda x: float(x["px"]) if x["px"] != "?" else 0,
                       reverse=(size < 0))  # shorts want descending
        covered = 0.0
        for tp in tp_orders:
            if tp["sz"] == 0:
                lines.append(f"\U0001f3af TP: `${tp['px']}` (whole position)")
                covered = pos_size  # whole position covers everything
            else:
                if covered >= pos_size:
                    lines.append(f"\U0001f3af TP: `${tp['px']}` ({tp['sz']:.1f} \u2014 _covered by earlier TP_)")
                else:
                    lines.append(f"\U0001f3af TP: `${tp['px']}` ({tp['sz']:.1f} units)")
                    covered += tp["sz"]
        if covered < pos_size and not any(t["sz"] == 0 for t in tp_orders):
            uncovered = pos_size - covered
            lines.append(f"  \u26a0\ufe0f `{uncovered:.1f}` units have no TP")
    else:
        lines.append("\U0001f3af TP: \u26a0\ufe0f *MISSING*")

    rows = [
        [_btn("\U0001f534 Close Position", f"mn:cl:{coin_name}")],
        [_btn("\U0001f6e1 Set SL", f"mn:sl:{coin_name}"), _btn("\U0001f3af Set TP", f"mn:tp:{coin_name}")],
        [_btn("\U0001f4c9 4h", f"mn:ch:{coin_name}:4"), _btn("\U0001f4ca 24h", f"mn:ch:{coin_name}:24"), _btn("\U0001f4c8 7d", f"mn:ch:{coin_name}:168")],
        [_btn("\U0001f50d Technicals", f"mn:mk:{coin_name}")],
        [_btn("\u00ab Back", "mn:main")],
    ]

    return "\n".join(lines), rows


def _build_watchlist_menu() -> tuple:
    """Build watchlist coin grid. Returns (text, rows)."""
    from common.watchlist import load_watchlist
    wl = load_watchlist()

    lines = ["\U0001f4ca *Watchlist*", ""]
    rows = []
    btns = []
    for m in wl:
        coin = m["coin"]
        price = _get_current_price(coin)
        if price:
            label = f"{m['display']} ${price:,.2f}"
        else:
            label = m["display"]
        btns.append(_btn(label, f"mn:mk:{coin}"))

    # 2 per row
    for i in range(0, len(btns), 2):
        rows.append(btns[i:i+2])

    rows.append([_btn("\u00ab Back", "mn:main")])
    return "\n".join(lines), rows


def _build_trade_menu() -> tuple:
    """Build trade market selection. Returns (text, rows)."""
    from common.watchlist import load_watchlist
    wl = load_watchlist()

    lines = ["\U0001f4c8 *New Trade \u2014 Select Market*", ""]
    rows = []
    btns = []
    for m in wl:
        coin = m["coin"]
        price = _get_current_price(coin)
        if price:
            label = f"{m['display']} ${price:,.2f}"
        else:
            label = m["display"]
        btns.append(_btn(label, f"mn:buy:{coin}"))

    for i in range(0, len(btns), 2):
        rows.append(btns[i:i+2])

    rows.append([_btn("\u00ab Back", "mn:main")])
    return "\n".join(lines), rows


def _build_trade_side_menu(coin: str) -> tuple:
    """Build buy/sell selection for a specific coin. Returns (text, rows)."""
    from telegram.approval import _find_position

    price = _get_current_price(coin)
    px_str = f"${price:,.2f}" if price else "\u2014"
    display = coin.replace("xyz:", "")

    # Check if already have a position
    pos = _find_position(coin)
    pos_line = ""
    if pos:
        size = float(pos.get("size", pos.get("szi", 0)))
        direction = "LONG" if size > 0 else "SHORT"
        upnl = float(pos.get("upnl", pos.get("unrealizedPnl", 0)))
        pos_line = f"\nExisting: {direction} `{abs(size):.1f}` | uPnL `${upnl:+,.2f}`"

    # Active account
    acct_label = "Vault" if _active_account == "vault" else "Main"

    lines = [
        f"\U0001f4c8 *Trade {display}*",
        f"Price: `{px_str}`",
        f"Account: *{acct_label}*",
    ]
    if pos_line:
        lines.append(pos_line)

    rows = [
        [_btn(f"\U0001f7e2 BUY {display}", f"mn:side:{coin}:buy"),
         _btn(f"\U0001f534 SELL {display}", f"mn:side:{coin}:sell")],
        [_btn("\u00ab Back", "mn:trade")],
    ]

    return "\n".join(lines), rows


def _build_account_menu() -> tuple:
    """Build account switcher. Returns (text, rows)."""
    from common.account_state import fetch_registered_account_state

    lines = [f"\U0001f504 *Account Switcher*", ""]
    bundle = fetch_registered_account_state()

    # Main account
    main_row = next((row for row in bundle.get("accounts", []) if row.get("role") == "main"), None)
    main_total = float(main_row.get("total_equity", 0)) if main_row else 0.0
    main_check = " \u2705" if _active_account == "main" else ""
    lines.append(f"Main: `${main_total:,.2f}`{main_check}")

    # Vault
    if VAULT_ADDR:
        vault_row = next((row for row in bundle.get("accounts", []) if row.get("role") == "vault"), None)
        vault_val = float(vault_row.get("total_equity", 0)) if vault_row else 0.0
        vault_check = " \u2705" if _active_account == "vault" else ""
        lines.append(f"Vault: `${vault_val:,.2f}`{vault_check}")

    rows = [
        [_btn(f"\U0001f464 Main{main_check}", "mn:acct:main")],
    ]
    if VAULT_ADDR:
        vault_check_btn = " \u2705" if _active_account == "vault" else ""
        rows.append([_btn(f"\U0001f3e6 Vault{vault_check_btn}", "mn:acct:vault")])

    rows.append([_btn("\u00ab Back", "mn:tools")])
    return "\n".join(lines), rows


def _build_tools_menu() -> tuple:
    """Build tools sub-menu. Returns (text, rows)."""
    acct_label = "Vault" if _active_account == "vault" else "Main"
    text = f"\u2699\ufe0f *Tools* \u2014 Account: *{acct_label}*"
    rows = [
        [_btn(f"\U0001f504 Switch Account ({acct_label})", "mn:acct")],
        [_btn("\U0001f4ca Status", "mn:run:status"), _btn("\U0001f3e5 Health", "mn:run:health")],
        [_btn("\U0001f527 Diag", "mn:run:diag"), _btn("\U0001f916 Models", "mn:run:models")],
        [_btn("\U0001f511 Authority", "mn:run:authority"), _btn("\U0001f9e0 Memory", "mn:run:memory")],
        [_btn("\u00ab Back", "mn:main")],
    ]
    return text, rows


def _menu_dispatch(token: str, chat_id: str, handler, args: str) -> None:
    """Call a command handler with correct signature (Renderer-based or legacy).

    Needs RENDERER_COMMANDS from telegram_bot — imported lazily to avoid circular imports.
    """
    from telegram.bot import RENDERER_COMMANDS
    if handler in RENDERER_COMMANDS:
        from common.renderer import TelegramRenderer
        handler(TelegramRenderer(token, chat_id), args)
    else:
        handler(token, chat_id, args)


def _handle_menu_callback(token: str, chat_id: str, cb_id: str, data: str, message_id: int) -> None:
    """Central router for all mn: prefixed callbacks."""
    from telegram.approval import (
        _handle_close_position, _handle_sl_prompt, _handle_tp_prompt,
        _handle_trade_size_prompt,
    )

    # Answer callback immediately to avoid Telegram timeout
    tg_answer_callback(token, cb_id)

    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "main":
        text, rows = _build_main_menu()
        tg_edit_grid(token, chat_id, message_id, text, rows)

    elif action == "p" and len(parts) >= 3:
        coin = ":".join(parts[2:])  # handle xyz:BRENTOIL
        text, rows = _build_position_detail(coin)
        tg_edit_grid(token, chat_id, message_id, text, rows)

    elif action == "cl" and len(parts) >= 3:
        coin = ":".join(parts[2:])
        _handle_close_position(token, chat_id, coin)

    elif action == "sl" and len(parts) >= 3:
        coin = ":".join(parts[2:])
        _handle_sl_prompt(token, chat_id, coin)

    elif action == "tp" and len(parts) >= 3:
        coin = ":".join(parts[2:])
        _handle_tp_prompt(token, chat_id, coin)

    elif action == "ch" and len(parts) >= 4:
        coin = parts[2]
        hours = parts[3]
        # Handle xyz coins
        if len(parts) >= 5 and parts[2] == "xyz":
            coin = f"xyz:{parts[3]}"
            hours = parts[4]
        from telegram.bot import cmd_chart
        cmd_chart(token, chat_id, f"{coin} {hours}")

    elif action == "mk" and len(parts) >= 3:
        coin = ":".join(parts[2:])
        from telegram.bot import cmd_market
        cmd_market(token, chat_id, coin)

    elif action == "watch":
        text, rows = _build_watchlist_menu()
        tg_edit_grid(token, chat_id, message_id, text, rows)

    elif action == "tools":
        text, rows = _build_tools_menu()
        tg_edit_grid(token, chat_id, message_id, text, rows)

    elif action == "ord":
        from telegram.bot import cmd_orders
        _menu_dispatch(token, chat_id, cmd_orders, "")

    elif action == "pnl":
        from telegram.commands.portfolio import cmd_pnl
        _menu_dispatch(token, chat_id, cmd_pnl, "")

    elif action == "run" and len(parts) >= 3:
        cmd_name = parts[2]
        from telegram.bot import (
            cmd_status, cmd_health, cmd_diag, cmd_models, cmd_authority, cmd_memory,
        )
        run_map = {
            "status": cmd_status, "health": cmd_health, "diag": cmd_diag,
            "models": cmd_models, "authority": cmd_authority, "memory": cmd_memory,
        }
        handler = run_map.get(cmd_name)
        if handler:
            _menu_dispatch(token, chat_id, handler, "")

    # ── Trade flow ──
    elif action == "trade":
        text, rows = _build_trade_menu()
        tg_edit_grid(token, chat_id, message_id, text, rows)

    elif action == "buy" and len(parts) >= 3:
        coin = ":".join(parts[2:])
        text, rows = _build_trade_side_menu(coin)
        tg_edit_grid(token, chat_id, message_id, text, rows)

    elif action == "side" and len(parts) >= 4:
        # mn:side:xyz:CL:buy → coin=xyz:CL, side=buy
        # Find the last part as side, rest is coin
        side = parts[-1]
        coin = ":".join(parts[2:-1])
        _handle_trade_size_prompt(token, chat_id, coin, side)

    # ── Account switching ──
    elif action == "acct" and len(parts) >= 3:
        global _active_account
        _active_account = parts[2]
        tg_send(token, chat_id, f"\u2705 Switched to *{_active_account.title()}* account")
        # Refresh main menu
        text, rows = _build_main_menu()
        tg_send_grid(token, chat_id, text, rows)

    elif action == "acct":
        text, rows = _build_account_menu()
        tg_edit_grid(token, chat_id, message_id, text, rows)
