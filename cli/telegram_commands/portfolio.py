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


def cmd_pnl(token: str, chat_id: str, _args: str) -> None:
    """Summarise unrealized PnL across all positions (main + vault)."""
    from cli.telegram_bot import (
        MAIN_ADDR,
        VAULT_ADDR,
        _get_account_values,
        _get_all_positions,
        _hl_post,
        tg_send,
    )

    lines = ["📈 *P&L Summary*", ""]

    # Main — all positions (native + xyz)
    positions = _get_all_positions(MAIN_ADDR)
    values = _get_account_values(MAIN_ADDR)
    main_val = values['native'] + values['xyz']

    total_upnl = 0.0
    for pos in positions:
        upnl = float(pos.get('unrealizedPnl', 0))
        total_upnl += upnl
        pnl_sign = "+" if upnl >= 0 else ""
        emoji = "✅" if upnl >= 0 else "🔻"
        lines.append(f"{emoji} {pos.get('coin')}: `{pnl_sign}${upnl:,.2f}`")

    # Vault (skip if no vault configured)
    vault = _hl_post({"type": "clearinghouseState", "user": VAULT_ADDR}) if VAULT_ADDR else {}
    vault_val = float(vault.get("marginSummary", {}).get("accountValue", 0))
    for p in vault.get("assetPositions", []):
        pos = p["position"]
        vupnl = float(pos.get('unrealizedPnl', 0))
        total_upnl += vupnl
        pnl_sign = "+" if vupnl >= 0 else ""
        emoji = "✅" if vupnl >= 0 else "🔻"
        lines.append(f"{emoji} Vault {pos['coin']}: `{pnl_sign}${vupnl:,.2f}`")

    upnl_emoji = "✅" if total_upnl >= 0 else "🔻"
    upnl_sign = "+" if total_upnl >= 0 else ""
    lines.append(f"\n{upnl_emoji} *Unrealized*")
    lines.append(f"  `{upnl_sign}${total_upnl:,.2f}`")
    spot_val = values.get('spot', 0)
    grand_total = main_val + spot_val + vault_val
    lines.append(f"\n💎 *Balances*")
    if main_val > 0 and spot_val > 0:
        lines.append(f"  Perps: `${main_val:,.2f}` | Spot: `${spot_val:,.2f}`")
    elif spot_val > 0:
        lines.append(f"  Spot: `${spot_val:,.2f}`")
    elif main_val > 0:
        lines.append(f"  Perps: `${main_val:,.2f}`")
    if vault_val > 0:
        lines.append(f"  Vault: `${vault_val:,.2f}`")
    lines.append(f"  Total: `${grand_total:,.2f}`")

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
    from cli.telegram_bot import (
        MAIN_ADDR,
        _coin_matches,
        _get_account_values,
        _get_all_orders,
        _get_all_positions,
        _get_current_price,
        _liquidity_regime,
        tg_send,
    )
    from common.authority import get_authority

    positions = _get_all_positions(MAIN_ADDR)
    values = _get_account_values(MAIN_ADDR)
    total_equity = values['native'] + values['xyz'] + values.get('spot', 0)

    if not positions:
        tg_send(token, chat_id, "No open positions.")
        return

    ts = datetime.now(timezone.utc).strftime('%H:%M UTC')
    lines = [f"*Positions* — {ts}", ""]

    # Fetch orders once (not per-position)
    all_orders = _get_all_orders(MAIN_ADDR)

    for pos in positions:
        coin = pos.get('coin', '?')
        size = float(pos.get('szi', 0))
        entry = float(pos.get('entryPx', 0))
        upnl = float(pos.get('unrealizedPnl', 0))
        liq = pos.get('liquidationPx')
        lev = pos.get('leverage', {})
        lev_val = lev.get('value', '?') if isinstance(lev, dict) else lev
        margin_used = float(pos.get('marginUsed', 0))

        direction = "LONG" if size > 0 else "SHORT"
        dir_dot = "🟢" if size > 0 else "🔴"
        pnl_sign = "+" if upnl >= 0 else ""

        # Current price
        current = _get_current_price(coin)
        px_str = f"`${current:,.2f}`" if current else "—"

        # Authority
        auth = get_authority(coin)
        auth_icon = {"agent": "🤖", "manual": "👤", "off": "⬛"}.get(auth, "")

        lines.append(f"{dir_dot} *{coin}* — {direction} {auth_icon} {auth}")
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
        for o in all_orders:
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
