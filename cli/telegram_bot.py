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

# ── Watchlist: markets we track ──────────────────────────────
# Format: (display_name, hl_coin, aliases, category)
WATCHLIST = [
    ("BTC", "BTC", ["btc", "bitcoin"], "crypto"),
    ("ETH", "ETH", ["eth", "ethereum"], "crypto"),
    ("Brent Oil", "xyz:BRENTOIL", ["oil", "brent", "brentoil", "crude"], "commodity"),
    ("WTI Crude", "xyz:CL", ["wti", "cl", "crude-us"], "commodity"),
    ("Gold", "xyz:GOLD", ["gold", "xau"], "commodity"),
    ("Silver", "xyz:SILVER", ["silver", "xag"], "commodity"),
    ("Nat Gas", "xyz:NATGAS", ["natgas", "gas", "ng"], "commodity"),
    ("S&P 500", "xyz:SP500", ["sp500", "spx", "sp"], "index"),
    ("Nvidia", "xyz:NVDA", ["nvda", "nvidia"], "equity"),
    ("Tesla", "xyz:TSLA", ["tsla", "tesla"], "equity"),
]

# Quick lookup: alias → hl_coin
COIN_ALIASES: dict[str, str] = {}
for _name, _coin, _aliases, _cat in WATCHLIST:
    COIN_ALIASES[_coin.lower()] = _coin
    COIN_ALIASES[_name.lower()] = _coin
    for a in _aliases:
        COIN_ALIASES[a.lower()] = _coin

APPROVED_MARKETS = [w[1] for w in WATCHLIST]


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


def _get_all_orders(addr: str) -> list:
    """Get open orders from BOTH native and xyz clearinghouses."""
    orders = []
    for dex in ['', 'xyz']:
        payload = {'type': 'openOrders', 'user': addr}
        if dex:
            payload['dex'] = dex
        orders.extend(_hl_post(payload) or [])
    return orders


def _get_account_values(addr: str) -> dict:
    """Get account values from both clearinghouses."""
    result = {'native': 0.0, 'xyz': 0.0}
    for dex in ['', 'xyz']:
        payload = {'type': 'clearinghouseState', 'user': addr}
        if dex:
            payload['dex'] = dex
        state = _hl_post(payload)
        val = float(state.get('marginSummary', {}).get('accountValue', 0))
        result[dex or 'native'] = val
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

def cmd_status(token: str, chat_id: str, _args: str) -> None:
    ts = datetime.now(timezone.utc).strftime('%a %H:%M UTC')
    lines = [f"*Portfolio* — {ts}", ""]

    # Spot balances
    spot = _hl_post({"type": "spotClearinghouseState", "user": MAIN_ADDR})
    spot_total = 0.0
    for b in spot.get("balances", []):
        total = float(b.get("total", 0))
        if total > 0.01 and b.get("coin") == "USDC":
            spot_total = total

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
    else:
        lines.append("No open positions\n")

    # Account values
    values = _get_account_values(MAIN_ADDR)
    total_perps = values['native'] + values['xyz']
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

    # Vault
    vault = _hl_post({"type": "clearinghouseState", "user": VAULT_ADDR})
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

    tg_send(token, chat_id, "\n".join(lines))


def cmd_price(token: str, chat_id: str, _args: str) -> None:
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

    tg_send(token, chat_id, "\n".join(lines))


def cmd_orders(token: str, chat_id: str, _args: str) -> None:
    orders = _get_all_orders(MAIN_ADDR)
    if not orders:
        tg_send(token, chat_id, "📋 No open orders")
        return
    lines = [f"📋 *Open Orders* ({len(orders)})", ""]
    for o in orders:
        side = "🟢 BUY" if o.get("side") == "B" else "🔴 SELL"
        lines.append(f"{side} `{o.get('sz')}` {o.get('coin')} @ `${o.get('limitPx')}`")
    tg_send(token, chat_id, "\n".join(lines))


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

    # Vault
    vault = _hl_post({"type": "clearinghouseState", "user": VAULT_ADDR})
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
    lines.append(f"\n💎 *Balances*")
    lines.append(f"  Main: `${main_val:,.2f}` | Vault: `${vault_val:,.2f}`")
    lines.append(f"  Total: `${main_val + vault_val:,.2f}`")

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

    # Technicals — formatted for Telegram
    try:
        from common.market_snapshot import build_snapshot
        from modules.candle_cache import CandleCache
        cache = CandleCache()
        snap = build_snapshot(coin, cache, price or 0)

        # Flags as readable labels
        if snap.flags:
            flag_labels = {
                "bb_squeeze_4h": "BB squeeze (4h)", "bb_squeeze_1h": "BB squeeze (1h)",
                "rsi_oversold_1h": "RSI oversold (1h)", "rsi_overbought_1h": "RSI overbought (1h)",
                "rsi_oversold_4h": "RSI oversold (4h)", "rsi_overbought_4h": "RSI overbought (4h)",
                "bullish_div_4h": "Bullish div (4h)", "bearish_div_4h": "Bearish div (4h)",
                "above_vwap": "Above VWAP", "below_vwap": "Below VWAP",
                "volume_surge": "Volume surge", "near_support": "Near support",
                "near_resistance": "Near resistance",
            }
            readable = [flag_labels.get(f, f) for f in snap.flags]
            lines.append(f"  Signals: {', '.join(readable)}")

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

        # Timeframe trends
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
                if u.get("name") == coin or u.get("name") == coin.replace("xyz:", ""):
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
    total_equity = values['native'] + values['xyz']

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
            if o.get('coin') == coin:
                if o.get('orderType') == 'Stop Market' or (o.get('triggerCondition') and o.get('side') != ('B' if size > 0 else 'A')):
                    sl_found = True
                elif o.get('reduceOnly'):
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
        "*How This Bot Works*\n"
        "\n*Trading Commands*\n"
        "Your portfolio at a glance — use `/status` for the overview, "
        "`/position` for detailed risk, `/market oil` for technicals.\n"
        "\n*Charts*\n"
        "Type `/chartoil 72` for a 72-hour oil chart. "
        "Also: `/chartbtc`, `/chartgold`, `/chartsilver`. "
        "Just the shorthand works.\n"
        "\n*AI Chat*\n"
        "Type anything that's not a command and the AI responds with "
        "live market data. It knows your positions, prices, and thesis. "
        "Ask it questions like \"what's oil doing?\" or \"should I add here?\"\n"
        "\n*Agent Delegation*\n"
        "You control which assets the bot can trade autonomously.\n"
        "  `/authority` — see who manages what\n"
        "  `/delegate BRENTOIL` — give BRENTOIL to the agent\n"
        "  `/reclaim BRENTOIL` — take it back\n"
        "\n🤖 *Agent* = bot manages entries, exits, sizing\n"
        "👤 *Manual* = you trade, bot only ensures SL/TP exist\n"
        "\n*Tracking*\n"
        "  `/bug text` — report issues\n"
        "  `/todo text` — add tasks\n"
        "  `/feedback text` — suggestions\n"
        "All picked up by Claude Code next session.\n"
        "\n`/help` for full command list")


def cmd_health(token: str, chat_id: str, _args: str) -> None:
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

    lines.append("")
    lines.append("`/diag` for error details")
    tg_send(token, chat_id, "\n".join(lines))


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
    """Show AI model selector with inline keyboard buttons."""
    from cli.telegram_agent import get_available_models, _get_active_model

    models = get_available_models()
    current = _get_active_model()

    free = [m for m in models if m.get("tier") == "free"]
    paid = [m for m in models if m.get("tier") != "free"]

    # Free models
    free_buttons = []
    for m in free:
        label = f"{'✅ ' if m['id'] == current else ''}{m['name']}"
        free_buttons.append({"text": label, "callback_data": f"model:{m['id']}"})

    current_name = next((m["name"] for m in models if m["id"] == current), current)
    tg_send_buttons(token, chat_id,
        f"🤖 *AI Models*\n\nActive: *{current_name}*\n\n*Free models* (rate limited):",
        free_buttons)

    # Paid models
    if paid:
        paid_buttons = []
        for m in paid:
            label = f"{'✅ ' if m['id'] == current else ''}{m['name']}"
            paid_buttons.append({"text": label, "callback_data": f"model:{m['id']}"})
        tg_send_buttons(token, chat_id, "*Paid models* (require credits):", paid_buttons)


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
        # Trading
        {"command": "status", "description": "Portfolio overview"},
        {"command": "position", "description": "Positions + risk + authority"},
        {"command": "market", "description": "Technicals, funding, OI"},
        {"command": "pnl", "description": "Profit & loss breakdown"},
        {"command": "price", "description": "Quick prices + 24h change"},
        {"command": "orders", "description": "Open orders"},
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
                if cb_sender == chat_id and cb_data.startswith("model:"):
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
                    HANDLERS[cmd_key](token, reply_chat_id, args)
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

        if running:
            time.sleep(POLL_INTERVAL)

    # Cleanup
    PID_FILE.unlink(missing_ok=True)
    log.info("Telegram bot stopped.")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    run()
