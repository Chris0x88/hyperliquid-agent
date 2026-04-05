#!/usr/bin/env python3
"""Real-time Telegram bot — polls every 2s, executes commands as fixed code.

NO AI credits burned. Simple commands (/status, /price, /help, /orders, /pnl)
run pure Python against the HyperLiquid API directly. Only free-text messages
that need Claude's brain get queued for the scheduled task.

Run as a background process:
    python3 -m cli.telegram_bot &

Or via the CLI:
    hl telegram start
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from common.renderer import Renderer, TelegramRenderer

# Ensure project root on path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("telegram_bot")

# Diagnostics
try:
    from common.diagnostics import diag as _diag
except ImportError:
    _diag = None

HL_API = "https://api.hyperliquid.xyz/info"
from common.account_resolver import resolve_main_wallet, resolve_vault_address as _resolve_vault
MAIN_ADDR = resolve_main_wallet(required=True)
VAULT_ADDR = _resolve_vault(required=False) or ""
POLL_INTERVAL = 2.0  # seconds
COMMAND_QUEUE = Path("data/daemon/telegram_commands.jsonl")
PID_FILE = Path("data/daemon/telegram_bot.pid")
LAST_UPDATE_FILE = Path("data/daemon/telegram_last_update_id.txt")

# ── Watchlist: markets we track (loaded from data/config/watchlist.json) ──
from common.watchlist import (
    load_watchlist as _load_wl,
    get_watchlist_as_tuples as _get_wl_tuples,
    get_coin_aliases as _get_aliases,
    get_watchlist_coins as _get_coins,
)

WATCHLIST = _get_wl_tuples()
COIN_ALIASES: dict[str, str] = _get_aliases()
APPROVED_MARKETS = _get_coins()


def _coin_matches(universe_name: str, target: str) -> bool:
    """Check if a universe asset name matches a target coin identifier.

    CRITICAL: The xyz clearinghouse returns universe names WITH the 'xyz:' prefix
    (e.g. 'xyz:BRENTOIL'), while native clearinghouse does NOT (e.g. 'BTC').
    This function handles both forms so callers don't need to worry about it.

    Examples:
        _coin_matches("xyz:BRENTOIL", "BRENTOIL") → True
        _coin_matches("xyz:BRENTOIL", "xyz:BRENTOIL") → True
        _coin_matches("BTC", "BTC") → True
    """
    if universe_name == target:
        return True
    bare_universe = universe_name.replace("xyz:", "")
    bare_target = target.replace("xyz:", "")
    return bare_universe == bare_target


def resolve_coin(text: str) -> Optional[str]:
    """Resolve user input to an HL coin identifier."""
    t = text.strip().lower()
    if t in COIN_ALIASES:
        return COIN_ALIASES[t]
    # Try with xyz: prefix
    if f"xyz:{t}" in COIN_ALIASES:
        return COIN_ALIASES[f"xyz:{t}"]
    return None


# ── Keychain helpers ─────────────────────────────────────────

def _keychain_read(key_name: str) -> Optional[str]:
    try:
        r = subprocess.run(
            ["security", "find-generic-password",
             "-s", "hl-agent-telegram", "-a", key_name, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


# ── Telegram API helpers ─────────────────────────────────────

def tg_send(token: str, chat_id: str, text: str, markdown: bool = True) -> bool:
    """Send a Telegram message. Uses Markdown by default, falls back to plain text."""
    try:
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if markdown:
            payload["parse_mode"] = "Markdown"
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=10,
        )
        result = r.json()
        if result.get("ok"):
            return True
        # Markdown failed — retry as plain text
        if markdown:
            payload.pop("parse_mode", None)
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload, timeout=10,
            )
            return r.json().get("ok", False)
        return False
    except Exception as e:
        log.warning("Send failed: %s", e)
        return False


def tg_send_buttons(token: str, chat_id: str, text: str, buttons: list) -> bool:
    """Send a message with inline keyboard buttons.

    buttons: list of dicts with 'text' and 'callback_data' keys.
    Laid out one button per row.
    """
    try:
        keyboard = [[btn] for btn in buttons]
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": keyboard},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=10,
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.warning("Send buttons failed: %s", e)
        return False


def tg_remove_buttons(token: str, chat_id: str, message_id: int) -> bool:
    """Remove inline keyboard buttons from a message."""
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": {"inline_keyboard": []},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
            json=payload, timeout=5,
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.warning("Remove buttons failed: %s", e)
        return False


def tg_answer_callback(token: str, callback_id: str, text: str = "") -> None:
    """Answer a callback query (dismisses the loading spinner on the button)."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=5,
        )
    except Exception:
        pass


def tg_send_grid(token: str, chat_id: str, text: str, rows: list) -> dict:
    """Send a message with inline keyboard grid. rows = [[btn, btn], [btn], ...]."""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": rows},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=10,
        )
        return r.json()
    except Exception as e:
        log.warning("Send grid failed: %s", e)
        return {}


def tg_edit_grid(token: str, chat_id: str, message_id: int, text: str, rows: list) -> bool:
    """Edit an existing message text + inline keyboard in-place."""
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": rows},
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/editMessageText",
            json=payload, timeout=10,
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.warning("Edit grid failed: %s", e)
        return False


def tg_get_updates(token: str, offset: int) -> list:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": 2},
            timeout=10,
        )
        data = r.json()
        return data.get("result", []) if data.get("ok") else []
    except Exception:
        return []


# ── HL API helpers (pure Python, no AI) ──────────────────────

def _hl_post(payload: dict) -> dict:
    try:
        return requests.post(HL_API, json=payload, timeout=10).json()
    except Exception:
        return {}


def _get_all_positions(addr: str) -> list:
    """Get positions from BOTH native and xyz clearinghouses."""
    positions = []
    for dex in ['', 'xyz']:
        payload = {'type': 'clearinghouseState', 'user': addr}
        if dex:
            payload['dex'] = dex
        state = _hl_post(payload)
        for p in state.get('assetPositions', []):
            pos = p.get('position', {})
            pos['_dex'] = dex or 'native'
            positions.append(pos)
    return positions


def _refresh_candle_cache_for_market(cache, coin: str, lookback_hours: int = 168) -> None:
    """Fetch fresh candles for a market across 1h, 4h, 1d intervals.

    Called by /market before building snapshots so signals are never stale.
    Skips intervals already fresh (<1h old).
    """
    now_ms = int(time.time() * 1000)
    for interval in ["1h", "4h", "1d"]:
        try:
            date_range = cache.date_range(coin, interval)
            if date_range and (now_ms - date_range[1]) < 3_600_000:
                continue  # Fresh enough

            start_ms = date_range[1] if date_range else now_ms - (lookback_hours * 3_600_000)
            payload = {
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": interval,
                        "startTime": start_ms, "endTime": now_ms},
            }
            r = requests.post(HL_API, json=payload, timeout=10)
            if r.status_code == 200:
                candles = r.json()
                if isinstance(candles, list) and candles:
                    cache.store_candles(coin, interval, candles)
            time.sleep(0.15)
        except Exception:
            pass


def _get_all_orders(addr: str) -> list:
    """Get open orders from BOTH clearinghouses (rich format with orderType/triggerPx)."""
    orders = []
    for dex in ['', 'xyz']:
        payload = {'type': 'frontendOpenOrders', 'user': addr}
        if dex:
            payload['dex'] = dex
        result = _hl_post(payload) or []
        for o in result:
            o['_dex'] = dex or 'native'
        orders.extend(result)
    return orders


def _get_account_values(addr: str) -> dict:
    """Get account values from both clearinghouses + spot USDC."""
    result = {'native': 0.0, 'xyz': 0.0, 'spot': 0.0}
    for dex in ['', 'xyz']:
        payload = {'type': 'clearinghouseState', 'user': addr}
        if dex:
            payload['dex'] = dex
        state = _hl_post(payload)
        val = float(state.get('marginSummary', {}).get('accountValue', 0))
        result[dex or 'native'] = val
    # Spot USDC
    spot = _hl_post({"type": "spotClearinghouseState", "user": addr})
    for b in spot.get("balances", []):
        if b.get("coin") == "USDC":
            result['spot'] = float(b.get("total", 0))
    return result


def _get_market_oi(coin: str, dex: str = '') -> str:
    """Get open interest + 24h volume for a market. Returns formatted string."""
    try:
        payload: dict = {"type": "metaAndAssetCtxs"}
        if dex == 'xyz':
            payload["dex"] = "xyz"
        data = _hl_post(payload)
        if isinstance(data, list) and len(data) >= 2:
            meta = data[0]
            ctxs = data[1]
            universe = meta.get("universe", [])
            for i, ctx in enumerate(ctxs):
                if i < len(universe) and _coin_matches(universe[i].get("name", ""), coin):
                    oi = float(ctx.get("openInterest", 0))
                    vol = float(ctx.get("dayNtlVlm", 0))
                    parts = []
                    if oi > 0:
                        parts.append(f"OI `${oi / 1e6:.1f}M`")
                    if vol > 0:
                        parts.append(f"Vol `${vol / 1e6:.1f}M`")
                    return " • ".join(parts) if parts else ""
    except Exception:
        pass
    return ""


def _get_current_price(coin: str) -> Optional[float]:
    """Get current mid price for a coin (checks both clearinghouses)."""
    try:
        mids = _hl_post({"type": "allMids"})
        if coin in mids:
            return float(mids[coin])
    except Exception:
        pass
    try:
        mids = _hl_post({"type": "allMids", "dex": "xyz"})
        for k, v in mids.items():
            if k.replace("xyz:", "") == coin or k == coin:
                return float(v)
    except Exception:
        pass
    return None


def _get_all_market_ctx() -> dict:
    """Fetch metaAndAssetCtxs from both clearinghouses.

    Returns dict mapping coin name -> {"markPx": float, "prevDayPx": float}.
    Handles both native (BTC, ETH) and xyz (BRENTOIL, GOLD, etc.) markets.
    """
    result: dict = {}
    for dex in ['', 'xyz']:
        try:
            payload: dict = {"type": "metaAndAssetCtxs"}
            if dex:
                payload["dex"] = dex
            data = _hl_post(payload)
            if isinstance(data, list) and len(data) >= 2:
                universe = data[0].get("universe", [])
                ctxs = data[1]
                for i, ctx in enumerate(ctxs):
                    if i < len(universe):
                        name = universe[i].get("name", "")
                        mark = float(ctx.get("markPx", 0))
                        prev = float(ctx.get("prevDayPx", 0))
                        if mark > 0:
                            result[name] = {"markPx": mark, "prevDayPx": prev}
        except Exception:
            pass
    return result


def _liquidity_regime() -> str:
    now = datetime.now(timezone.utc)
    weekend = now.weekday() >= 5
    after_hours = now.hour >= 22 or now.hour < 6
    if weekend and after_hours:
        return "DANGEROUS"
    elif weekend:
        return "WEEKEND"
    elif after_hours:
        return "LOW"
    return "NORMAL"


# ── Command handlers (fixed code, zero AI) ───────────────────

def cmd_status(renderer: Renderer, _args: str) -> None:
    ts = datetime.now(timezone.utc).strftime('%a %H:%M UTC')
    lines = [f"*Portfolio* — {ts}", ""]

    # Spot balances (fetched via _get_account_values below, but need display here)
    spot_total = 0.0  # populated from _get_account_values

    # ALL perp positions (native + xyz clearinghouses)
    positions = _get_all_positions(MAIN_ADDR)
    if positions:
        for pos in positions:
            coin = pos.get('coin', '?')
            size = float(pos.get('szi', 0))
            entry = float(pos.get('entryPx', 0))
            upnl = float(pos.get('unrealizedPnl', 0))
            lev = pos.get('leverage', {})
            liq = pos.get('liquidationPx')
            lev_val = lev.get('value', '?') if isinstance(lev, dict) else lev
            notional = abs(size * entry)

            direction = "LONG" if size > 0 else "SHORT"
            dir_dot = "🟢" if size > 0 else "🔴"
            pnl_sign = "+" if upnl >= 0 else ""

            # Current price
            current = _get_current_price(coin)
            px_str = f"`${current:,.2f}`" if current else "—"

            # OI / volume for liquidity
            oi_str = _get_market_oi(coin, pos.get('_dex', ''))

            lines.append(f"{dir_dot} *{coin}* — {direction}")
            lines.append(f"  Entry `${entry:,.2f}` → Now {px_str}")
            lines.append(f"  Size `{abs(size):.1f}` | `{lev_val}x` | Notional `${notional:,.0f}`")
            lines.append(f"  uPnL `{pnl_sign}${upnl:,.2f}`")
            if liq and liq != "N/A":
                liq_f = float(liq)
                if current and current > 0:
                    dist = abs(current - liq_f) / current * 100
                    lines.append(f"  Liq `${liq_f:,.2f}` ({dist:.1f}% away)")
            if oi_str:
                lines.append(f"  {oi_str}")
            lines.append("")
        # Check for unwatched positions and flag them
        from common.watchlist import get_watchlist_coins, get_coin_aliases
        watched = set(get_watchlist_coins())
        aliases = get_coin_aliases()
        for pos in positions:
            coin = pos.get('coin', '?')
            # Check if this coin is watched (with or without xyz: prefix)
            is_watched = (
                coin in watched
                or f"xyz:{coin}" in watched
                or coin.lower() in aliases
            )
            if not is_watched:
                lines.append(f"⚠️ `{coin}` not in watchlist — run `/addmarket {coin.lower()}` for full monitoring")
                lines.append("")
    else:
        lines.append("No open positions\n")

    # Account values
    values = _get_account_values(MAIN_ADDR)
    total_perps = values['native'] + values['xyz']
    spot_total = values.get('spot', 0)
    grand_total = total_perps + spot_total

    lines.append(f"\n*Equity*")
    lines.append(f"  `${grand_total:,.2f}`")
    if total_perps > 0 and spot_total > 0:
        lines.append(f"  Perps `${total_perps:,.2f}` • Spot `${spot_total:,.2f}`")

    # Orders (compact)
    orders = _get_all_orders(MAIN_ADDR)
    if orders:
        lines.append(f"\n*Orders* ({len(orders)})")
        for o in orders[:5]:
            side_dot = "🟢" if o.get("side") == "B" else "🔴"
            lines.append(f"  {side_dot} {o.get('sz')} {o.get('coin')} @ `${o.get('limitPx')}`")

    # Vault (skip API call if no vault configured)
    vault = _hl_post({"type": "clearinghouseState", "user": VAULT_ADDR}) if VAULT_ADDR else {}
    vmarg = vault.get("marginSummary", {})
    vpos = vault.get("assetPositions", [])
    val = float(vmarg.get("accountValue", 0))
    if val > 0:
        lines.append(f"\n*Vault*")
        lines.append(f"  `${val:,.2f}`")
        for p in vpos:
            pos = p["position"]
            vupnl = float(pos.get('unrealizedPnl', 0))
            vpnl_sign = "+" if vupnl >= 0 else ""
            lines.append(f"  BTC `{pos['szi']}` @ `${pos['entryPx']}` • uPnL `{vpnl_sign}${vupnl:,.2f}`")

    renderer.send_text("\n".join(lines))


def cmd_price(renderer: Renderer, _args: str) -> None:
    ts = datetime.now(timezone.utc).strftime('%a %H:%M UTC')
    lines = [f"💲 *Prices* — {ts}", ""]

    # Fetch market context for 24h change (one call per clearinghouse)
    market_ctx = _get_all_market_ctx()

    for name, coin, aliases, cat in WATCHLIST:
        price = _get_current_price(coin)
        emoji = {"crypto": "₿", "commodity": "🛢️", "index": "📈", "equity": "🏢"}.get(cat, "📊")
        if not price:
            lines.append(f"{emoji} {name}: --")
            continue

        # Look up 24h change — try both with and without xyz: prefix
        bare = coin.replace("xyz:", "") if coin.startswith("xyz:") else coin
        ctx = market_ctx.get(coin, {}) or market_ctx.get(bare, {}) or market_ctx.get(f"xyz:{bare}", {})
        prev = ctx.get("prevDayPx", 0)

        if prev and prev > 0:
            change_pct = (price - prev) / prev * 100
            arrow = "📈" if change_pct >= 0 else "📉"
            sign = "+" if change_pct >= 0 else ""
            lines.append(f"{emoji} {name}: `${price:,.2f}`  {arrow} {sign}{change_pct:.1f}%")
        else:
            lines.append(f"{emoji} {name}: `${price:,.2f}`")

    renderer.send_text("\n".join(lines))


def _format_order_line(o: dict) -> str:
    """Format a single order into a readable line with type label."""
    coin = o.get("coin", "?")
    side = "BUY" if o.get("side") == "B" else "SELL"
    sz = o.get("sz", "0")
    order_type = o.get("orderType", "Limit")
    trigger_px = o.get("triggerPx")
    limit_px = o.get("limitPx", "?")
    tpsl = o.get("tpsl", "")

    # Determine type label and icon
    if tpsl == "sl" or order_type in ("Stop Market", "Stop Limit"):
        icon = "🛡"
        label = "SL"
        px = trigger_px or limit_px
    elif tpsl == "tp" or order_type in ("Take Profit Market", "Take Profit Limit"):
        icon = "🎯"
        label = "TP"
        px = trigger_px or limit_px
    elif o.get("isTrigger"):
        icon = "⏳"
        label = "Trigger"
        px = trigger_px or limit_px
    else:
        icon = "🟢" if side == "BUY" else "🔴"
        label = side
        px = limit_px

    # Size display: 0 means whole position
    if float(sz) == 0:
        sz_str = "whole position"
    else:
        sz_str = f"{float(sz):.1f}"

    return f"{icon} *{label}* {coin} — {sz_str} @ `${px}`"


def cmd_orders(renderer: Renderer, _args: str) -> None:
    orders = _get_all_orders(MAIN_ADDR)
    if not orders:
        renderer.send_text("📋 No open orders")
        return

    # Group by coin
    by_coin: dict = {}
    for o in orders:
        coin = o.get("coin", "?")
        by_coin.setdefault(coin, []).append(o)

    lines = [f"📋 *Open Orders* ({len(orders)})", ""]
    for coin, coin_orders in by_coin.items():
        lines.append(f"*{coin}*")
        for o in coin_orders:
            lines.append(f"  {_format_order_line(o)}")
        lines.append("")

    renderer.send_text("\n".join(lines))


def cmd_pnl(token: str, chat_id: str, _args: str) -> None:
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


def cmd_commands(token: str, chat_id: str, args: str) -> None:
    from cli.commands.commands import get_commands_text, CATEGORIES
    arg = args.strip().lower()
    is_long = arg in ("--long", "-l", "long", "all")
    category = arg if arg in CATEGORIES else None
    text = get_commands_text(long=is_long, category=category)
    # Telegram has 4096 char limit, split if needed
    if len(text) > 4000:
        parts = text.split("\n\n")
        chunk = ""
        for part in parts:
            if len(chunk) + len(part) > 3900:
                tg_send(token, chat_id, chunk)
                chunk = part
            else:
                chunk += "\n\n" + part if chunk else part
        if chunk:
            tg_send(token, chat_id, chunk)
    else:
        tg_send(token, chat_id, text)


def cmd_chart(token: str, chat_id: str, args: str) -> None:
    """Generate and send a price chart. Usage: /chart <market> [hours]"""
    parts = args.split() if args else []

    if not parts:
        lines = ["*Charts*", ""]
        for name, coin, aliases, cat in WATCHLIST:
            hint = aliases[0] if aliases else coin
            lines.append(f"  `/chart{hint}` — {name}")
        lines.append("\nAdd hours: `/chartoil 72`, `/chartbtc 168`")
        lines.append("Or /watchlist for all markets + prices")
        tg_send(token, chat_id, "\n".join(lines))
        return

    coin = resolve_coin(parts[0])
    if not coin:
        tg_send(token, chat_id, f"Unknown market: `{parts[0]}`\nTry `/chart` to see available markets.")
        return

    hours = 72
    if len(parts) > 1:
        try:
            hours = int(parts[1])
        except ValueError:
            pass

    display = next((w[0] for w in WATCHLIST if w[1] == coin), coin)
    try:
        from cli.chart_engine import ChartEngine
        engine = ChartEngine()
        path = engine.price_action(coin, hours=hours)
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        with open(path, "rb") as f:
            requests.post(url, data={"chat_id": chat_id, "caption": f"{display} — {hours}h"},
                         files={"photo": f}, timeout=30)
    except Exception as e:
        tg_send(token, chat_id, f"Chart error: {e}")


def cmd_watchlist(token: str, chat_id: str, _args: str) -> None:
    """Show the watchlist with current prices."""
    lines = ["📊 *Watchlist*", ""]
    cat_emojis = {"crypto": "₿", "commodity": "🛢️", "index": "📈", "equity": "🏢"}
    by_cat: dict[str, list] = {}
    for name, coin, aliases, cat in WATCHLIST:
        by_cat.setdefault(cat, []).append((name, coin, aliases))

    for cat, markets in by_cat.items():
        emoji = cat_emojis.get(cat, "📊")
        lines.append(f"{emoji} *{cat.title()}*")
        for name, coin, aliases in markets:
            price = _get_current_price(coin)
            px = f"`${price:,.2f}`" if price else "`--`"
            hint = aliases[0] if aliases else ""
            lines.append(f"  {name}: {px}  /chart{hint}")
        lines.append("")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_addmarket(token: str, chat_id: str, args: str) -> None:
    """Search HL for a market and add it to the watchlist. Usage: /addmarket <query>"""
    from common.watchlist import search_hl_markets, add_market, load_watchlist
    query = args.strip()
    if not query:
        tg_send(token, chat_id, "Usage: `/addmarket <query>`\nExample: `/addmarket crude` or `/addmarket sol`")
        return

    # Check if already in watchlist
    existing = {m["coin"] for m in load_watchlist()}

    results = search_hl_markets(query)
    if not results:
        tg_send(token, chat_id, f"No markets found matching `{query}`")
        return

    lines = [f"🔍 *Markets matching* `{query}`", ""]
    for r in results:
        status = " ✅ (already tracked)" if r["coin"] in existing else ""
        lines.append(f"  `{r['coin']}` — ${r['price']:,.2f} ({r['dex']}){status}")

    # Auto-add first non-existing match if only one clear result
    candidates = [r for r in results if r["coin"] not in existing]
    if candidates:
        lines.append("")
        lines.append("To add, reply: `/addmarket! <coin>`")
        lines.append(f"Example: `/addmarket! {candidates[0]['coin']}`")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_addmarket_confirm(token: str, chat_id: str, args: str) -> None:
    """Confirm adding a market. Usage: /addmarket! xyz:CL"""
    from common.watchlist import add_market
    coin = args.strip()
    if not coin:
        tg_send(token, chat_id, "Usage: `/addmarket! <coin>`\nExample: `/addmarket! xyz:CL`")
        return

    # Determine display name and category
    bare = coin.replace("xyz:", "")
    display = bare
    category = "crypto"
    if coin.startswith("xyz:"):
        category = "commodity"
    aliases = [bare.lower()]

    if add_market(display, coin, aliases, category):
        # Reload module-level vars
        global WATCHLIST, COIN_ALIASES, APPROVED_MARKETS
        WATCHLIST = _get_wl_tuples()
        COIN_ALIASES = _get_aliases()
        APPROVED_MARKETS = _get_coins()
        tg_send(token, chat_id, f"✅ Added `{coin}` to watchlist.\nUse `/watchlist` to see all tracked markets.")
    else:
        tg_send(token, chat_id, f"`{coin}` is already in the watchlist.")


def cmd_removemarket(token: str, chat_id: str, args: str) -> None:
    """Remove a market from the watchlist. Usage: /removemarket <coin>"""
    from common.watchlist import remove_market, load_watchlist
    coin = args.strip()
    if not coin:
        # Show current watchlist for selection
        wl = load_watchlist()
        lines = ["📋 *Current watchlist* — which to remove?", ""]
        for m in wl:
            lines.append(f"  `{m['coin']}` — {m['display']}")
        lines.append("")
        lines.append("Reply: `/removemarket <coin>`")
        tg_send(token, chat_id, "\n".join(lines))
        return

    if remove_market(coin):
        global WATCHLIST, COIN_ALIASES, APPROVED_MARKETS
        WATCHLIST = _get_wl_tuples()
        COIN_ALIASES = _get_aliases()
        APPROVED_MARKETS = _get_coins()
        tg_send(token, chat_id, f"✅ Removed `{coin}` from watchlist.")
    else:
        tg_send(token, chat_id, f"`{coin}` not found in watchlist. Use `/watchlist` to see current markets.")


def cmd_powerlaw(token: str, chat_id: str, _args: str) -> None:
    """Generate and send the BTC Power Law chart."""
    try:
        from plugins.power_law.charting import generate_powerlaw_png
        import io
        png_bytes = generate_powerlaw_png()
        requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": "₿ *BTC Power Law* — Floor / Ceiling / Fair Value"},
            files={"photo": ("powerlaw.png", io.BytesIO(png_bytes), "image/png")},
            timeout=30)
    except Exception as e:
        tg_send(token, chat_id, f"Power Law error: {e}")


def cmd_delegate(token: str, chat_id: str, args: str) -> None:
    """Delegate an asset to the agent. Usage: /delegate BRENTOIL"""
    from common.authority import delegate, format_authority_status
    asset = args.strip().upper()
    if not asset:
        # Show current positions so user can pick
        positions = _get_all_positions(MAIN_ADDR)
        pos_data = []
        for p in positions:
            pos_data.append({
                "coin": p.get("coin", "?"),
                "side": "long" if float(p.get("szi", 0)) > 0 else "short",
                "size": abs(float(p.get("szi", 0))),
                "entry_price": float(p.get("entryPx", 0)),
            })
        status = format_authority_status(pos_data)
        tg_send(token, chat_id, status + "\n\nUsage: `/delegate BRENTOIL`")
        return
    result = delegate(asset)
    tg_send(token, chat_id,
            f"🤖 *Delegated*\n{result}\n\n"
            f"Agent now manages `{asset}` — entries, exits, sizing.\n"
            f"Use `/reclaim {asset}` to take back control.")


def cmd_reclaim(token: str, chat_id: str, args: str) -> None:
    """Reclaim an asset from the agent. Usage: /reclaim BRENTOIL"""
    from common.authority import reclaim
    asset = args.strip().upper()
    if not asset:
        tg_send(token, chat_id, "Usage: `/reclaim BRENTOIL`\nTakes the asset back from agent control.")
        return
    result = reclaim(asset)
    tg_send(token, chat_id,
            f"👤 *Reclaimed*\n{result}\n\n"
            f"You control `{asset}` now. Bot is safety-net only (SL/TP checks).")


def cmd_authority(token: str, chat_id: str, _args: str) -> None:
    """Show authority status for all assets."""
    from common.authority import format_authority_status
    positions = _get_all_positions(MAIN_ADDR)
    pos_data = []
    for p in positions:
        pos_data.append({
            "coin": p.get("coin", "?"),
            "side": "long" if float(p.get("szi", 0)) > 0 else "short",
            "size": abs(float(p.get("szi", 0))),
            "entry_price": float(p.get("entryPx", 0)),
        })
    status = format_authority_status(pos_data)
    tg_send(token, chat_id, status)


def cmd_todo(token: str, chat_id: str, args: str) -> None:
    """Add or list todos. Usage: /todo <description> or /todo (to list)"""
    todos_path = Path("data/todos.jsonl")
    todos_path.parent.mkdir(parents=True, exist_ok=True)

    if not args.strip():
        # List open todos
        if not todos_path.exists():
            tg_send(token, chat_id, "No todos. Use `/todo fix the chart labels`")
            return
        items = []
        for line in todos_path.read_text().splitlines():
            if line.strip():
                try:
                    item = json.loads(line)
                    if item.get("status") == "open":
                        items.append(item)
                except json.JSONDecodeError:
                    pass
        if not items:
            tg_send(token, chat_id, "No open todos.")
            return
        lines = ["*Open Todos*\n"]
        for i, item in enumerate(items[-15:], 1):
            ts = item.get("timestamp", "")[:10]
            lines.append(f"`{i}.` {item.get('text', '?')} ({ts})")
        tg_send(token, chat_id, "\n".join(lines))
        return

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "telegram",
        "text": args.strip()[:200],
        "status": "open",
    }
    with open(todos_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    tg_send(token, chat_id, f"Todo added.\n`{args.strip()[:100]}`")


def cmd_help(token: str, chat_id: str, _args: str) -> None:
    tg_send(token, chat_id,
        "*HyperLiquid Bot*\n"
        "\n*Trading*\n"
        "  /status — portfolio overview\n"
        "  /position — positions + risk + authority\n"
        "  /market oil — technicals, funding, OI\n"
        "  /pnl — profit & loss breakdown\n"
        "  /price — quick prices + 24h change\n"
        "  /orders — open orders\n"
        "\n*Charts*\n"
        "  /chartoil 72 — oil chart (hours)\n"
        "  /chartbtc 168 — BTC chart\n"
        "  /chartgold — gold chart\n"
        "  /watchlist — all markets + prices\n"
        "  /powerlaw — BTC power law model\n"
        "\n*Agent Control*\n"
        "  /authority — who manages what\n"
        "  /delegate ASSET — hand to agent\n"
        "  /reclaim ASSET — take back\n"
        "\n*Vault*\n"
        "  /rebalancer — status / start / stop\n"
        "  /rebalance — force rebalance now\n"
        "\n*System*\n"
        "  /models — AI model selection\n"
        "  /memory — memory system status\n"
        "  /health — app health check\n"
        "  /diag — error diagnostics\n"
        "  /bug text — report a bug\n"
        "  /todo text — add a todo\n"
        "  /feedback text — submit feedback\n"
        "  /guide — how to use this bot\n"
        "\n*AI Chat*\n"
        "  Type anything — AI responds with live data")


# ── Vault rebalancer daemon control ─────────────────────────────────────

_LAUNCHD_LABEL = "com.hl-bot.vault-rebalancer"


def _rebalancer_is_running() -> bool:
    try:
        result = subprocess.run(
            ["launchctl", "list", _LAUNCHD_LABEL],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def cmd_rebalancer(token: str, chat_id: str, args: str) -> None:
    action = args.strip().lower()

    if action == "start":
        if _rebalancer_is_running():
            tg_send(token, chat_id, "🟢 Rebalancer already running.")
            return
        try:
            subprocess.run(
                ["launchctl", "load", "-w",
                 str(Path.home() / "Library/LaunchAgents" / f"{_LAUNCHD_LABEL}.plist")],
                check=True, timeout=10,
            )
            tg_send(token, chat_id, "🟢 Vault rebalancer *started*.")
        except Exception as e:
            tg_send(token, chat_id, f"Start failed: `{e}`")

    elif action == "stop":
        try:
            subprocess.run(
                ["launchctl", "unload", "-w",
                 str(Path.home() / "Library/LaunchAgents" / f"{_LAUNCHD_LABEL}.plist")],
                check=True, timeout=10,
            )
            tg_send(token, chat_id, "🔴 Vault rebalancer *stopped*.")
        except Exception as e:
            tg_send(token, chat_id, f"Stop failed: `{e}`")

    else:
        running = _rebalancer_is_running()
        status_icon = "🟢" if running else "🔴"
        status_text = "RUNNING" if running else "STOPPED"
        pid_file = Path("data/vault_rebalancer.pid")
        pid = pid_file.read_text().strip() if pid_file.exists() else "—"
        tg_send(token, chat_id,
                f"*Vault Rebalancer* {status_icon} {status_text}\n\n"
                f"  PID: `{pid}`\n"
                f"  Vault: `{VAULT_ADDR[:10]}...`\n"
                f"  Tick: `1h` | Max leverage: `1x`\n\n"
                f"`/rebalancer start` or `/rebalancer stop`")


def cmd_rebalance(token: str, chat_id: str, _args: str) -> None:
    """Force an immediate BTC rebalance in the vault, ignoring the threshold."""
    tg_send(token, chat_id, "Running immediate vault rebalance...")
    try:
        import sys as _sys
        _sys.path.insert(0, PROJECT_ROOT)
        import os as _os
        _os.environ["POWER_LAW_SIMULATE"] = "false"
        _os.environ["HL_TESTNET"] = "false"

        from common.credentials import resolve_private_key
        from parent.hl_proxy import HLProxy
        from cli.hl_adapter import DirectHLProxy
        from plugins.power_law.bot import PowerLawBot
        from plugins.power_law.config import PowerLawConfig

        key = resolve_private_key(venue="hl")
        hl = HLProxy(private_key=key, testnet=False, vault_address=VAULT_ADDR)
        proxy = DirectHLProxy(hl)
        # threshold=0 forces rebalance regardless of current deviation
        cfg = PowerLawConfig(max_leverage=1, threshold_percent=0, simulate=False)
        bot = PowerLawBot(proxy=proxy, config=cfg)
        result = bot.check_and_rebalance()

        if result.get("traded"):
            tg_send(token, chat_id,
                    f"*Rebalanced*\n\n"
                    f"  {result['direction']} `${result.get('amount_usd', 0):.2f}` "
                    f"@ `${result.get('fill_price', 0):,.0f}`\n"
                    f"  Target: `{result.get('target_btc_pct', 0):.1f}%` BTC")
        else:
            tg_send(token, chat_id,
                    f"*No Rebalance Needed*\n\n"
                    f"  {result.get('reason', 'already at target')}\n"
                    f"  Current: `{result.get('current_btc_pct', 0):.1f}%` | "
                    f"Target: `{result.get('target_btc_pct', 0):.1f}%`")
    except Exception as e:
        tg_send(token, chat_id, f"Rebalance error: {e}")


def cmd_market(token: str, chat_id: str, args: str) -> None:
    """Market update with technicals. Usage: /market <symbol>"""
    raw_parts = args.split() if args else []
    if not raw_parts:
        lines = ["*Market*", ""]
        for name, coin, aliases, cat in WATCHLIST:
            hint = aliases[0] if aliases else coin.lower()
            lines.append(f"  `/market {hint}` — {name}")
        tg_send(token, chat_id, "\n".join(lines))
        return

    coin = resolve_coin(raw_parts[0])
    if not coin:
        tg_send(token, chat_id, f"Unknown: `{raw_parts[0]}`\nTry `/market` for options.")
        return

    display = next((w[0] for w in WATCHLIST if w[1] == coin), coin)
    price = _get_current_price(coin)

    lines = [f"*{display}*", ""]
    if price:
        lines.append(f"  Price: `${price:,.2f}`")
    else:
        lines.append("  Price: unavailable")

    # Technicals — full signal engine
    try:
        from common.market_snapshot import build_snapshot, render_signal_summary
        from modules.candle_cache import CandleCache
        cache = CandleCache()

        # Refresh candles for all timeframes BEFORE building snapshot
        _refresh_candle_cache_for_market(cache, coin)

        snap = build_snapshot(coin, cache, price or 0)

        # Key levels
        if snap.key_levels:
            supports = [kl for kl in snap.key_levels if kl.type == "support"]
            resists = [kl for kl in snap.key_levels if kl.type == "resistance"]
            if supports:
                s_prices = ", ".join(f"`${kl.price:,.2f}` ({kl.distance_pct:+.1f}%)" for kl in supports[:3])
                lines.append(f"  Support: {s_prices}")
            if resists:
                r_prices = ", ".join(f"`${kl.price:,.2f}` ({kl.distance_pct:+.1f}%)" for kl in resists[:3])
                lines.append(f"  Resist: {r_prices}")

        # Timeframe trends (compact)
        lines.append("")
        for interval in ["1d", "4h", "1h"]:
            tf = snap.timeframes.get(interval)
            if not tf:
                continue
            t = tf.trend
            trend_icon = "↑" if t.direction == "bullish" else ("↓" if t.direction == "bearish" else "→")
            bb_note = ""
            if tf.bb:
                if tf.bb.is_squeeze:
                    bb_note = " *SQUEEZE*"
                elif tf.bb.zone != "mid":
                    bb_note = f" BB:{tf.bb.zone}"
            lines.append(
                f"  `{interval}` {trend_icon} {t.direction} | "
                f"RSI `{t.rsi:.0f}` | ATR `{tf.atr_pct:.1f}%`{bb_note} | "
                f"`{tf.price_change_pct:+.1f}%`"
            )

        # Full signal summary — exhaustion, divergence, multi-TF, volume, position guidance
        # Get position data for position-specific signals
        pos_data = None
        for p in _get_all_positions(MAIN_ADDR):
            if _coin_matches(p.get("coin", ""), coin):
                sz = float(p.get("szi", 0))
                if sz != 0:
                    pos_data = {"direction": "long" if sz > 0 else "short", "size": abs(sz)}
                break

        signal_text = render_signal_summary(snap, position=pos_data)
        if signal_text:
            lines.append("")
            lines.append("---")
            # Reformat signal for Telegram readability
            for sig_line in signal_text.strip().split("\n"):
                sig_line = sig_line.strip()
                if not sig_line:
                    continue
                # Header line: "SIGNAL: 🟢 BULLISH (score: +1)" → bold header
                if sig_line.startswith("SIGNAL:"):
                    lines.append(f"*{sig_line}*")
                # Outlook line: "→ PRICE OUTLOOK:" → bold, standalone
                elif sig_line.startswith("→ PRICE OUTLOOK:"):
                    outlook = sig_line.replace("→ PRICE OUTLOOK:", "").strip()
                    lines.append(f"\n📍 *Outlook:* {outlook}")
                # Position guidance: "→ SHORTS/LONGS" → actionable
                elif sig_line.startswith("→ SHORTS") or sig_line.startswith("→ LONGS"):
                    lines.append(f"  {sig_line}")
                # Position impact: "✅/⚠️/➡️ YOUR LONG/SHORT" → bold
                elif "YOUR LONG" in sig_line or "YOUR SHORT" in sig_line:
                    lines.append(f"\n{sig_line}")
                # Bullet points
                elif sig_line.startswith("•"):
                    lines.append(f"  {sig_line}")
                else:
                    lines.append(f"  {sig_line}")
    except Exception as e:
        log.debug("Snapshot unavailable for %s: %s", coin, e)

    # Funding + OI + Volume
    try:
        dex = "xyz" if coin.startswith("xyz:") else None
        payload = {"type": "metaAndAssetCtxs"}
        if dex:
            payload["dex"] = dex
        meta = _hl_post(payload)
        if isinstance(meta, list) and len(meta) >= 2:
            asset_ctxs = meta[1]
            universe = meta[0].get("universe", [])
            for i, u in enumerate(universe):
                if _coin_matches(u.get("name", ""), coin):
                    if i < len(asset_ctxs):
                        fr = float(asset_ctxs[i].get("funding", 0))
                        oi_raw = float(asset_ctxs[i].get("openInterest", 0))
                        vol_raw = float(asset_ctxs[i].get("dayNtlVlm", 0))
                        ann_pct = fr * 8760 * 100

                        lines.append("")
                        lines.append(f"  Funding: `{fr*100:.4f}%/h` (`{ann_pct:+.1f}%` ann)")
                        oi_vol = []
                        if oi_raw > 0:
                            oi_vol.append(f"OI `${oi_raw/1e6:.1f}M`" if oi_raw >= 1e6 else f"OI `${oi_raw:,.0f}`")
                        if vol_raw > 0:
                            oi_vol.append(f"Vol `${vol_raw/1e6:.1f}M`" if vol_raw >= 1e6 else f"Vol `${vol_raw:,.0f}`")
                        if oi_vol:
                            lines.append(f"  {' | '.join(oi_vol)}")
                    break
    except Exception:
        pass

    lines.append(f"\n  Liquidity: {_liquidity_regime()}")
    tg_send(token, chat_id, "\n".join(lines))


def cmd_position(token: str, chat_id: str, _args: str) -> None:
    """Detailed position report with risk metrics."""
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


def cmd_bug(token: str, chat_id: str, args: str) -> None:
    """Report a bug. Usage: /bug <description>"""
    if not args.strip():
        tg_send(token, chat_id, "*Bug Report*\n\nUsage: `/bug SL not being set on BRENTOIL entries`")
        return

    bugs_path = Path("data/bugs.md")
    bugs_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## [MEDIUM] {args.strip()[:100]}\n- **Reported:** {now}\n- **Source:** Telegram\n- **Status:** open\n- **Description:** {args.strip()}\n"

    if not bugs_path.exists():
        bugs_path.write_text("# Bugs & Issues\n\nTracked bugs for Claude Code to investigate and fix.\n" + entry)
    else:
        with open(bugs_path, "a") as f:
            f.write(entry)

    tg_send(token, chat_id, f"*Bug Logged*\n\n`{args.strip()[:100]}`\n\nClaude Code will pick this up next session.")
    log.info("Bug reported via Telegram: %s", args.strip()[:80])


def cmd_feedback(token: str, chat_id: str, args: str) -> None:
    """Submit feedback. Usage: /feedback <text>"""
    if not args.strip():
        tg_send(token, chat_id, "*Feedback*\n\nUsage: `/feedback market updates need more detail on technicals`")
        return

    feedback_path = Path("data/feedback.jsonl")
    feedback_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "telegram",
        "text": args.strip()[:1000],
    }
    with open(feedback_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    tg_send(token, chat_id, f"*Feedback Recorded*\n\n`{args.strip()[:100]}`")
    log.info("Feedback via Telegram: %s", args.strip()[:80])


def cmd_guide(token: str, chat_id: str, _args: str) -> None:
    """Onboarding guide — how to use the bot."""
    tg_send(token, chat_id,
        "*How This System Works*\n"
        "\nThis is a portfolio copilot, risk manager, and research agent. "
        "You bring the thesis, it executes with discipline.\n"
        "\n📊 *Quick Data*\n"
        "`/status` — portfolio overview + PnL\n"
        "`/position` — detailed risk per position\n"
        "`/market oil` — deep technicals on a market\n"
        "`/watchlist` — all tracked markets + prices\n"
        "`/price btc` — quick price check\n"
        "\n📈 *Charts*\n"
        "`/chartoil 72` — 72h oil chart\n"
        "Shortcuts: `/chartbtc`, `/chartgold`, `/chartwti`\n"
        "\n💬 *AI Chat*\n"
        "Type anything that's not a `/command` and the AI responds. "
        "It sees your live positions, prices, thesis, and memory — refreshed every message. "
        "Ask things like \"what's oil doing?\", \"should I add here?\", or \"challenge my thesis\".\n"
        "\nIf the AI suggests a trade, you get Approve/Reject buttons. "
        "No trade executes without your tap.\n"
        "\n🤖 *Agent Delegation*\n"
        "`/authority` — see who manages what\n"
        "`/delegate BRENTOIL` — agent controls entries, exits, sizing\n"
        "`/reclaim BRENTOIL` — take it back to manual\n"
        "\n🤖 Agent = bot makes all decisions (you approve trades)\n"
        "👤 Manual = you trade, bot ensures SL/TP exist\n"
        "\n🔧 *System*\n"
        "`/models` — switch AI model (10 free, 8 paid)\n"
        "`/health` — check what's running (bot, heartbeat, daemon)\n"
        "`/diag` — tool calls, errors, authority status\n"
        "`/memory` — agent learnings and notes\n"
        "\n🛢️ *Watchlist Management*\n"
        "`/addmarket crude` — search and add a new market\n"
        "`/removemarket xyz:CL` — remove a market\n"
        "\n📝 *Tracking*\n"
        "`/bug`, `/todo`, `/feedback` — all picked up by Claude Code next session.\n"
        "\n*Background*: Heartbeat checks every 2 min (stops, alerts, escalation). "
        "Thesis files drive conviction sizing. Claude Code (Opus) writes thesis, this bot reads and discusses.\n"
        "\n`/help` for full command list")


def cmd_health(renderer: Renderer, _args: str) -> None:
    """App health check — shows what's running and what isn't."""
    from common.authority import get_all as get_all_authority

    lines = ["*App Health*", "", "*Services*"]

    # 1. Telegram bot — always running
    uptime_str = "unknown"
    if _diag:
        summary = _diag.get_summary()
        uptime_s = summary['uptime_seconds']
        if uptime_s >= 3600:
            uptime_str = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60:02d}m"
        elif uptime_s >= 60:
            uptime_str = f"{uptime_s // 60}m"
        else:
            uptime_str = f"{uptime_s}s"
    lines.append(f"  🟢 Telegram bot — running (`{uptime_str}`)")

    # 2. Heartbeat
    ws_path = Path("data/memory/working_state.json")
    if ws_path.exists():
        try:
            ws = json.loads(ws_path.read_text())
            esc = ws.get("escalation_level", "?")
            fails = ws.get("heartbeat_consecutive_failures", 0)
            hb_icon = "🟢" if fails == 0 else "🔴"
            lines.append(f"  {hb_icon} Heartbeat — `{esc}` ({fails} failures)")
        except Exception:
            lines.append("  ⚪ Heartbeat — unknown")
    else:
        lines.append("  ⚪ Heartbeat — no state file")

    # 3. Daemon
    daemon_pid_path = Path("data/daemon/daemon.pid")
    daemon_running = False
    if daemon_pid_path.exists():
        try:
            pid = int(daemon_pid_path.read_text().strip())
            os.kill(pid, 0)
            daemon_running = True
        except (ValueError, OSError):
            pass

    if daemon_running:
        daemon_state_path = Path("data/daemon/state.json")
        tier_str = ""
        if daemon_state_path.exists():
            try:
                ds = json.loads(daemon_state_path.read_text())
                tier = ds.get("tier", "?")
                tier_str = f" tier `{tier}`"
            except Exception:
                pass
        lines.append(f"  🟢 Daemon — running{tier_str}")
    else:
        lines.append("  🔴 Daemon — stopped")

    # 4. Vault rebalancer
    rebal_pid_path = Path("data/vault_rebalancer.pid")
    rebal_running = False
    if rebal_pid_path.exists():
        try:
            pid = int(rebal_pid_path.read_text().strip())
            os.kill(pid, 0)
            rebal_running = True
        except (ValueError, OSError):
            pass
    lines.append(f"  {'🟢' if rebal_running else '🔴'} Rebalancer — {'running' if rebal_running else 'stopped'}")

    # Data section
    lines.append("")
    lines.append("*Data*")

    # 5. Thesis files
    thesis_dir = Path("data/thesis")
    if thesis_dir.exists():
        thesis_files = list(thesis_dir.glob("*_state.json"))
        active_parts = []
        for tf in thesis_files:
            try:
                td = json.loads(tf.read_text())
                conv = float(td.get("conviction", 0))
                if conv > 0:
                    market = td.get("market", tf.stem.replace("_state", ""))
                    active_parts.append(f"{market} `{conv:.2f}`")
            except Exception:
                pass
        if active_parts:
            lines.append(f"  Thesis: `{len(active_parts)}` active ({', '.join(active_parts)})")
        elif thesis_files:
            lines.append(f"  Thesis: `{len(thesis_files)}` files (none active)")
        else:
            lines.append("  Thesis: none")
    else:
        lines.append("  Thesis: none")

    # 6. Chat history
    history_path = Path("data/daemon/chat_history.jsonl")
    if history_path.exists():
        line_count = sum(1 for _ in history_path.open())
        size_kb = history_path.stat().st_size / 1024
        lines.append(f"  Chat: `{line_count}` messages (`{size_kb:.0f}KB`)")
    else:
        lines.append("  Chat: no history")

    # 7. Authority
    auth_assets = get_all_authority()
    delegated = [a for a, e in auth_assets.items() if e.get("authority") == "agent"]
    if delegated:
        lines.append(f"  Authority: {', '.join(f'`{a}`' for a in delegated)} delegated")
    else:
        lines.append("  Authority: all manual")

    # 8. Health metrics (HealthWindow + pending actions)
    lines.append("")
    lines.append("*Health Metrics*")

    tel_path = Path("state/telemetry.json")
    hw_shown = False
    if tel_path.exists():
        try:
            tel = json.loads(tel_path.read_text())
            hw = tel.get("health_window")
            if hw:
                window_min = hw.get("window_s", 900) // 60
                placed = hw.get("orders_placed", 0)
                cancelled = hw.get("orders_cancelled", 0)
                fills = hw.get("fills", 0)
                errors = hw.get("errors", 0)
                budget = hw.get("error_budget", 10)
                rss_mb = hw.get("rss_mb", 0)
                exhausted = hw.get("budget_exhausted", False)
                err_icon = "🔴" if exhausted else ("🟡" if errors > 0 else "🟢")
                lines.append(
                    f"  Orders ({window_min}min): placed `{placed}` · cancelled `{cancelled}` · filled `{fills}`"
                )
                lines.append(f"  {err_icon} Errors: `{errors}/{budget}` budget")
                lines.append(f"  RSS memory: `{rss_mb:.1f} MB`")
                hw_shown = True
        except Exception:
            pass

    if not hw_shown:
        lines.append("  No telemetry data (daemon not running?)")

    try:
        from cli.agent_tools import pending_count
        pc = pending_count()
        lines.append(f"  Pending actions: `{pc}`")
    except Exception:
        pass

    lines.append("")
    lines.append("`/diag` for error details")
    renderer.send_text("\n".join(lines))


def cmd_memory(token: str, chat_id: str, _args: str) -> None:
    """Memory system status and effectiveness check."""
    import sqlite3
    ts = datetime.now(timezone.utc).strftime('%a %H:%M UTC')
    lines = [f"🧠 *Memory System* — {ts}", ""]

    # 1. Memory DB (events + learnings)
    db_path = Path("data/memory/memory.db")
    if db_path.exists():
        size_kb = db_path.stat().st_size / 1024
        try:
            con = sqlite3.connect(str(db_path))
            con.row_factory = sqlite3.Row
            event_count = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            learning_count = con.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]

            cutoff_ms = int((time.time() - 86400) * 1000)
            recent_events = con.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp_ms >= ?", (cutoff_ms,)
            ).fetchone()[0]
            recent_learnings = con.execute(
                "SELECT COUNT(*) FROM learnings WHERE timestamp_ms >= ?", (cutoff_ms,)
            ).fetchone()[0]

            latest = con.execute(
                "SELECT title, timestamp_ms FROM events ORDER BY timestamp_ms DESC LIMIT 1"
            ).fetchone()
            con.close()

            lines.append("📦 *Event Store*")
            lines.append(f"  Events: {event_count} ({recent_events} last 24h)")
            lines.append(f"  Learnings: {learning_count} ({recent_learnings} last 24h)")
            lines.append(f"  Size: {size_kb:.0f}KB")
            if latest:
                age_h = (time.time() * 1000 - latest["timestamp_ms"]) / 3_600_000
                lines.append(f"  Latest: {age_h:.0f}h ago")
            if recent_events == 0 and event_count > 0:
                lines.append("  ⚠️ No events in 24h")
        except Exception as e:
            lines.append(f"📦 Event Store: error — {e}")
    else:
        lines.append("📦 Event Store: not found")

    # 2. Working state (heartbeat memory)
    lines.append("")
    ws_path = Path("data/memory/working_state.json")
    if ws_path.exists():
        try:
            ws = json.loads(ws_path.read_text())
            updated_ms = ws.get("last_updated_ms", 0)
            age_min = (time.time() * 1000 - updated_ms) / 60_000 if updated_ms else 0
            esc = ws.get("escalation_level", "?")
            atr_keys = list(ws.get("atr_cache", {}).keys())
            peak = ws.get("session_peak_equity", 0)

            icon = "🟢" if age_min < 5 else "🔴"
            lines.append(f"{icon} *Heartbeat*")
            lines.append(f"  Updated: {age_min:.0f}m ago")
            lines.append(f"  Escalation: {esc}")
            lines.append(f"  Peak equity: ${peak:,.0f}")
            if atr_keys:
                lines.append(f"  ATR: {', '.join(atr_keys)}")
            if age_min >= 5:
                lines.append("  ⚠️ Stale — heartbeat may not be running")
        except Exception as e:
            lines.append(f"🔴 Heartbeat: error — {e}")
    else:
        lines.append("🔴 Heartbeat: no state file")

    # 3. Thesis states
    lines.append("")
    thesis_dir = Path("data/thesis")
    if thesis_dir.exists():
        thesis_files = list(thesis_dir.glob("*_state.json"))
        if thesis_files:
            lines.append(f"📜 *Thesis* ({len(thesis_files)})")
            for tf in sorted(thesis_files):
                try:
                    td = json.loads(tf.read_text())
                    market = td.get("market", tf.stem.replace("_state", ""))
                    conv = float(td.get("conviction", 0))
                    direction = td.get("direction", "?")
                    updated = td.get("updated_at", td.get("created_at", ""))
                    age_str = ""
                    if updated:
                        from datetime import datetime as _dt
                        try:
                            updated_dt = _dt.fromisoformat(updated.replace("Z", "+00:00"))
                            age_h = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
                            age_str = f" ({age_h:.0f}h)"
                            if age_h > 48:
                                age_str += " ⚠️"
                        except Exception:
                            pass
                    dot = "🟢" if conv > 0.5 else ("🟡" if conv > 0 else "⬛")
                    lines.append(f"  {dot} {market} {direction} {conv:.2f}{age_str}")
                except Exception:
                    lines.append(f"  ⚠️ {tf.name} — unreadable")
        else:
            lines.append("📜 *Thesis*: none")
    else:
        lines.append("📜 *Thesis*: none")

    # 4. Chat history
    lines.append("")
    history_path = Path("data/daemon/chat_history.jsonl")
    if history_path.exists():
        try:
            text = history_path.read_text()
            msg_lines = [l for l in text.splitlines() if l.strip()]
            msg_count = len(msg_lines)
            size_kb = history_path.stat().st_size / 1024
            user_msgs = 0
            ai_msgs = 0
            for line in msg_lines:
                try:
                    entry = json.loads(line)
                    if entry.get("role") == "user":
                        user_msgs += 1
                    elif entry.get("role") == "assistant":
                        ai_msgs += 1
                except Exception:
                    pass
            lines.append(f"💬 *Chat History*")
            lines.append(f"  {msg_count} messages ({size_kb:.0f}KB)")
            lines.append(f"  You: {user_msgs} | AI: {ai_msgs}")
            if ai_msgs == 0 and user_msgs > 5:
                lines.append("  ⚠️ AI not responding — check OpenRouter key")
        except Exception:
            lines.append("💬 Chat History: error reading")
    else:
        lines.append("💬 Chat History: empty")

    # 5. Context harness check
    lines.append("")
    try:
        from common.context_harness import build_multi_market_context
        result = build_multi_market_context(
            markets=["BTC"], account_state={"account": {"total_equity": 0}, "alerts": [], "escalation": "L0"},
            market_snapshots={}, token_budget=500,
        )
        blocks = len(result.blocks_included)
        tokens = result.estimated_tokens
        lines.append(f"🟢 *Context Harness*: {blocks} blocks, {tokens}t")
    except Exception as e:
        lines.append(f"🔴 *Context Harness*: {str(e)[:60]}")

    # 6. Data files summary
    lines.append("")
    data_files = [
        ("Bugs", Path("data/bugs.md")),
        ("Todos", Path("data/todos.jsonl")),
        ("Feedback", Path("data/feedback.jsonl")),
    ]
    tracking = []
    for label, path in data_files:
        if path.exists():
            try:
                if path.suffix == ".jsonl":
                    count = sum(1 for line in path.read_text().splitlines() if line.strip())
                else:
                    count = path.read_text().count("## [")
                if count > 0:
                    tracking.append(f"{label}: {count}")
            except Exception:
                pass
    if tracking:
        lines.append(f"📋 *Tracking*: {' | '.join(tracking)}")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_models(token: str, chat_id: str, args: str) -> None:
    """Show AI model selector with compact inline keyboard grid."""
    from cli.telegram_agent import get_available_models, _get_active_model

    models = get_available_models()
    current = _get_active_model()
    current_name = next((m["name"] for m in models if m["id"] == current), current)

    free = [m for m in models if m.get("tier") == "free"]
    anthropic = [m for m in models if m.get("tier") == "anthropic"]
    paid = [m for m in models if m.get("tier") == "paid"]

    def _make_grid(model_list: list, cols: int = 2) -> list:
        """Build inline keyboard rows with `cols` buttons per row."""
        rows = []
        row = []
        for m in model_list:
            check = "✅ " if m["id"] == current else ""
            row.append({"text": f"{check}{m['name']}", "callback_data": f"model:{m['id']}"})
            if len(row) >= cols:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return rows

    # Build all sections into one message with one keyboard
    keyboard = []

    # Section header row for Anthropic (free via token)
    if anthropic:
        keyboard.append([{"text": "── Anthropic (free) ──", "callback_data": "noop"}])
        keyboard.extend(_make_grid(anthropic, cols=3))

    # Section header row for Free
    keyboard.append([{"text": "── Free (OpenRouter) ──", "callback_data": "noop"}])
    keyboard.extend(_make_grid(free, cols=2))

    # Section header row for Paid
    if paid:
        keyboard.append([{"text": "── Paid (credits) ──", "callback_data": "noop"}])
        keyboard.extend(_make_grid(paid, cols=2))

    try:
        payload = {
            "chat_id": chat_id,
            "text": f"🤖 *AI Models*\n\nActive: *{current_name}*",
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": keyboard},
        }
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=10,
        )
    except Exception as e:
        log.warning("Models command failed: %s", e)


def _handle_model_callback(token: str, chat_id: str, callback_id: str, model_id: str) -> None:
    """Handle inline keyboard button press for model selection."""
    from cli.telegram_agent import get_available_models, set_active_model

    valid_ids = [m["id"] for m in get_available_models()]
    if model_id not in valid_ids:
        tg_answer_callback(token, callback_id, "Unknown model")
        return

    set_active_model(model_id)
    name = next((m["name"] for m in get_available_models() if m["id"] == model_id), model_id)
    tg_answer_callback(token, callback_id, f"Switched to {name}")
    tg_send(token, chat_id, f"🤖 Model switched to *{name}*")


def _handle_tool_approval(token: str, chat_id: str, callback_id: str,
                           action_id: str, approved: bool, message_id: int = None) -> None:
    """Handle approve/reject of a pending write tool action."""
    from cli.agent_tools import pop_pending, execute_tool

    if message_id is not None:
        tg_remove_buttons(token, chat_id, message_id)

    action = pop_pending(action_id)
    if action is None:
        tg_answer_callback(token, callback_id, "Expired or not found")
        tg_send(token, chat_id, "Action expired or already handled.")
        return

    if not approved:
        tg_answer_callback(token, callback_id, "Rejected")
        tg_send(token, chat_id, f"❌ Action rejected.")
        return

    tg_answer_callback(token, callback_id, "Executing...")
    try:
        result = execute_tool(action["tool"], action["arguments"])
        tg_send(token, chat_id, f"✅ *{action['tool']}*\n\n{result}")
    except Exception as e:
        tg_send(token, chat_id, f"❌ *{action['tool']} failed*\n\n{e}")


def cmd_diag(token: str, chat_id: str, _args: str) -> None:
    """Show diagnostic summary with system state."""
    from common.authority import get_all as get_all_authority

    lines = ["*Diagnostics*", ""]

    # Bot uptime
    if _diag:
        summary = _diag.get_summary()
        uptime_s = summary['uptime_seconds']
        if uptime_s >= 3600:
            uptime_str = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m"
        elif uptime_s >= 60:
            uptime_str = f"{uptime_s // 60}m"
        else:
            uptime_str = f"{uptime_s}s"
        lines.append(f"  Bot uptime: `{uptime_str}`")
        # Tool call counts
        total_tools = summary.get('total_tool_calls', 0)
        tool_counts = summary.get('tool_calls', {})
        lines.append(f"  Tool calls: `{total_tools}`")
        if tool_counts:
            top3 = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            top_str = ", ".join(f"{n}({c})" for n, c in top3)
            lines.append(f"  Top tools: `{top_str}`")
        if summary['total_errors'] > 0:
            lines.append(f"  Errors: `{summary['total_errors']}`")

    # Heartbeat state
    ws_path = Path("data/memory/working_state.json")
    if ws_path.exists():
        try:
            ws = json.loads(ws_path.read_text())
            esc = ws.get("escalation_level", "?")
            fails = ws.get("heartbeat_consecutive_failures", 0)
            hb_icon = "🟢" if fails == 0 else "🔴"
            lines.append(f"  Heartbeat: {hb_icon} `{esc}` ({fails} failures)")
        except Exception:
            lines.append("  Heartbeat: unknown")

    # Authority summary
    auth_assets = get_all_authority()
    if auth_assets:
        lines.append("\n*Asset Authority*")
        for asset, entry in auth_assets.items():
            level = entry.get("authority", "manual")
            icon = {"agent": "🤖", "manual": "👤", "off": "⬛"}.get(level, "")
            lines.append(f"  {icon} `{asset}` — {level}")
    else:
        lines.append("\n  No assets delegated (all manual)")

    # Chat history stats
    history_path = Path("data/daemon/chat_history.jsonl")
    if history_path.exists():
        line_count = sum(1 for _ in history_path.open())
        size_kb = history_path.stat().st_size / 1024
        lines.append(f"\n  Chat history: `{line_count}` messages (`{size_kb:.0f}KB`)")

    # Recent errors
    if _diag:
        recent_errors = _diag.get_recent_errors(limit=3)
        if recent_errors:
            lines.append("\n*Recent Errors*")
            for err in recent_errors:
                data = err.get('data', {})
                src = data.get('source', data.get('tool', '?'))
                msg = data.get('message', data.get('error', '?'))[:80]
                lines.append(f"  `{src}`: {msg}")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_thesis(token: str, chat_id: str, _args: str) -> None:
    """Show all thesis states with age and conviction. Usage: /thesis"""
    from common.thesis import ThesisState, DEFAULT_THESIS_DIR
    from cli.daemon.iterators.thesis_engine import _WARN_AGE_H, _CLAMP_AGE_H

    states = ThesisState.load_all(DEFAULT_THESIS_DIR)
    if not states:
        tg_send(token, chat_id, "*Thesis States*\n\nNo thesis files found.")
        return

    lines = ["*Thesis States*", ""]
    for market, state in sorted(states.items()):
        age_h = state.age_hours
        raw_conv = state.conviction
        # Mirror the in-memory clamp applied by ThesisEngineIterator
        if age_h > _CLAMP_AGE_H:
            state.conviction = raw_conv * 0.5
            clamp_note = " ⚠️ clamped 50%"
        else:
            clamp_note = ""
        effective = state.effective_conviction()

        if age_h > _CLAMP_AGE_H:
            age_icon = "🔴"
        elif age_h > _WARN_AGE_H:
            age_icon = "🟡"
        else:
            age_icon = "🟢"

        if age_h >= 48:
            age_str = f"{age_h:.0f}h"
        else:
            age_str = f"{age_h:.1f}h"

        direction_icon = {"long": "📈", "short": "📉", "flat": "➡️"}.get(state.direction, "")
        short_market = market.split(":")[-1]
        lines.append(
            f"{age_icon} *{short_market}* {direction_icon} {state.direction.upper()}"
        )
        lines.append(
            f"  Conviction: `{raw_conv:.2f}` → effective `{effective:.2f}`{clamp_note}"
        )
        lines.append(f"  Age: `{age_str}`")
        if state.thesis_summary:
            summary = state.thesis_summary[:80] + ("…" if len(state.thesis_summary) > 80 else "")
            lines.append(f"  _{summary}_")
        lines.append("")

    tg_send(token, chat_id, "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════
# Interactive Menu System
# ═══════════════════════════════════════════════════════════════════════

# Position cache (5s TTL) — rapid menu tapping shouldn't hammer HL API
_pos_cache: dict = {"ts": 0, "data": []}
_pending_inputs: dict = {}  # chat_id -> {type, coin, size, side, entry, current, ts}


def _cached_positions() -> list:
    """Get positions with 5-second cache."""
    now = time.time()
    if now - _pos_cache["ts"] < 5:
        return _pos_cache["data"]
    positions = _get_all_positions(MAIN_ADDR)
    # Filter to non-zero size
    result = [p for p in positions if float(p.get("szi", 0)) != 0]
    _pos_cache["ts"] = now
    _pos_cache["data"] = result
    return result


def _btn(text: str, data: str) -> dict:
    """Shorthand for inline keyboard button."""
    return {"text": text, "callback_data": data}


def _build_main_menu() -> tuple:
    """Build main menu text + button grid. Returns (text, rows)."""
    ts = datetime.now(timezone.utc).strftime('%H:%M UTC')
    positions = _cached_positions()
    orders = _get_all_orders(MAIN_ADDR)
    values = _get_account_values(MAIN_ADDR)
    total = values['native'] + values['xyz'] + values.get('spot', 0)

    acct_label = "Vault" if _active_account == "vault" else "Main"
    lines = [f"📊 *Trading Terminal* — {ts}", f"Account: *{acct_label}* | Equity: `${total:,.2f}`", ""]

    rows = []

    if positions:
        lines.append(f"*Positions* ({len(positions)})")
        # Position buttons: 2 per row
        pos_btns = []
        for pos in positions[:6]:
            coin = pos.get("coin", "?")
            size = float(pos.get("szi", 0))
            upnl = float(pos.get("unrealizedPnl", 0))
            direction = "L" if size > 0 else "S"
            pnl_icon = "🟢" if upnl >= 0 else "🔴"
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
        _btn("📈 New Trade", "mn:trade"),
        _btn(f"📋 Orders ({order_count})", "mn:ord"),
    ])
    rows.append([
        _btn("💰 PnL", "mn:pnl"),
        _btn("📊 Watchlist", "mn:watch"),
    ])
    rows.append([
        _btn("⚙️ Tools", "mn:tools"),
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
        return f"No open position for `{coin}`", [[_btn("« Back", "mn:main")]]

    size = float(pos.get("szi", 0))
    entry = float(pos.get("entryPx", 0))
    upnl = float(pos.get("unrealizedPnl", 0))
    lev = pos.get("leverage", {})
    lev_val = lev.get("value", "?") if isinstance(lev, dict) else lev
    liq = pos.get("liquidationPx")
    coin_name = pos.get("coin", coin)

    direction = "LONG" if size > 0 else "SHORT"
    dir_icon = "🟢" if size > 0 else "🔴"
    pnl_sign = "+" if upnl >= 0 else ""
    current = _get_current_price(coin_name)
    px_str = f"${current:,.2f}" if current else "—"
    notional = abs(size * entry)

    lines = [
        f"{dir_icon} *{coin_name}* — {direction}",
        f"Entry `${entry:,.2f}` → Now `{px_str}`",
        f"Size `{abs(size):.1f}` | `{lev_val}x` | Notional `${notional:,.0f}`",
        f"uPnL `{pnl_sign}${upnl:,.2f}`",
    ]

    if liq and liq != "N/A":
        liq_f = float(liq)
        if current and current > 0:
            dist = abs(current - liq_f) / current * 100
            lines.append(f"Liq `${liq_f:,.2f}` ({dist:.1f}% away)")

    # Check SL/TP from orders — smart grouping
    orders = _get_all_orders(MAIN_ADDR)
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
                lines.append(f"🛡 SL: `${sl['px']}` (whole position)")
            else:
                lines.append(f"🛡 SL: `${sl['px']}` ({sl['sz']:.1f} units)")
    else:
        lines.append("🛡 SL: ⚠️ *MISSING*")

    # Display TP orders — smart: check coverage
    if tp_orders:
        # Sort by price (ascending for longs, descending for shorts)
        tp_orders.sort(key=lambda x: float(x["px"]) if x["px"] != "?" else 0,
                       reverse=(size < 0))  # shorts want descending
        covered = 0.0
        for tp in tp_orders:
            if tp["sz"] == 0:
                lines.append(f"🎯 TP: `${tp['px']}` (whole position)")
                covered = pos_size  # whole position covers everything
            else:
                if covered >= pos_size:
                    lines.append(f"🎯 TP: `${tp['px']}` ({tp['sz']:.1f} — _covered by earlier TP_)")
                else:
                    lines.append(f"🎯 TP: `${tp['px']}` ({tp['sz']:.1f} units)")
                    covered += tp["sz"]
        if covered < pos_size and not any(t["sz"] == 0 for t in tp_orders):
            uncovered = pos_size - covered
            lines.append(f"  ⚠️ `{uncovered:.1f}` units have no TP")
    else:
        lines.append("🎯 TP: ⚠️ *MISSING*")

    rows = [
        [_btn("🔴 Close Position", f"mn:cl:{coin_name}")],
        [_btn("🛡 Set SL", f"mn:sl:{coin_name}"), _btn("🎯 Set TP", f"mn:tp:{coin_name}")],
        [_btn("📉 4h", f"mn:ch:{coin_name}:4"), _btn("📊 24h", f"mn:ch:{coin_name}:24"), _btn("📈 7d", f"mn:ch:{coin_name}:168")],
        [_btn("🔍 Technicals", f"mn:mk:{coin_name}")],
        [_btn("« Back", "mn:main")],
    ]

    return "\n".join(lines), rows


def _build_watchlist_menu() -> tuple:
    """Build watchlist coin grid. Returns (text, rows)."""
    from common.watchlist import load_watchlist
    wl = load_watchlist()

    lines = ["📊 *Watchlist*", ""]
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

    rows.append([_btn("« Back", "mn:main")])
    return "\n".join(lines), rows


def _build_trade_menu() -> tuple:
    """Build trade market selection. Returns (text, rows)."""
    from common.watchlist import load_watchlist
    wl = load_watchlist()

    lines = ["📈 *New Trade — Select Market*", ""]
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

    rows.append([_btn("« Back", "mn:main")])
    return "\n".join(lines), rows


def _build_trade_side_menu(coin: str) -> tuple:
    """Build buy/sell selection for a specific coin. Returns (text, rows)."""
    price = _get_current_price(coin)
    px_str = f"${price:,.2f}" if price else "—"
    display = coin.replace("xyz:", "")

    # Check if already have a position
    pos = _find_position(coin)
    pos_line = ""
    if pos:
        size = float(pos.get("szi", 0))
        direction = "LONG" if size > 0 else "SHORT"
        upnl = float(pos.get("unrealizedPnl", 0))
        pos_line = f"\nExisting: {direction} `{abs(size):.1f}` | uPnL `${upnl:+,.2f}`"

    # Active account
    acct_label = "Vault" if _active_account == "vault" else "Main"

    lines = [
        f"📈 *Trade {display}*",
        f"Price: `{px_str}`",
        f"Account: *{acct_label}*",
    ]
    if pos_line:
        lines.append(pos_line)

    rows = [
        [_btn(f"🟢 BUY {display}", f"mn:side:{coin}:buy"),
         _btn(f"🔴 SELL {display}", f"mn:side:{coin}:sell")],
        [_btn("« Back", "mn:trade")],
    ]

    return "\n".join(lines), rows


# ── Account context ────────────────────────────────────────────
_active_account = "main"  # "main" or "vault"


def _get_active_addr() -> str:
    """Return address for the active account context."""
    if _active_account == "vault" and VAULT_ADDR:
        return VAULT_ADDR
    return MAIN_ADDR


def _build_account_menu() -> tuple:
    """Build account switcher. Returns (text, rows)."""
    lines = [f"🔄 *Account Switcher*", ""]

    # Main account
    main_vals = _get_account_values(MAIN_ADDR)
    main_total = main_vals['native'] + main_vals['xyz'] + main_vals.get('spot', 0)
    main_check = " ✅" if _active_account == "main" else ""
    lines.append(f"Main: `${main_total:,.2f}`{main_check}")

    # Vault
    if VAULT_ADDR:
        vault = _hl_post({"type": "clearinghouseState", "user": VAULT_ADDR})
        vault_val = float(vault.get("marginSummary", {}).get("accountValue", 0))
        vault_check = " ✅" if _active_account == "vault" else ""
        lines.append(f"Vault: `${vault_val:,.2f}`{vault_check}")

    rows = [
        [_btn(f"👤 Main{main_check}", "mn:acct:main")],
    ]
    if VAULT_ADDR:
        vault_check_btn = " ✅" if _active_account == "vault" else ""
        rows.append([_btn(f"🏦 Vault{vault_check_btn}", "mn:acct:vault")])

    rows.append([_btn("« Back", "mn:tools")])
    return "\n".join(lines), rows


def _build_tools_menu() -> tuple:
    """Build tools sub-menu. Returns (text, rows)."""
    acct_label = "Vault" if _active_account == "vault" else "Main"
    text = f"⚙️ *Tools* — Account: *{acct_label}*"
    rows = [
        [_btn(f"🔄 Switch Account ({acct_label})", "mn:acct")],
        [_btn("📊 Status", "mn:run:status"), _btn("🏥 Health", "mn:run:health")],
        [_btn("🔧 Diag", "mn:run:diag"), _btn("🤖 Models", "mn:run:models")],
        [_btn("🔑 Authority", "mn:run:authority"), _btn("🧠 Memory", "mn:run:memory")],
        [_btn("« Back", "mn:main")],
    ]
    return text, rows


def _menu_dispatch(token: str, chat_id: str, handler, args: str) -> None:
    """Call a command handler with correct signature (Renderer-based or legacy)."""
    if handler in RENDERER_COMMANDS:
        from common.renderer import TelegramRenderer
        handler(TelegramRenderer(token, chat_id), args)
    else:
        handler(token, chat_id, args)


def _handle_menu_callback(token: str, chat_id: str, cb_id: str, data: str, message_id: int) -> None:
    """Central router for all mn: prefixed callbacks."""
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
        cmd_chart(token, chat_id, f"{coin} {hours}")

    elif action == "mk" and len(parts) >= 3:
        coin = ":".join(parts[2:])
        cmd_market(token, chat_id, coin)

    elif action == "watch":
        text, rows = _build_watchlist_menu()
        tg_edit_grid(token, chat_id, message_id, text, rows)

    elif action == "tools":
        text, rows = _build_tools_menu()
        tg_edit_grid(token, chat_id, message_id, text, rows)

    elif action == "ord":
        _menu_dispatch(token, chat_id, cmd_orders, "")

    elif action == "pnl":
        _menu_dispatch(token, chat_id, cmd_pnl, "")

    elif action == "run" and len(parts) >= 3:
        cmd_name = parts[2]
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
        tg_send(token, chat_id, f"✅ Switched to *{_active_account.title()}* account")
        # Refresh main menu
        text, rows = _build_main_menu()
        tg_send_grid(token, chat_id, text, rows)

    elif action == "acct":
        text, rows = _build_account_menu()
        tg_edit_grid(token, chat_id, message_id, text, rows)


# ── Write action handlers ────────────────────────────────────

def _handle_trade_size_prompt(token: str, chat_id: str, coin: str, side: str) -> None:
    """Prompt user for trade size, store pending input state."""
    coin_name = coin
    current = _get_current_price(coin_name)
    px_str = f"${current:,.2f}" if current else "—"
    display = coin.replace("xyz:", "")
    side_label = "BUY (LONG)" if side == "buy" else "SELL (SHORT)"
    side_icon = "🟢" if side == "buy" else "🔴"

    # Check existing position
    pos = _find_position(coin)
    pos_line = ""
    if pos:
        sz = float(pos.get("szi", 0))
        direction = "LONG" if sz > 0 else "SHORT"
        pos_line = f"\nExisting position: {direction} `{abs(sz):.1f}`"

    # Active account
    acct_label = "Vault" if _active_account == "vault" else "Main"
    values = _get_account_values(_get_active_addr())
    equity = values['native'] + values['xyz'] + values.get('spot', 0)

    _pending_inputs[chat_id] = {
        "type": "trade",
        "coin": coin_name,
        "side": side,
        "current": current,
        "account": _active_account,
        "ts": time.time(),
    }

    tg_send(token, chat_id,
        f"{side_icon} *{side_label} {display}*\n\n"
        f"Price: `{px_str}`\n"
        f"Account: *{acct_label}* (`${equity:,.2f}`)"
        f"{pos_line}\n\n"
        f"Reply with size (number of contracts):")


def _find_position(coin: str) -> dict | None:
    """Find a position by coin name (handles xyz: prefix matching)."""
    for p in _cached_positions():
        if _coin_matches(p.get("coin", ""), coin):
            return p
    return None


def _handle_close_position(token: str, chat_id: str, coin: str) -> None:
    """Build close-position confirmation with approval buttons."""
    from cli.agent_tools import store_pending, format_confirmation

    pos = _find_position(coin)
    if not pos:
        tg_send(token, chat_id, f"No open position for `{coin}`")
        return

    size = float(pos.get("szi", 0))
    coin_name = pos.get("coin", coin)
    close_side = "sell" if size > 0 else "buy"
    current = _get_current_price(coin_name)

    args = {"coin": coin_name, "side": close_side, "size": abs(size), "dex": pos.get("_dex", "")}
    action_id = store_pending("close_position", args, chat_id)

    direction = "LONG" if size > 0 else "SHORT"
    px_str = f" @ ~`${current:,.2f}`" if current else ""
    text = f"⚠️ *Close Position*\n\n{direction} `{abs(size):.1f}` {coin_name}{px_str}\n\nApprove or reject:"
    buttons = [
        {"text": "✅ Approve", "callback_data": f"approve:{action_id}"},
        {"text": "❌ Reject", "callback_data": f"reject:{action_id}"},
    ]
    tg_send_buttons(token, chat_id, text, buttons)


def _handle_sl_prompt(token: str, chat_id: str, coin: str) -> None:
    """Prompt user for SL price, store pending input state."""
    pos = _find_position(coin)
    if not pos:
        tg_send(token, chat_id, f"No open position for `{coin}`")
        return

    size = float(pos.get("szi", 0))
    entry = float(pos.get("entryPx", 0))
    coin_name = pos.get("coin", coin)
    current = _get_current_price(coin_name)
    px_str = f"${current:,.2f}" if current else "—"

    _pending_inputs[chat_id] = {
        "type": "sl",
        "coin": coin_name,
        "size": abs(size),
        "side": "sell" if size > 0 else "buy",
        "entry": entry,
        "current": current,
        "dex": pos.get("_dex", ""),
        "ts": time.time(),
    }

    direction = "LONG" if size > 0 else "SHORT"
    close_side = "SELL" if size > 0 else "BUY"
    # SL should be BELOW entry for longs, ABOVE for shorts
    sl_hint = "below" if size > 0 else "above"

    tg_send(token, chat_id,
        f"🛡 *Set Stop-Loss for {coin_name}*\n\n"
        f"Position: {direction} `{abs(size):.1f}` @ `${entry:,.2f}`\n"
        f"Now: `{px_str}`\n\n"
        f"Order type: *Stop Market* (reduce-only)\n"
        f"Side: {close_side} | Size: whole position\n"
        f"Trigger should be _{sl_hint}_ current price\n\n"
        f"Reply with trigger price:")


def _handle_tp_prompt(token: str, chat_id: str, coin: str) -> None:
    """Prompt user for TP price, store pending input state."""
    pos = _find_position(coin)
    if not pos:
        tg_send(token, chat_id, f"No open position for `{coin}`")
        return

    size = float(pos.get("szi", 0))
    entry = float(pos.get("entryPx", 0))
    coin_name = pos.get("coin", coin)
    current = _get_current_price(coin_name)
    px_str = f"${current:,.2f}" if current else "—"

    _pending_inputs[chat_id] = {
        "type": "tp",
        "coin": coin_name,
        "size": abs(size),
        "side": "sell" if size > 0 else "buy",
        "entry": entry,
        "current": current,
        "dex": pos.get("_dex", ""),
        "ts": time.time(),
    }

    direction = "LONG" if size > 0 else "SHORT"
    close_side = "SELL" if size > 0 else "BUY"
    # TP should be ABOVE entry for longs, BELOW for shorts
    tp_hint = "above" if size > 0 else "below"

    tg_send(token, chat_id,
        f"🎯 *Set Take-Profit for {coin_name}*\n\n"
        f"Position: {direction} `{abs(size):.1f}` @ `${entry:,.2f}`\n"
        f"Now: `{px_str}`\n\n"
        f"Order type: *Take Profit Market* (reduce-only)\n"
        f"Side: {close_side} | Size: whole position\n"
        f"Trigger should be _{tp_hint}_ current price\n\n"
        f"Reply with trigger price:")


def _handle_pending_input(token: str, chat_id: str, text: str) -> bool:
    """Check if text is a pending SL/TP price reply. Returns True if handled."""
    pending = _pending_inputs.get(chat_id)
    if not pending:
        return False

    # 60-second TTL
    if time.time() - pending["ts"] > 60:
        del _pending_inputs[chat_id]
        return False

    # Try to parse as a number
    try:
        value = float(text.strip().replace("$", "").replace(",", ""))
    except ValueError:
        return False  # Not a number — let it fall through to normal routing

    # Clear pending state
    del _pending_inputs[chat_id]

    from cli.agent_tools import store_pending

    if pending["type"] == "trade":
        # Trade: value is size (contracts)
        size = value
        args = {
            "coin": pending["coin"],
            "side": pending["side"],
            "size": size,
        }
        action_id = store_pending("place_trade", args, chat_id)

        side_icon = "🟢" if pending["side"] == "buy" else "🔴"
        side_label = "BUY" if pending["side"] == "buy" else "SELL"
        current = pending.get("current")
        px_str = f" @ ~`${current:,.2f}`" if current else ""
        acct = pending.get("account", "main").title()
        text_msg = (
            f"{side_icon} *Confirm Trade*\n\n"
            f"*{side_label} `{size:.1f}` {pending['coin']}*{px_str}\n"
            f"Account: *{acct}*\n"
            f"Type: Market order\n\n"
            f"Approve or reject:"
        )
    else:
        # SL/TP: value is trigger price
        price = value
        tool_name = "set_sl" if pending["type"] == "sl" else "set_tp"
        args = {
            "coin": pending["coin"],
            "trigger_price": price,
            "side": pending["side"],
            "size": pending["size"],
            "dex": pending.get("dex", ""),
        }
        action_id = store_pending(tool_name, args, chat_id)

        label = "Stop-Loss" if pending["type"] == "sl" else "Take-Profit"
        icon = "🛡" if pending["type"] == "sl" else "🎯"
        order_type = "Stop Market" if pending["type"] == "sl" else "Take Profit Market"
        text_msg = (
            f"{icon} *Confirm {label}*\n\n"
            f"*{pending['coin']}*\n"
            f"Type: `{order_type}` (reduce-only)\n"
            f"Trigger: `${price:,.2f}`\n"
            f"Side: `{pending['side'].upper()}` | Size: whole position\n\n"
            f"Approve or reject:"
        )
    buttons = [
        {"text": "✅ Approve", "callback_data": f"approve:{action_id}"},
        {"text": "❌ Reject", "callback_data": f"reject:{action_id}"},
    ]
    tg_send_buttons(token, chat_id, text_msg, buttons)
    return True


# ── New command handlers ──────────────────────────────────────

def cmd_menu(renderer: Renderer, args: str) -> None:
    """Interactive trading terminal with button navigation."""
    if args.strip():
        # Jump to position detail if a coin is given
        coin = args.strip()
        resolved = resolve_coin(coin) if 'resolve_coin' in dir() else coin
        if resolved:
            text, rows = _build_position_detail(resolved)
        else:
            text, rows = _build_position_detail(coin)
        renderer.send_grid(text, rows)
    else:
        text, rows = _build_main_menu()
        renderer.send_grid(text, rows)


def cmd_close(token: str, chat_id: str, args: str) -> None:
    """Close a position with approval. Usage: /close BTC"""
    coin = args.strip()
    if not coin:
        tg_send(token, chat_id, "Usage: `/close <coin>`\nExample: `/close BTC`")
        return
    resolved = resolve_coin(coin)
    _handle_close_position(token, chat_id, resolved or coin)


def cmd_sl(token: str, chat_id: str, args: str) -> None:
    """Set stop-loss. Usage: /sl BTC 65500 or /sl BTC (prompts for price)"""
    parts = args.strip().split()
    if not parts:
        tg_send(token, chat_id, "Usage: `/sl <coin> [price]`\nExample: `/sl BTC 65500`")
        return
    coin = parts[0]
    resolved = resolve_coin(coin) or coin

    if len(parts) >= 2:
        # Price given directly — skip prompt, go to approval
        try:
            price = float(parts[1].replace("$", "").replace(",", ""))
        except ValueError:
            tg_send(token, chat_id, f"Invalid price: `{parts[1]}`")
            return
        pos = _find_position(resolved)
        if not pos:
            tg_send(token, chat_id, f"No open position for `{resolved}`")
            return
        size = float(pos.get("szi", 0))
        from cli.agent_tools import store_pending
        args_dict = {
            "coin": pos.get("coin", resolved),
            "trigger_price": price,
            "side": "sell" if size > 0 else "buy",
            "size": abs(size),
            "dex": pos.get("_dex", ""),
        }
        action_id = store_pending("set_sl", args_dict, chat_id)
        text = f"🛡 *Confirm Stop-Loss*\n\n{pos.get('coin', resolved)} @ `${price:,.2f}`\nSize: `{abs(size):.1f}`\n\nApprove or reject:"
        buttons = [
            {"text": "✅ Approve", "callback_data": f"approve:{action_id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{action_id}"},
        ]
        tg_send_buttons(token, chat_id, text, buttons)
    else:
        # No price — prompt for it
        _handle_sl_prompt(token, chat_id, resolved)


def cmd_tp(token: str, chat_id: str, args: str) -> None:
    """Set take-profit. Usage: /tp BTC 72000 or /tp BTC (prompts for price)"""
    parts = args.strip().split()
    if not parts:
        tg_send(token, chat_id, "Usage: `/tp <coin> [price]`\nExample: `/tp BTC 72000`")
        return
    coin = parts[0]
    resolved = resolve_coin(coin) or coin

    if len(parts) >= 2:
        try:
            price = float(parts[1].replace("$", "").replace(",", ""))
        except ValueError:
            tg_send(token, chat_id, f"Invalid price: `{parts[1]}`")
            return
        pos = _find_position(resolved)
        if not pos:
            tg_send(token, chat_id, f"No open position for `{resolved}`")
            return
        size = float(pos.get("szi", 0))
        from cli.agent_tools import store_pending
        args_dict = {
            "coin": pos.get("coin", resolved),
            "trigger_price": price,
            "side": "sell" if size > 0 else "buy",
            "size": abs(size),
            "dex": pos.get("_dex", ""),
        }
        action_id = store_pending("set_tp", args_dict, chat_id)
        text = f"🎯 *Confirm Take-Profit*\n\n{pos.get('coin', resolved)} @ `${price:,.2f}`\nSize: `{abs(size):.1f}`\n\nApprove or reject:"
        buttons = [
            {"text": "✅ Approve", "callback_data": f"approve:{action_id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{action_id}"},
        ]
        tg_send_buttons(token, chat_id, text, buttons)
    else:
        _handle_tp_prompt(token, chat_id, resolved)


# Commands that have been migrated to accept (renderer, args) instead of (token, chat_id, args).
# The dispatch shim in the polling loop creates a TelegramRenderer for these.
RENDERER_COMMANDS = {
    cmd_status, cmd_price, cmd_orders, cmd_health, cmd_menu,
}

HANDLERS = {
    "/status": cmd_status,
    "/price": cmd_price,
    "/orders": cmd_orders,
    "/pnl": cmd_pnl,
    "/commands": cmd_commands,
    "/chart": cmd_chart,
    "/market": cmd_market,
    "/m": cmd_market,
    "/position": cmd_position,
    "/pos": cmd_position,
    "/bug": cmd_bug,
    "/todo": cmd_todo,
    "/feedback": cmd_feedback,
    "/fb": cmd_feedback,
    "/memory": cmd_memory,
    "/mem": cmd_memory,
    "/diag": cmd_diag,
    "/watchlist": cmd_watchlist,
    "/w": cmd_watchlist,
    "/powerlaw": cmd_powerlaw,
    "/rebalancer": cmd_rebalancer,
    "/rebalance": cmd_rebalance,
    "/delegate": cmd_delegate,
    "/reclaim": cmd_reclaim,
    "/authority": cmd_authority,
    "/auth": cmd_authority,
    "/help": cmd_help,
    "/guide": cmd_guide,
    "/g": cmd_guide,
    "/models": cmd_models,
    "/model": cmd_models,
    "/health": cmd_health,
    "/h": cmd_health,
    "/thesis": cmd_thesis,
    "status": cmd_status,
    "price": cmd_price,
    "orders": cmd_orders,
    "pnl": cmd_pnl,
    "commands": cmd_commands,
    "chart": cmd_chart,
    "market": cmd_market,
    "m": cmd_market,
    "position": cmd_position,
    "pos": cmd_position,
    "bug": cmd_bug,
    "todo": cmd_todo,
    "feedback": cmd_feedback,
    "fb": cmd_feedback,
    "memory": cmd_memory,
    "mem": cmd_memory,
    "diag": cmd_diag,
    "watchlist": cmd_watchlist,
    "w": cmd_watchlist,
    "addmarket": cmd_addmarket,
    "addmarket!": cmd_addmarket_confirm,
    "removemarket": cmd_removemarket,
    "powerlaw": cmd_powerlaw,
    "rebalancer": cmd_rebalancer,
    "rebalance": cmd_rebalance,
    "delegate": cmd_delegate,
    "reclaim": cmd_reclaim,
    "authority": cmd_authority,
    "auth": cmd_authority,
    "help": cmd_help,
    "guide": cmd_guide,
    "g": cmd_guide,
    "models": cmd_models,
    "model": cmd_models,
    "health": cmd_health,
    "h": cmd_health,
    "thesis": cmd_thesis,
    "/menu": cmd_menu,
    "menu": cmd_menu,
    "/close": cmd_close,
    "close": cmd_close,
    "/sl": cmd_sl,
    "sl": cmd_sl,
    "/tp": cmd_tp,
    "tp": cmd_tp,
    "/start": cmd_menu,
    "start": cmd_menu,
}


# ── Main loop ────────────────────────────────────────────────

def _get_last_update_id() -> int:
    if LAST_UPDATE_FILE.exists():
        try:
            return int(LAST_UPDATE_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    return 0


def _set_last_update_id(uid: int) -> None:
    LAST_UPDATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_UPDATE_FILE.write_text(str(uid))


def _set_telegram_commands(token: str) -> None:
    """Set the Telegram bot command menu via setMyCommands API."""
    commands = [
        # Interactive Menu
        {"command": "start", "description": "Open trading terminal"},
        {"command": "menu", "description": "Trading terminal with buttons"},
        # Trading
        {"command": "status", "description": "Portfolio overview"},
        {"command": "position", "description": "Positions + risk + authority"},
        {"command": "market", "description": "Technicals, funding, OI"},
        {"command": "pnl", "description": "Profit & loss breakdown"},
        {"command": "price", "description": "Quick prices + 24h change"},
        {"command": "orders", "description": "Open orders"},
        # Position Management
        {"command": "close", "description": "Close a position"},
        {"command": "sl", "description": "Set stop-loss"},
        {"command": "tp", "description": "Set take-profit"},
        # Charts
        {"command": "chartoil", "description": "Oil price chart (add hours)"},
        {"command": "chartbtc", "description": "BTC price chart"},
        {"command": "chartgold", "description": "Gold price chart"},
        {"command": "watchlist", "description": "All markets + prices"},
        {"command": "powerlaw", "description": "BTC power law model"},
        # Agent Control
        {"command": "authority", "description": "Who manages what"},
        {"command": "delegate", "description": "Hand asset to agent"},
        {"command": "reclaim", "description": "Take asset back"},
        # Vault
        {"command": "rebalancer", "description": "Rebalancer status/start/stop"},
        {"command": "rebalance", "description": "Force vault rebalance"},
        # System
        {"command": "models", "description": "AI model selection"},
        {"command": "memory", "description": "Memory system status"},
        {"command": "health", "description": "App health check"},
        {"command": "diag", "description": "Error diagnostics"},
        {"command": "bug", "description": "Report a bug"},
        {"command": "todo", "description": "Add or list todos"},
        {"command": "feedback", "description": "Submit feedback"},
        {"command": "guide", "description": "How to use this bot"},
        {"command": "help", "description": "Full command list"},
    ]
    requests.post(
        f"https://api.telegram.org/bot{token}/setMyCommands",
        json={"commands": commands},
        timeout=10,
    )
    log.info("Set Telegram command menu (%d commands)", len(commands))


def run() -> None:
    """Main polling loop. Runs forever until SIGTERM/SIGINT."""
    token = _keychain_read("bot_token")
    chat_id = _keychain_read("chat_id")
    if not token or not chat_id:
        log.error("Telegram credentials not in Keychain. Run setup first.")
        sys.exit(1)

    # Single-instance enforcement (pacman pattern)
    # 1. Kill process from PID file if it exists
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if old_pid != os.getpid():
                os.kill(old_pid, signal.SIGTERM)
                time.sleep(0.5)
                # Force kill if still alive
                try:
                    os.kill(old_pid, 0)  # Check if still running
                    os.kill(old_pid, signal.SIGKILL)
                    time.sleep(0.3)
                except ProcessLookupError:
                    pass
                log.info("Killed previous bot instance (PID %d)", old_pid)
        except (ProcessLookupError, OSError, ValueError):
            pass
        PID_FILE.unlink(missing_ok=True)

    # 2. Scan for any orphaned instances by process name (catches missed PID files)
    my_pid = os.getpid()
    try:
        import subprocess as _sp
        result = _sp.run(
            ["pgrep", "-f", "cli.telegram_bot"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                stale_pid = int(line.strip())
                if stale_pid != my_pid:
                    log.warning("Killing orphaned telegram_bot (PID %d)", stale_pid)
                    try:
                        os.kill(stale_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
    except Exception:
        pass

    PID_FILE.write_text(str(os.getpid()))

    running = True

    def _stop(signum, frame):
        nonlocal running
        log.info("Stopping telegram bot (signal %d)", signum)
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Set Telegram command menu (what users see when typing /)
    try:
        _set_telegram_commands(token)
    except Exception as e:
        log.warning("Failed to set Telegram command menu: %s", e)

    log.info("Telegram bot started — polling every %.0fs", POLL_INTERVAL)
    tg_send(token, chat_id, "Bot online. /help for commands.")

    offset = _get_last_update_id() + 1

    while running:
        updates = tg_get_updates(token, offset)

        for update in updates:
            uid = update.get("update_id", 0)
            offset = uid + 1
            _set_last_update_id(uid)

            # Handle callback queries (inline keyboard button presses)
            cb = update.get("callback_query")
            if cb:
                cb_sender = str(cb.get("from", {}).get("id", ""))
                cb_chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                cb_data = cb.get("data", "")
                cb_id = cb.get("id", "")
                if cb_data == "noop":
                    tg_answer_callback(token, cb_id, "")
                elif cb_sender == chat_id and cb_data.startswith("model:"):
                    model_id = cb_data[6:]  # strip "model:" prefix
                    _handle_model_callback(token, cb_chat, cb_id, model_id)
                elif cb_sender == chat_id and cb_data.startswith("approve:"):
                    action_id = cb_data[8:]
                    msg_id = cb.get("message", {}).get("message_id")
                    _handle_tool_approval(token, cb_chat, cb_id, action_id, approved=True, message_id=msg_id)
                elif cb_sender == chat_id and cb_data.startswith("reject:"):
                    action_id = cb_data[7:]
                    msg_id = cb.get("message", {}).get("message_id")
                    _handle_tool_approval(token, cb_chat, cb_id, action_id, approved=False, message_id=msg_id)
                elif cb_sender == chat_id and cb_data.startswith("mn:"):
                    msg_id = cb.get("message", {}).get("message_id")
                    _handle_menu_callback(token, cb_chat, cb_id, cb_data, msg_id)
                else:
                    tg_answer_callback(token, cb_id)
                continue

            msg = update.get("message", {})
            reply_chat_id = str(msg.get("chat", {}).get("id", ""))
            sender_id = str(msg.get("from", {}).get("id", ""))
            text = (msg.get("text") or "").strip()

            # Authorize by SENDER, not chat — works in both DMs and groups
            if sender_id != chat_id or not text:
                continue

            # Check for pending SL/TP price input (catches bare numbers)
            if _handle_pending_input(token, reply_chat_id, text):
                continue

            cmd = text.split()[0].lower().lstrip("/")
            # Strip bot username from commands (e.g., /status@MyBot_bot → /status)
            if "@" in cmd:
                cmd = cmd.split("@")[0]
            cmd_key = "/" + cmd if ("/" + cmd) in HANDLERS else cmd

            # Dynamic chart shorthand: /chartoil 72 → /chart oil 72
            if cmd_key not in HANDLERS and cmd.startswith("chart") and len(cmd) > 5:
                market_alias = cmd[5:]  # e.g. "oil", "btc", "gold"
                rest = text[len(text.split()[0]):].strip()
                args_override = f"{market_alias} {rest}".strip()
                cmd_key = "/chart"
                text = f"/chart {args_override}"

            # Log incoming message for diagnostics
            if _diag:
                _diag.log_chat("user", text, channel="telegram",
                              metadata={"msg_id": msg.get("message_id"), "cmd": cmd_key if cmd_key in HANDLERS else None})

            if cmd_key in HANDLERS:
                log.info("Command: %s (chat=%s)", cmd_key, reply_chat_id)
                try:
                    args = text[len(text.split()[0]):].strip()
                    handler = HANDLERS[cmd_key]
                    if handler in RENDERER_COMMANDS:
                        handler(TelegramRenderer(token, reply_chat_id), args)
                    else:
                        handler(token, reply_chat_id, args)
                    # Log to chat history so AI knows what commands were used
                    try:
                        from cli.telegram_agent import _log_chat
                        _log_chat("user", f"[command] {cmd_key} {args}".strip())
                    except Exception:
                        pass
                except Exception as e:
                    log.error("Command %s failed: %s", cmd_key, e)
                    if _diag:
                        _diag.log_error("telegram_cmd", f"{cmd_key} failed: {e}")
                    tg_send(token, reply_chat_id, f"Error: {e}")
            else:
                # Not a command — handle with AI agent (direct, no OpenClaw)
                is_group = msg.get("chat", {}).get("type", "") in ("group", "supergroup")
                if is_group:
                    log.debug("Ignoring free text in group: %s", text[:50])
                else:
                    log.info("AI chat: %s", text[:80])
                    try:
                        from cli.telegram_agent import handle_ai_message
                        handle_ai_message(
                            token, reply_chat_id, text,
                            user_name=msg.get("from", {}).get("first_name", ""),
                        )
                    except Exception as e:
                        log.error("AI handler failed: %s", e)
                        tg_send(token, reply_chat_id, f"AI error: {e}\n\nUse /help for commands.")

        # Periodic maintenance (every ~60s = 30 poll cycles)
        if running and offset % 30 == 0:
            try:
                from cli.agent_tools import cleanup_expired_pending
                cleanup_expired_pending()
            except Exception:
                pass

        if running:
            time.sleep(POLL_INTERVAL)

    # Cleanup
    PID_FILE.unlink(missing_ok=True)
    log.info("Telegram bot stopped.")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    run()
