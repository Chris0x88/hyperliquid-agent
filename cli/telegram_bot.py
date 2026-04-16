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

import cli.telegram_hl as telegram_hl
from cli.telegram_hl import (
    HL_API,
    _hl_post, _get_all_positions, _get_all_orders, _get_account_values,
    _get_market_oi, _get_current_price, _get_all_market_ctx,
    _coin_matches, resolve_coin,
)
from cli.telegram_api import (
    tg_send, tg_send_buttons, tg_remove_buttons, tg_answer_callback,
    tg_send_grid, tg_edit_grid, tg_get_updates,
)
import cli.telegram_api as _tg_api  # for mutable _poll_fail_count access
from cli.telegram_menu import (  # noqa: E402
    _cached_positions, _btn, _build_main_menu, _build_position_detail,
    _build_watchlist_menu, _build_trade_menu, _build_trade_side_menu,
    _build_account_menu, _build_tools_menu, _menu_dispatch,
    _handle_menu_callback, _get_active_addr, _pos_cache,
)
import cli.telegram_menu as _tg_menu  # for mutable _active_account access
from cli.telegram_approval import (  # noqa: E402
    _lock_approval_message, _handle_tool_approval, _handle_pending_input,
    _handle_trade_size_prompt, _find_position, _handle_close_position,
    _handle_sl_prompt, _handle_tp_prompt, _pending_inputs,
)

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

# HL_API moved to cli/telegram_hl.py (imported above)
from common.account_resolver import resolve_main_wallet, resolve_vault_address as _resolve_vault
MAIN_ADDR = resolve_main_wallet(required=True)
VAULT_ADDR = _resolve_vault(required=False) or ""
POLL_INTERVAL = 2.0  # seconds
COMMAND_QUEUE = Path("data/daemon/telegram_commands.jsonl")
PID_FILE = Path("data/daemon/telegram_bot.pid")
LAST_UPDATE_FILE = Path("data/daemon/telegram_last_update_id.txt")
CATALYSTS_JSONL = "data/news/catalysts.jsonl"  # sub-system 1: news ingest catalysts
SUPPLY_STATE_JSON = "data/supply/state.json"  # sub-system 2: supply ledger aggregated state
SUPPLY_DISRUPTIONS_JSONL = "data/supply/disruptions.jsonl"  # sub-system 2: append-only disruption log
HEATMAP_ZONES_JSONL = "data/heatmap/zones.jsonl"  # sub-system 3: liquidity zones snapshots
HEATMAP_CASCADES_JSONL = "data/heatmap/cascades.jsonl"  # sub-system 3: liquidation cascade events
BOT_PATTERNS_JSONL = "data/research/bot_patterns.jsonl"  # sub-system 4: bot-pattern classifications
OIL_BOTPATTERN_CONFIG_JSON = "data/config/oil_botpattern.json"  # sub-system 5: strategy config + kill switches
OIL_BOTPATTERN_STATE_JSON = "data/strategy/oil_botpattern_state.json"  # sub-system 5: strategy state
OIL_BOTPATTERN_DECISIONS_JSONL = "data/strategy/oil_botpattern_journal.jsonl"  # sub-system 5: per-decision audit log
OIL_BOTPATTERN_TUNE_CONFIG_JSON = "data/config/oil_botpattern_tune.json"  # sub-system 6 L1: bounded auto-tune config
OIL_BOTPATTERN_TUNE_AUDIT_JSONL = "data/strategy/oil_botpattern_tune_audit.jsonl"  # sub-system 6: nudge audit log
OIL_BOTPATTERN_REFLECT_CONFIG_JSON = "data/config/oil_botpattern_reflect.json"  # sub-system 6 L2: weekly reflect config
OIL_BOTPATTERN_REFLECT_STATE_JSON = "data/strategy/oil_botpattern_reflect_state.json"  # sub-system 6 L2: cadence state
OIL_BOTPATTERN_PROPOSALS_JSONL = "data/strategy/oil_botpattern_proposals.jsonl"  # sub-system 6 L2: structural proposals

# ── Watchlist: markets we track (loaded from data/config/watchlist.json) ──
from common.watchlist import (
    load_watchlist as _load_wl,
    get_watchlist_as_tuples as _get_wl_tuples,
    get_coin_aliases as _get_aliases,
    get_watchlist_coins as _get_coins,
)

WATCHLIST = _get_wl_tuples()
# Local copy kept for global-reload sites; canonical copy in cli.telegram_hl
COIN_ALIASES: dict[str, str] = _get_aliases()
APPROVED_MARKETS = _get_coins()


# _coin_matches, resolve_coin → Moved to cli/telegram_hl.py


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


# ── Telegram API helpers ── Moved to cli/telegram_api.py ─────
# tg_send, tg_send_buttons, tg_remove_buttons, tg_answer_callback,
# tg_send_grid, tg_edit_grid, tg_get_updates, _poll_fail_count


def _poll_backoff_seconds() -> float:
    """Exponential backoff: 2s → 4s → 8s → … capped at 30s."""
    if _tg_api._poll_fail_count <= 0:
        return POLL_INTERVAL
    return min(POLL_INTERVAL * (2 ** _tg_api._poll_fail_count), 30.0)


# ── HL API helpers — moved to cli/telegram_hl.py ─────────────
# _hl_post, _get_all_positions, _get_all_orders, _get_account_values,
# _get_market_oi, _get_current_price, _get_all_market_ctx,
# _coin_matches, resolve_coin  →  imported at top of file


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


# _get_all_orders, _get_account_values, _get_market_oi,
# _get_current_price, _get_all_market_ctx → Moved to cli/telegram_hl.py


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
    from common.account_state import fetch_registered_account_state

    ts = datetime.now(timezone.utc).strftime('%a %H:%M UTC')
    lines = [f"*Portfolio* — {ts}", ""]

    try:
        bundle = fetch_registered_account_state()
    except Exception as e:
        log.error("cmd_status: account fetch failed: %s", e)
        bundle = {}
    account_rows = bundle.get("accounts", [])
    positions = bundle.get("positions", [])
    # Detect fetch failure: no accounts returned means the API call failed
    if not account_rows and not positions and not bundle.get("account"):
        lines.append("Data unavailable — exchange API may be down. Try again shortly.\n")
        renderer.send_text("\n".join(lines))
        return
    if positions:
        for pos in positions:
            coin = pos.get('coin', '?')
            size = float(pos.get('size', 0))
            entry = float(pos.get('entry', 0))
            upnl = float(pos.get('upnl', 0))
            liq = pos.get('liq')
            lev_val = pos.get('leverage', '?')
            notional = abs(size * entry)
            acct_label = pos.get('account_label', pos.get('account_role', 'Account'))

            direction = "LONG" if size > 0 else "SHORT"
            dir_dot = "🟢" if size > 0 else "🔴"
            pnl_sign = "+" if upnl >= 0 else ""

            # Current price
            current = _get_current_price(coin)
            px_str = f"`${current:,.2f}`" if current else "—"

            # OI / volume for liquidity
            oi_str = _get_market_oi(coin, pos.get('dex', ''))

            lines.append(f"{dir_dot} *{coin}* — {direction} • _{acct_label}_")
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

    acc = bundle.get("account", {})
    total_perps = float(acc.get("native_equity", 0)) + float(acc.get("xyz_equity", 0))
    spot_total = float(acc.get("spot_usdc", 0))
    grand_total = float(acc.get("total_equity", 0))

    lines.append(f"\n*Equity*")
    lines.append(f"  `${grand_total:,.2f}`")
    if total_perps > 0 and spot_total > 0:
        lines.append(f"  Perps `${total_perps:,.2f}` • Spot `${spot_total:,.2f}`")
    elif total_perps > 0:
        lines.append(f"  Perps `${total_perps:,.2f}`")
    elif spot_total > 0:
        lines.append(f"  Spot `${spot_total:,.2f}`")

    if len(account_rows) > 1:
        lines.append("")
        for row in account_rows:
            lines.append(
                f"  {row['label']}: `${row['total_equity']:,.2f}`"
                f" (native `${row['native_equity']:,.2f}` • xyz `${row['xyz_equity']:,.2f}`"
                f" • spot `${row['spot_usdc']:,.2f}`)"
            )

    # Orders (compact)
    orders = _get_all_orders(MAIN_ADDR)
    if orders:
        lines.append(f"\n*Orders* ({len(orders)})")
        for o in orders[:5]:
            side_dot = "🟢" if o.get("side") == "B" else "🔴"
            lines.append(f"  {side_dot} {o.get('sz')} {o.get('coin')} @ `${o.get('limitPx')}`")

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


def _send_brief_pdf(token: str, chat_id: str, mechanical: bool, label: str) -> None:
    """Shared sender for /brief and /briefai. Calls daily_report with the
    requested flavour and uploads the PDF via sendDocument."""
    try:
        tg_send(token, chat_id, f"Generating {label}... (5-15s)")
        from cli import daily_report
        path = daily_report.generate_report(mechanical=mechanical)
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        with open(path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": f"{label} — {path.name}"},
                files={"document": (path.name, f, "application/pdf")},
                timeout=60,
            )
        if not resp.json().get("ok"):
            tg_send(token, chat_id, f"{label} upload failed: {resp.text[:200]}")
    except Exception as e:
        tg_send(token, chat_id, f"{label} error: {e}")


def cmd_brief(token: str, chat_id: str, _args: str) -> None:
    """MECHANICAL brief — fixed code, NO AI content. Portfolio, positions,
    orders, market technicals (price/EMA/RSI/trend/liquidity), funding 24h,
    chart. Use `/briefai` for the thesis + catalysts version. Per CLAUDE.md
    slash commands MUST be fixed code; AI-dependent variants get the `ai`
    suffix."""
    _send_brief_pdf(token, chat_id, mechanical=True, label="Brief")


def cmd_briefai(token: str, chat_id: str, _args: str) -> None:
    """AI-INFLUENCED brief — same as `/brief` plus the THESIS line and
    hardcoded CATALYSTS list. Marked with the `ai` suffix because the thesis
    text and catalyst calendar are seeded by AI/research, not pure code."""
    _send_brief_pdf(token, chat_id, mechanical=False, label="BriefAI")


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
        # Reload module-level vars (both local and telegram_hl copy)
        global WATCHLIST, COIN_ALIASES, APPROVED_MARKETS
        WATCHLIST = _get_wl_tuples()
        COIN_ALIASES = _get_aliases()
        telegram_hl.COIN_ALIASES = COIN_ALIASES
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
        telegram_hl.COIN_ALIASES = COIN_ALIASES
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


def cmd_restart(token: str, chat_id: str, _args: str) -> None:
    """Restart all daemons (daemon + telegram + heartbeat) via launchd."""
    import subprocess
    import os
    import signal

    uid = os.getuid()
    services = [
        "com.hyperliquid.daemon",
        "com.hyperliquid.heartbeat",
        "com.hyperliquid.telegram",
    ]

    results = []
    for svc in services:
        # Stop the service (launchd KeepAlive will restart it)
        try:
            subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{uid}/{svc}"],
                capture_output=True, text=True, timeout=10,
            )
            results.append(f"  {svc}: restarted")
        except Exception as e:
            results.append(f"  {svc}: error ({e})")

    msg = "🔄 *Restarting all services*\n\n" + "\n".join(results)
    msg += "\n\n_Telegram bot will reconnect in a few seconds._"
    tg_send(token, chat_id, msg)

    # Give Telegram time to deliver the message, then exit.
    # launchd KeepAlive will restart us.
    import threading
    def _delayed_exit():
        import time as _t
        _t.sleep(2)
        os._exit(0)
    threading.Thread(target=_delayed_exit, daemon=True).start()


def cmd_restartall(token: str, chat_id: str, _args: str) -> None:
    """Restart ALL services including Mission Control web dashboard."""
    import subprocess
    import os

    uid = os.getuid()
    services = [
        "com.hyperliquid.daemon",
        "com.hyperliquid.heartbeat",
        "com.hyperliquid.telegram",
        "com.hyperliquid.web",
    ]

    results = []
    for svc in services:
        try:
            r = subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{uid}/{svc}"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                results.append(f"  {svc}: restarted")
            else:
                # Service might not be loaded yet
                results.append(f"  {svc}: not loaded (skip)")
        except Exception as e:
            results.append(f"  {svc}: error ({e})")

    msg = "🔄 *Restarting ALL services (including web)*\n\n" + "\n".join(results)
    msg += "\n\n_Dashboard: http://127.0.0.1:3000_"
    msg += "\n_Docs: http://127.0.0.1:4321_"
    msg += "\n\n_Telegram bot will reconnect in a few seconds._"
    tg_send(token, chat_id, msg)

    import threading
    def _delayed_exit():
        import time as _t
        _t.sleep(2)
        os._exit(0)
    threading.Thread(target=_delayed_exit, daemon=True).start()


def cmd_signals(token: str, chat_id: str, args: str) -> None:
    """Show recent Pulse and Radar signals.

    Usage:
      /signals           — all signals, limit 15
      /signals 5         — all signals, limit 5
      /signals wti       — oil/BRENTOIL signals only, limit 15
      /signals btc 5     — BTC signals only, limit 5
    """
    import json as _json
    from pathlib import Path as _Path
    signals_path = _Path("data/research/signals.jsonl")
    if not signals_path.exists():
        tg_send(token, chat_id,
                "📡 *No signals yet*\n\n"
                "Pulse (capital inflow) and Radar (opportunity scanner) "
                "signals will appear here once the daemon generates them.\n\n"
                "Pulse scans every 2 min for OI/volume/funding anomalies.\n"
                "Radar scans every 5 min for multi-timeframe setups.")
        return

    # Parse args: optional asset name and/or limit number (order-insensitive)
    limit = 15
    asset_filter: Optional[str] = None  # canonical coin name, e.g. "BRENTOIL" or "BTC"
    for tok in args.split():
        tok = tok.strip()
        if not tok:
            continue
        if tok.isdigit():
            limit = min(int(tok), 30)
        else:
            resolved = resolve_coin(tok)
            if resolved:
                asset_filter = resolved
            else:
                # Treat uppercase token as a direct coin name (e.g. "BRENTOIL")
                asset_filter = tok.upper()

    lines_raw = signals_path.read_text().strip().split("\n")
    # Read more lines than limit so filtering doesn't cut results short
    read_count = limit * 5 if asset_filter else limit
    signals_raw = []
    for line in lines_raw[-read_count:]:
        try:
            signals_raw.append(_json.loads(line))
        except Exception:
            pass

    # Apply asset filter using _coin_matches for xyz: prefix safety
    if asset_filter:
        signals = [s for s in signals_raw if _coin_matches(s.get("asset", ""), asset_filter)]
        signals = signals[-limit:]
    else:
        signals = signals_raw[-limit:]

    if not signals:
        if asset_filter:
            tg_send(token, chat_id, f"📡 No signals found for {asset_filter}.")
        else:
            tg_send(token, chat_id, "📡 No recent signals.")
        return

    signals.reverse()  # newest first
    parts = [f"📡 *Last {len(signals)} Signals*\n"]

    for s in signals:
        source = s.get("source", "?").upper()
        asset = s.get("asset", "?")
        direction = s.get("direction", "?")
        ts = s.get("timestamp_human", "?")

        if source == "PULSE":
            tier = s.get("tier", "?")
            conf = s.get("confidence", 0)
            sig_type = s.get("signal_type", "")
            oi = s.get("oi_delta_pct", 0)
            vol = s.get("volume_surge_ratio", 0)
            parts.append(
                f"⚡ `{ts}`\n"
                f"  *PULSE* {asset} {direction} tier={tier} conf={conf:.0f}%\n"
                f"  {sig_type} OI={oi:+.1f}% vol={vol:.1f}x"
            )
        elif source == "RADAR":
            score = s.get("score", 0)
            parts.append(
                f"🎯 `{ts}`\n"
                f"  *RADAR* {asset} {direction} score={score:.0f}/400"
            )
        else:
            parts.append(f"📊 `{ts}` {source} {asset} {direction}")

    msg = "\n\n".join(parts)
    if len(msg) > 4000:
        msg = msg[:4000] + "\n\n_(truncated)_"
    tg_send(token, chat_id, msg)


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
    """Add, list, search, done, dismiss, or show todos.

    Usage:
        /todo                         — list open todos
        /todo <description>           — add a new todo
        /todo list [open|all|done]    — list with status filter
        /todo search <query>          — substring search
        /todo done <id>               — mark done
        /todo dismiss <id> [note]     — mark dismissed
        /todo show <id>               — full detail + event history

    Event-sourced append-only. See modules/feedback_store.py.
    """
    from engines.learning import feedback_store as fs

    text = args.strip()

    # Bare /todo → list open.
    if not text:
        items = [i for i in fs.load_todos() if i.status == "open"]
        if not items:
            tg_send(token, chat_id, "No open todos. Use `/todo fix the chart labels`")
            return
        lines = ["*Open Todos*\n"]
        for item in items[-15:]:
            short = item.id[-4:]
            ts = (item.timestamp or "")[:10]
            lines.append(f"`{short}` {item.text[:80]} _({ts})_")
        lines.append("\nUse `/todo done <id>` or `/todo show <id>`.")
        tg_send(token, chat_id, "\n".join(lines))
        return

    lower = text.lower()

    # list subcommand
    if lower == "list" or lower.startswith("list "):
        rest = text[4:].strip().lower() or "open"
        all_items = fs.load_todos()
        if rest == "all":
            items = all_items
            header = f"*All Todos ({len(items)})*"
        elif rest == "done":
            items = [i for i in all_items if i.status == "done"]
            header = f"*Done Todos ({len(items)})*"
        else:
            items = [i for i in all_items if i.status == "open"]
            header = f"*Open Todos ({len(items)})*"
        if not items:
            tg_send(token, chat_id, f"{header}\n\n_(none)_")
            return
        lines = [header, ""]
        for item in items[-15:]:
            short = item.id[-4:]
            marker = {"open": "•", "done": "✓", "dismissed": "×"}.get(item.status, "?")
            ts = (item.timestamp or "")[:10]
            lines.append(f"`{short}` {marker} {item.text[:80]} _({ts})_")
        tg_send(token, chat_id, "\n".join(lines))
        return

    # search subcommand
    if lower.startswith("search "):
        q = text[7:].strip()
        matches = fs.search_todos(q, limit=10)
        if not matches:
            tg_send(token, chat_id, f"No todos matching `{q}`.")
            return
        lines = [f"*Todo search: `{q}` ({len(matches)} hits)*", ""]
        for item in matches:
            short = item.id[-4:]
            marker = {"open": "•", "done": "✓", "dismissed": "×"}.get(item.status, "?")
            lines.append(f"`{short}` {marker} {item.text[:100]}")
        tg_send(token, chat_id, "\n".join(lines))
        return

    # done / dismiss / show subcommands
    if lower.startswith("done "):
        prefix = text[5:].strip().split(None, 1)
        target = prefix[0] if prefix else ""
        note = prefix[1] if len(prefix) > 1 else ""
        items = fs.load_todos()
        item = fs.resolve_prefix(target, items)
        if item is None:
            tg_send(token, chat_id, f"No unique todo matching `{target}`. Try `/todo list`.")
            return
        fs.set_todo_status(item.id, "done", note=note)
        tg_send(token, chat_id, f"*Todo done* `{item.id[-4:]}`\n{item.text[:100]}")
        return

    if lower.startswith("dismiss "):
        prefix = text[8:].strip().split(None, 1)
        target = prefix[0] if prefix else ""
        note = prefix[1] if len(prefix) > 1 else ""
        items = fs.load_todos()
        item = fs.resolve_prefix(target, items)
        if item is None:
            tg_send(token, chat_id, f"No unique todo matching `{target}`. Try `/todo list`.")
            return
        fs.set_todo_status(item.id, "dismissed", note=note)
        tg_send(token, chat_id, f"*Todo dismissed* `{item.id[-4:]}`")
        return

    if lower.startswith("show "):
        target = text[5:].strip()
        items = fs.load_todos()
        item = fs.resolve_prefix(target, items)
        if item is None:
            tg_send(token, chat_id, f"No unique todo matching `{target}`.")
            return
        lines = [
            f"*Todo {item.id}*",
            f"Status: `{item.status}`",
            f"Created: {item.timestamp[:19]}",
            f"Source: {item.source}",
        ]
        if item.tags:
            lines.append("Tags: " + ", ".join(f"`{t}`" for t in item.tags))
        lines.append("")
        lines.append(item.text)
        if item.history:
            lines.append("\n*History*")
            for ev in item.history:
                lines.append(
                    f"  {ev.get('timestamp', '')[:19]} {ev.get('event', '?')} "
                    f"{ev.get('from_status', '')}→{ev.get('to_status', ev.get('tag', ''))}"
                )
        tg_send(token, chat_id, "\n".join(lines))
        return

    # Default: bare text → add new todo.
    new_id = fs.add_todo(text[:500])
    tg_send(token, chat_id, f"Todo added `{new_id[-4:]}`.\n`{text[:100]}`")


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
        "  /close — close a position (with approval)\n"
        "  /sl — set/view stop-loss (with approval)\n"
        "  /tp — set/view take-profit (with approval)\n"
        "  /menu — interactive button terminal\n"
        "\n*Conviction & Intelligence*\n"
        "  /thesis — show all thesis states (conviction, age, direction)\n"
        "  /signals — recent Pulse + Radar signals\n"
        "\n*Watchlist*\n"
        "  /addmarket crude — search + add a new market\n"
        "  /removemarket xyz:CL — remove a market\n"
        "\n*Charts*\n"
        "  /chart SYM [hours] — generic chart dispatcher\n"
        "  /chartoil 72 — oil chart (hours)\n"
        "  /chartbtc 168 — BTC chart\n"
        "  /chartgold — gold chart\n"
        "  /watchlist — all markets + prices\n"
        "  /powerlaw — BTC power law model\n"
        "  /brief — mechanical PDF (fixed code, no AI)\n"
        "  /briefai — brief + thesis & catalysts (AI)\n"
        "  /news — last 10 catalysts by severity\n"
        "  /catalysts — upcoming catalysts in next 7 days\n"
        "  /supply — show current supply disruption state\n"
        "  /disruptions — list top 10 active supply disruptions\n"
        "  /disrupt — manually log a supply disruption\n"
        "  /disrupt-update — update an existing supply disruption\n"
        "  /heatmap [SYMBOL] — stop/liquidity heatmap (sub-system 3)\n"
        "  /botpatterns [SYMBOL N] — recent bot-pattern classifications (sub-system 4)\n"
        "  /oilbot — oil_botpattern strategy state (sub-system 5)\n"
        "  /oilbotjournal [N] — recent strategy decisions\n"
        "  /oilbotreviewai [N] — AI review of strategy behaviour\n"
        "\n*Lab & Architect*\n"
        "  /lab — strategy development pipeline status\n"
        "  /lab discover <market> — profile + create experiments\n"
        "  /lab promote <id> — promote graduated experiment\n"
        "  /architect — self-improvement engine status\n"
        "  /architect detect — run detection (zero cost)\n"
        "  /architect proposals — pending proposals\n"
        "  /architect approve|reject <id>\n"
        "\n*Self-Tune Harness (sub-system 6)*\n"
        "  /selftune — L1 auto-tune + L2 reflect state\n"
        "  /selftuneproposals [N] — pending structural proposals\n"
        "  /selftuneapprove <id> — approve + apply a proposal\n"
        "  /selftunereject <id> — reject a proposal\n"
        "  /patterncatalog — L3 bot-pattern library state\n"
        "  /patternpromote <id> — promote a pattern candidate into the live catalog\n"
        "  /patternreject <id> — reject a pattern candidate\n"
        "  /shadoweval [id] — L4 counterfactual shadow eval results\n"
        "  /sim — shadow (paper) account state + positions + recent trades\n"
        "  /readiness — sub-system 5 activation preflight checklist\n"
        "  /activate — guided activation walkthrough (next / confirm / back / rollback)\n"
        "  /adaptlog [N|filter] — query adaptive evaluator decisions (exits/trails/live/shadow/SYM)\n"
        "\n*Lesson Corpus*\n"
        "  /lessons — recent trade post-mortems\n"
        "  /lesson <id> — view verbatim body\n"
        "  /lesson approve|reject <id> — curate\n"
        "  /lessonsearch <query> — BM25 search\n"
        "  /lessonauthorai [N|all] — author pending candidates via AI\n"
        "  /brutalreviewai — full deep audit of the codebase + trading state (AI)\n"
        "  /critique [N|symbol] — recent entry critiques (auto-fired on every new position)\n"
        "\n*Chat History (historical oracle)*\n"
        "  /chathistory — last 10 entries (alias /ch)\n"
        "  /chathistory 25 — last N entries (max 50)\n"
        "  /chathistory search <query> — substring search\n"
        "  /chathistory stats — count, date range, roles, market-context coverage\n"
        "\n*Discipline*\n"
        "  /nudge — things Chris should do (restore drill, brutal review, lesson queue)\n"
        "  /nudge overdue — only overdue items\n"
        "  /nudge done <id> — mark a ritual done now\n"
        "\n*Agent Control*\n"
        "  /authority — who manages what\n"
        "  /delegate ASSET — hand to agent\n"
        "  /reclaim ASSET — take back\n"
        "\n*Vault*\n"
        "  /rebalancer — status / start / stop\n"
        "  /rebalance — force rebalance now\n"
        "\n*System*\n"
        "  /restart — restart all services (daemon + bot + heartbeat)\n"
        "  /models — AI model selection\n"
        "  /memory — memory system status\n"
        "  /health — app health check\n"
        "  /diag — error diagnostics\n"
        "  /bug text — report a bug\n"
        "  /todo text — add todo (`list|search|done|dismiss|show`)\n"
        "  /feedback text — feedback (`list|search|resolve|dismiss|tag|show`)\n"
        "  /guide — how to use this bot\n"
        "\n*AI Chat*\n"
        "  Type anything — AI responds with live data\n"
        "\n*Convention*\n"
        "  Slash commands = fixed code, no AI.\n"
        "  Commands ending in `ai` (e.g. /briefai) include AI content.\n"
        "  Natural-language messages always go to the AI agent.")


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
        from exchange.hl_proxy import HLProxy
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
        from engines.data.candle_cache import CandleCache
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
    """Submit, list, search, resolve, dismiss, tag, or show feedback.

    Usage:
        /feedback <text>                     — add a new feedback item
        /feedback list [open|all|resolved]   — list (default: open)
        /feedback search <query>             — substring search
        /feedback resolve <id> [note]        — mark resolved
        /feedback dismiss <id> [note]        — mark won't-fix
        /feedback tag <id> <tag>             — attach a tag
        /feedback show <id>                  — full detail + event history

    Historical: this is an event-sourced append-only log. Rows are
    NEVER rewritten in place. See modules/feedback_store.py.
    """
    from engines.learning import feedback_store as fs

    text = args.strip()
    if not text:
        tg_send(token, chat_id,
            "*Feedback*\n\n"
            "Usage:\n"
            "`/feedback market updates need more detail on technicals`\n"
            "`/feedback list [open|all|resolved]`\n"
            "`/feedback search <query>`\n"
            "`/feedback resolve <id> [note]`\n"
            "`/feedback dismiss <id> [note]`\n"
            "`/feedback tag <id> <tag>`\n"
            "`/feedback show <id>`")
        return

    lower = text.lower()

    # list subcommand
    if lower == "list" or lower.startswith("list "):
        rest = text[4:].strip().lower() or "open"
        all_items = fs.load_feedback()
        if rest == "all":
            items = all_items
            header = f"*All Feedback ({len(items)})*"
        elif rest == "resolved":
            items = [i for i in all_items if i.status == "resolved"]
            header = f"*Resolved Feedback ({len(items)})*"
        elif rest == "dismissed":
            items = [i for i in all_items if i.status == "dismissed"]
            header = f"*Dismissed Feedback ({len(items)})*"
        else:
            items = [i for i in all_items if i.status == "open"]
            header = f"*Open Feedback ({len(items)})*"
        if not items:
            tg_send(token, chat_id, f"{header}\n\n_(none)_")
            return
        lines = [header, ""]
        for item in items[-20:]:
            short = item.id[-4:]
            marker = {"open": "•", "resolved": "✓", "dismissed": "×", "wontfix": "×"}.get(item.status, "?")
            ts = (item.timestamp or "")[:10]
            preview = item.text[:80].replace("\n", " ")
            lines.append(f"`{short}` {marker} {preview} _({ts})_")
        lines.append("\nUse `/feedback show <id>` for detail.")
        tg_send(token, chat_id, "\n".join(lines))
        return

    # search subcommand
    if lower.startswith("search "):
        q = text[7:].strip()
        matches = fs.search_feedback(q, limit=15)
        if not matches:
            tg_send(token, chat_id, f"No feedback matching `{q}`.")
            return
        lines = [f"*Feedback search: `{q}` ({len(matches)} hits)*", ""]
        for item in matches:
            short = item.id[-4:]
            marker = {"open": "•", "resolved": "✓", "dismissed": "×"}.get(item.status, "?")
            preview = item.text[:100].replace("\n", " ")
            lines.append(f"`{short}` {marker} {preview}")
        tg_send(token, chat_id, "\n".join(lines))
        return

    # resolve / dismiss / tag / show subcommands
    if lower.startswith("resolve "):
        parts = text[8:].strip().split(None, 1)
        target = parts[0] if parts else ""
        note = parts[1] if len(parts) > 1 else ""
        item = fs.resolve_prefix(target, fs.load_feedback())
        if item is None:
            tg_send(token, chat_id, f"No unique feedback matching `{target}`.")
            return
        fs.set_feedback_status(item.id, "resolved", note=note)
        tg_send(token, chat_id, f"*Resolved* `{item.id[-4:]}`\n{item.text[:100]}")
        return

    if lower.startswith("dismiss "):
        parts = text[8:].strip().split(None, 1)
        target = parts[0] if parts else ""
        note = parts[1] if len(parts) > 1 else ""
        item = fs.resolve_prefix(target, fs.load_feedback())
        if item is None:
            tg_send(token, chat_id, f"No unique feedback matching `{target}`.")
            return
        fs.set_feedback_status(item.id, "dismissed", note=note)
        tg_send(token, chat_id, f"*Dismissed* `{item.id[-4:]}`")
        return

    if lower.startswith("tag "):
        parts = text[4:].strip().split(None, 1)
        if len(parts) < 2:
            tg_send(token, chat_id, "Usage: `/feedback tag <id> <tag>`")
            return
        target, tag = parts[0], parts[1].strip()
        item = fs.resolve_prefix(target, fs.load_feedback())
        if item is None:
            tg_send(token, chat_id, f"No unique feedback matching `{target}`.")
            return
        fs.tag_feedback(item.id, tag)
        tg_send(token, chat_id, f"*Tagged* `{item.id[-4:]}` with `{tag}`")
        return

    if lower.startswith("show "):
        target = text[5:].strip()
        item = fs.resolve_prefix(target, fs.load_feedback())
        if item is None:
            tg_send(token, chat_id, f"No unique feedback matching `{target}`.")
            return
        lines = [
            f"*Feedback {item.id}*",
            f"Status: `{item.status}`",
            f"Created: {(item.timestamp or '')[:19]}",
            f"Source: {item.source}",
        ]
        if item.tags:
            lines.append("Tags: " + ", ".join(f"`{t}`" for t in item.tags))
        lines.append("")
        lines.append(item.text)
        if item.history:
            lines.append("\n*History*")
            for ev in item.history:
                kind = ev.get("event", "?")
                ts = (ev.get("timestamp") or "")[:19]
                detail = ev.get("to_status") or ev.get("tag") or ""
                note = ev.get("note") or ""
                suffix = f" — _{note}_" if note else ""
                lines.append(f"  {ts} {kind} `{detail}`{suffix}")
        tg_send(token, chat_id, "\n".join(lines))
        return

    # Default: bare text → add new feedback item.
    new_id = fs.add_feedback(text[:1000])
    tg_send(token, chat_id, f"*Feedback Recorded* `{new_id[-4:]}`\n\n`{text[:100]}`")
    log.info("Feedback via Telegram (%s): %s", new_id, text[:80])


def cmd_feedback_resolve(token: str, chat_id: str, args: str) -> None:
    """Legacy admin shim — mark feedback as resolved by id, short prefix, or ``all``.

    Historical note: the pre-2026-04-09 implementation read the whole
    file, mutated entries in memory, and rewrote the file with
    ``open(path, "w")``. That silently modified the very historical
    rows Chris said he values most. This now dispatches to the
    append-only event store — primary rows are never touched.
    """
    from engines.learning import feedback_store as fs

    arg = args.strip()
    all_items = fs.load_feedback()

    if not arg:
        unresolved = [i for i in all_items if i.status == "open"]
        if not unresolved:
            tg_send(token, chat_id, "*All feedback resolved!*")
            return
        lines = [f"*Unresolved Feedback ({len(unresolved)})*", ""]
        for item in unresolved[-20:]:
            short = item.id[-4:]
            preview = item.text[:60].replace("\n", " ")
            date = (item.timestamp or "")[:10]
            lines.append(f"`{short}` {date} — {preview}")
        lines.append("\nResolve: `/feedback_resolve <id>` or `all`")
        tg_send(token, chat_id, "\n".join(lines))
        return

    if arg.lower() == "all":
        count = 0
        for item in all_items:
            if item.status == "open":
                if fs.set_feedback_status(item.id, "resolved", note="bulk resolve"):
                    count += 1
        tg_send(token, chat_id, f"*Resolved {count} feedback item(s)*")
        return

    item = fs.resolve_prefix(arg, all_items)
    if item is None:
        tg_send(token, chat_id, f"No unique feedback matching `{arg}`.")
        return
    fs.set_feedback_status(item.id, "resolved")
    tg_send(token, chat_id, f"*Resolved 1 feedback item*\n`{item.id[-4:]}` {item.text[:80]}")


def cmd_news(token: str, chat_id: str, args: str) -> None:
    """Show the last 10 catalysts ranked by severity DESC, created_at DESC.

    Deterministic — reads data/news/catalysts.jsonl directly, no AI.
    Sub-system 1 (news ingest). See docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md.
    """
    path = Path(CATALYSTS_JSONL)
    if not path.exists():
        tg_send(token, chat_id, "🛢️ No catalysts yet. News ingestion may be disabled or still booting.")
        return

    entries: list[dict] = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        tg_send(token, chat_id, f"🛢️ Error reading catalysts: {e}")
        return

    # Sort: severity DESC, then created_at DESC
    entries.sort(key=lambda c: (-int(c.get("severity", 0)), c.get("created_at", "")), reverse=False)
    top = entries[:10]

    if not top:
        tg_send(token, chat_id, "🛢️ No catalysts yet.")
        return

    lines = ["🛢️ *Latest catalysts (last 10 by severity)*", ""]
    for c in top:
        sev = int(c.get("severity", 0))
        cat = c.get("category", "?")
        when = c.get("event_date", "")[:16].replace("T", " ") + " UTC"
        direction = c.get("expected_direction") or "?"
        instruments = ", ".join(c.get("instruments", []))
        lines.append(f"`sev={sev}` {cat} — {when}")
        lines.append(f"  → {instruments} ({direction})")
        lines.append("")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_catalysts(token: str, chat_id: str, args: str) -> None:
    """Show upcoming catalysts in the next 7 days.

    Deterministic — reads data/news/catalysts.jsonl directly.
    Sub-system 1 (news ingest). See docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md.
    """
    from datetime import datetime, timedelta, timezone

    path = Path(CATALYSTS_JSONL)
    if not path.exists():
        tg_send(token, chat_id, "🛢️ No upcoming catalysts.")
        return

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=7)

    upcoming: list[dict] = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    c = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    ed = datetime.fromisoformat(c["event_date"])
                except (KeyError, ValueError):
                    continue
                if now <= ed <= horizon:
                    upcoming.append(c)
    except OSError as e:
        tg_send(token, chat_id, f"🛢️ Error reading catalysts: {e}")
        return

    if not upcoming:
        tg_send(token, chat_id, "🛢️ No catalysts in the next 7 days.")
        return

    upcoming.sort(key=lambda c: c["event_date"])

    lines = ["🛢️ *Upcoming catalysts (next 7 days)*", ""]
    for c in upcoming[:20]:
        when = c["event_date"][:16].replace("T", " ") + " UTC"
        sev = int(c.get("severity", 0))
        cat = c.get("category", "?")
        instruments = ", ".join(c.get("instruments", []))
        lines.append(f"`sev={sev}` {cat} — {when}")
        lines.append(f"  → {instruments}")
        lines.append("")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_supply(token: str, chat_id: str, args: str) -> None:
    """Show the latest SupplyState (deterministic, NOT AI).

    Sub-system 2 (supply ledger). See docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER_PLAN.md.
    """
    import json
    from pathlib import Path

    path = Path(SUPPLY_STATE_JSON)
    if not path.exists():
        tg_send(token, chat_id, "🛢️ No supply state yet — supply_ledger may be disabled or still booting.", markdown=True)
        return

    try:
        s = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        tg_send(token, chat_id, f"🛢️ Error reading supply state: {e}", markdown=True)
        return

    def _fmt(n: float, unit: str) -> str:
        return f"{int(n):,} {unit}"

    lines = [
        "🛢️ *Supply state*",
        f"_computed {s.get('computed_at', '?')[:19].replace('T', ' ')} UTC_",
        "",
        f"Total offline: {_fmt(s.get('total_offline_bpd', 0), 'bpd')} + {_fmt(s.get('total_offline_mcfd', 0), 'mcfd')}",
        f"Active disruptions: {s.get('active_disruption_count', 0)} (high-confidence: {s.get('high_confidence_count', 0)})",
        "",
    ]
    if s.get("by_region"):
        lines.append("*By region:*")
        for region, vol in sorted(s["by_region"].items(), key=lambda kv: -kv[1]):
            lines.append(f"  `{region:<16}` {_fmt(vol, 'bpd')}")
        lines.append("")
    if s.get("by_facility_type"):
        lines.append("*By type:*")
        for ft, vol in sorted(s["by_facility_type"].items(), key=lambda kv: -kv[1]):
            lines.append(f"  `{ft:<16}` {_fmt(vol, 'bpd')}")
        lines.append("")
    if s.get("active_chokepoints"):
        lines.append(f"Active chokepoints: {', '.join(s['active_chokepoints'])}")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def cmd_disruptions(token: str, chat_id: str, args: str) -> None:
    """List top 10 active supply disruptions by confidence*volume.

    Sub-system 2 (supply ledger). Deterministic — reads disruptions.jsonl directly.
    """
    import json
    from pathlib import Path

    path = Path(SUPPLY_DISRUPTIONS_JSONL)
    if not path.exists():
        tg_send(token, chat_id, "🛢️ No disruptions logged yet.", markdown=True)
        return

    latest: dict = {}
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = row.get("id")
                if not rid:
                    continue
                prev = latest.get(rid)
                if prev is None or row.get("updated_at", "") > prev.get("updated_at", ""):
                    latest[rid] = row
    except OSError as e:
        tg_send(token, chat_id, f"🛢️ Error reading disruptions: {e}", markdown=True)
        return

    active = [r for r in latest.values() if r.get("status") in ("active", "partial")]
    active.sort(key=lambda r: (r.get("confidence", 0) * (r.get("volume_offline") or 0)), reverse=True)
    top = active[:10]

    if not top:
        tg_send(token, chat_id, "🛢️ No active disruptions.", markdown=True)
        return

    lines = ["🛢️ *Active disruptions (top 10)*", ""]
    for r in top:
        vol = r.get("volume_offline")
        unit = r.get("volume_unit") or ""
        vol_str = f"{int(vol):,} {unit}" if vol else "? volume"
        lines.append(f"`conf={r.get('confidence', 0)}` {r.get('facility_type', '?')} — {r.get('facility_name', '?')}")
        lines.append(f"  → {r.get('region', '?')} | {vol_str} | {r.get('status', '?')}")
        if r.get("notes"):
            lines.append(f"  _{r['notes'][:80]}_")
        lines.append("")
    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def cmd_disrupt(token: str, chat_id: str, args: str) -> None:
    """Manually append a supply disruption.

    Usage: /disrupt <type> <location> [volume] [unit] [status] [date] ["notes"]
    Example: /disrupt refinery Volgograd 200000 bpd active 2026-04-08 "drone strike"
    Sub-system 2 (supply ledger).
    """
    import hashlib
    import json
    import shlex
    from datetime import datetime, timezone
    from pathlib import Path

    if not args.strip():
        tg_send(token, chat_id,
                "🛢️ *Usage:* `/disrupt <type> <location> [volume] [unit] [status] [date] \"notes\"`\n\n"
                "Types: refinery, oilfield, gas_plant, terminal, pipeline, ship, chokepoint\n"
                "Units: bpd, mcfd\n"
                "Status: active, partial, restored\n\n"
                "Example:\n`/disrupt refinery Volgograd 200000 bpd active 2026-04-08 \"drone strike\"`",
                markdown=True)
        return

    try:
        parts = shlex.split(args)
    except ValueError as e:
        tg_send(token, chat_id, f"🛢️ Parse error: {e}", markdown=True)
        return

    if len(parts) < 2:
        tg_send(token, chat_id, "🛢️ Need at least `<type> <location>`. Send `/disrupt` for full usage.", markdown=True)
        return

    facility_type = parts[0]
    location = parts[1]
    volume = None
    unit = None
    status = "active"
    incident_iso = datetime.now(timezone.utc).date().isoformat()
    notes = ""

    i = 2
    if i < len(parts):
        try:
            volume = float(parts[i])
            i += 1
        except ValueError:
            pass
    if i < len(parts) and parts[i] in ("bpd", "mcfd"):
        unit = parts[i]
        i += 1
    if i < len(parts) and parts[i] in ("active", "partial", "restored", "unknown"):
        status = parts[i]
        i += 1
    if i < len(parts):
        try:
            datetime.fromisoformat(parts[i])
            incident_iso = parts[i]
            i += 1
        except ValueError:
            pass
    if i < len(parts):
        notes = " ".join(parts[i:])

    incident_dt = datetime.fromisoformat(incident_iso)
    if incident_dt.tzinfo is None:
        incident_dt = incident_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    from engines.data.supply_ledger import classify_region
    region = classify_region(f"{location} {notes}")

    did = hashlib.sha256(f"{location}|{incident_dt.isoformat()}".encode("utf-8")).hexdigest()[:16]

    row = {
        "id": did,
        "source": "manual",
        "source_ref": str(chat_id),
        "facility_name": f"{location} {facility_type}",
        "facility_type": facility_type,
        "location": location,
        "region": region,
        "volume_offline": volume,
        "volume_unit": unit,
        "incident_date": incident_dt.isoformat(),
        "expected_recovery": None,
        "confidence": 4,
        "status": status,
        "instruments": ["xyz:BRENTOIL", "CL"],
        "notes": notes,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    path = Path(SUPPLY_DISRUPTIONS_JSONL)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")

    tg_send(token, chat_id,
            f"🛢️ Logged disruption `{did}`\n{facility_type} / {location} / {region} / {status}\n"
            f"{'volume: ' + str(volume) + ' ' + (unit or '') if volume else '(volume unknown)'}",
            markdown=True)


def cmd_disrupt_update(token: str, chat_id: str, args: str) -> None:
    """Update an existing disruption by id-prefix. Appends a new row (history preserved).

    Usage: /disrupt-update <id_prefix> key=value [key=value ...]
    Sub-system 2 (supply ledger).
    """
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        tg_send(token, chat_id,
                "🛢️ *Usage:* `/disrupt-update <id_prefix> key=value [key=value ...]`\n\n"
                "Keys: status, volume_offline, volume_unit, expected_recovery, confidence, notes\n\n"
                "Example: `/disrupt-update abc12345 status=restored expected_recovery=2026-04-15`",
                markdown=True)
        return

    id_prefix = parts[0]
    updates_raw = parts[1]

    updates: dict = {}
    for token_pair in updates_raw.split():
        if "=" not in token_pair:
            continue
        k, v = token_pair.split("=", 1)
        updates[k] = v

    path = Path(SUPPLY_DISRUPTIONS_JSONL)
    if not path.exists():
        tg_send(token, chat_id, "🛢️ No disruptions file yet.", markdown=True)
        return

    latest: dict = {}
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("id", "").startswith(id_prefix):
                prev = latest.get(row["id"])
                if prev is None or row.get("updated_at", "") > prev.get("updated_at", ""):
                    latest[row["id"]] = row

    if not latest:
        tg_send(token, chat_id, f"🛢️ No disruption matching id prefix `{id_prefix}`.", markdown=True)
        return
    if len(latest) > 1:
        tg_send(token, chat_id, f"🛢️ Ambiguous prefix `{id_prefix}` matches {len(latest)} ids. Use a longer prefix.", markdown=True)
        return

    base = list(latest.values())[0]
    new_row = dict(base)
    for k, v in updates.items():
        if k in ("volume_offline", "confidence"):
            try:
                new_row[k] = float(v) if k == "volume_offline" else int(v)
            except ValueError:
                pass
        elif k == "expected_recovery":
            try:
                new_row[k] = datetime.fromisoformat(v).isoformat()
            except ValueError:
                pass
        else:
            new_row[k] = v
    new_row["updated_at"] = datetime.now(timezone.utc).isoformat()

    with path.open("a") as f:
        f.write(json.dumps(new_row) + "\n")

    tg_send(token, chat_id,
            f"🛢️ Updated disruption `{new_row['id']}`: " + ", ".join(f"{k}={v}" for k, v in updates.items()),
            markdown=True)


def cmd_heatmap(token: str, chat_id: str, args: str) -> None:
    """Show the latest stop/liquidity heatmap snapshot.

    Sub-system 3 (stop/liquidity heatmap). Deterministic — reads
    data/heatmap/{zones,cascades}.jsonl directly. NOT AI-driven.

    Optional argument: instrument symbol (default BRENTOIL).
    """
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    instrument = (args or "").strip().upper() or "BRENTOIL"

    zones_path = Path(HEATMAP_ZONES_JSONL)
    cascades_path = Path(HEATMAP_CASCADES_JSONL)

    if not zones_path.exists():
        tg_send(token, chat_id,
                "🗺️ No heatmap data yet — heatmap iterator may be disabled or still booting.",
                markdown=True)
        return

    # Read latest snapshot for instrument
    rows: list[dict] = []
    try:
        with zones_path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("instrument") == instrument:
                    rows.append(row)
    except OSError as e:
        tg_send(token, chat_id, f"🗺️ Error reading heatmap zones: {e}", markdown=True)
        return

    if not rows:
        tg_send(token, chat_id,
                f"🗺️ No zones logged for {instrument} yet.",
                markdown=True)
        return

    latest_ts = max(r.get("snapshot_at", "") for r in rows)
    latest = [r for r in rows if r.get("snapshot_at") == latest_ts]
    bids = sorted([r for r in latest if r.get("side") == "bid"], key=lambda r: r.get("rank", 99))
    asks = sorted([r for r in latest if r.get("side") == "ask"], key=lambda r: r.get("rank", 99))

    mid = latest[0].get("mid", 0.0) if latest else 0.0

    def _fmt_zone(r: dict) -> str:
        notional_k = (r.get("notional_usd") or 0) / 1000.0
        return (
            f"  #{r.get('rank')} {r.get('centroid'):.2f} "
            f"({r.get('distance_bps'):.0f}bps) "
            f"${notional_k:,.0f}K x{r.get('level_count')}"
        )

    lines = [
        f"🗺️ *Heatmap — {instrument}*",
        f"_snapshot {latest_ts[:19].replace('T', ' ')} UTC | mid {mid:.2f}_",
        "",
    ]

    if asks:
        lines.append("*Ask walls (above mid):*")
        for r in asks:
            lines.append(_fmt_zone(r))
        lines.append("")
    if bids:
        lines.append("*Bid walls (below mid):*")
        for r in bids:
            lines.append(_fmt_zone(r))
        lines.append("")

    # Recent cascades (last 5)
    if cascades_path.exists():
        cascades: list[dict] = []
        try:
            with cascades_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        c = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if c.get("instrument") == instrument:
                        cascades.append(c)
        except OSError:
            cascades = []
        if cascades:
            cascades.sort(key=lambda c: c.get("detected_at", ""), reverse=True)
            lines.append("*Recent cascades (last 5):*")
            for c in cascades[:5]:
                ts = (c.get("detected_at", "")[:19].replace("T", " "))
                lines.append(
                    f"  {ts} {c.get('side')} sev{c.get('severity')} "
                    f"OI {c.get('oi_delta_pct'):+.1f}% "
                    f"funding {c.get('funding_jump_bps'):+.1f}bps"
                )

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def cmd_botpatterns(token: str, chat_id: str, args: str) -> None:
    """Show recent bot-pattern classifications.

    Sub-system 4 (bot-pattern classifier). Deterministic — reads
    data/research/bot_patterns.jsonl directly. NOT AI-driven.

    Args: optional SYMBOL and/or N (default BRENTOIL, last 10).
    """
    import json
    from pathlib import Path

    instrument = "BRENTOIL"
    limit = 10
    for tok in (args or "").split():
        tok = tok.strip()
        if not tok:
            continue
        if tok.isdigit():
            limit = max(1, min(50, int(tok)))
        else:
            instrument = tok.upper()

    path = Path(BOT_PATTERNS_JSONL)
    if not path.exists():
        tg_send(token, chat_id,
                "🤖 No bot-pattern classifications yet — bot_classifier may be disabled or still booting.",
                markdown=True)
        return

    rows: list[dict] = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("instrument") == instrument:
                    rows.append(row)
    except OSError as e:
        tg_send(token, chat_id, f"🤖 Error reading bot_patterns: {e}", markdown=True)
        return

    if not rows:
        tg_send(token, chat_id,
                f"🤖 No classifications logged for {instrument} yet.",
                markdown=True)
        return

    rows.sort(key=lambda r: r.get("detected_at", ""), reverse=True)
    rows = rows[:limit]

    lines = [
        f"🤖 *Bot patterns — {instrument}* (last {len(rows)})",
        "",
    ]
    for r in rows:
        ts = (r.get("detected_at", "")[:19].replace("T", " "))
        cls = r.get("classification", "?")
        conf = float(r.get("confidence", 0))
        direction = r.get("direction", "?")
        move = float(r.get("price_change_pct", 0))
        emoji = {
            "bot_driven_overextension": "🔥",
            "informed_move": "📊",
            "mixed": "⚖️",
            "unclear": "·",
        }.get(cls, "·")
        lines.append(
            f"{emoji} `{ts}` *{cls}* conf={conf:.2f} {direction} {move:+.2f}%"
        )
        signals = r.get("signals", [])
        if signals:
            for s in signals[:3]:
                lines.append(f"     · {s}")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def cmd_oilbot(token: str, chat_id: str, args: str) -> None:
    """Show sub-system 5 (oil_botpattern strategy) state.

    Deterministic — reads state + config JSON directly. NOT AI-driven.
    """
    import json
    from pathlib import Path

    try:
        cfg = json.loads(Path(OIL_BOTPATTERN_CONFIG_JSON).read_text()) if Path(OIL_BOTPATTERN_CONFIG_JSON).exists() else {}
    except (OSError, json.JSONDecodeError):
        cfg = {}
    try:
        state = json.loads(Path(OIL_BOTPATTERN_STATE_JSON).read_text()) if Path(OIL_BOTPATTERN_STATE_JSON).exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}

    enabled = cfg.get("enabled", False)
    shorts = cfg.get("short_legs_enabled", False)
    instruments = cfg.get("instruments", [])

    lines = ["🛢️ *oil_botpattern strategy (sub-system 5)*", ""]
    lines.append(f"*Master kill switch:* {'🟢 ON' if enabled else '🔴 OFF'}")
    lines.append(f"*Short legs:* {'🟢 ON' if shorts else '🔴 OFF'}")
    lines.append(f"*Instruments:* {', '.join(instruments) or 'none'}")
    if state.get("enabled_since"):
        lines.append(f"*Enabled since:* {state['enabled_since'][:19].replace('T', ' ')} UTC")
    lines.append("")

    brakes = cfg.get("drawdown_brakes", {})
    daily_pnl = float(state.get("daily_realised_pnl_usd", 0.0))
    weekly_pnl = float(state.get("weekly_realised_pnl_usd", 0.0))
    monthly_pnl = float(state.get("monthly_realised_pnl_usd", 0.0))
    lines.append("*Circuit breakers:*")
    lines.append(f"  Daily P&L:   ${daily_pnl:+,.0f}  (cap {brakes.get('daily_max_loss_pct', '?')}%)")
    lines.append(f"  Weekly P&L:  ${weekly_pnl:+,.0f}  (cap {brakes.get('weekly_max_loss_pct', '?')}%)")
    lines.append(f"  Monthly P&L: ${monthly_pnl:+,.0f}  (cap {brakes.get('monthly_max_loss_pct', '?')}%)")
    if state.get("daily_brake_tripped_at"):
        lines.append(f"  ⚠️ Daily brake tripped at {state['daily_brake_tripped_at'][:19]}")
    if state.get("weekly_brake_tripped_at"):
        lines.append(f"  🔴 Weekly brake tripped at {state['weekly_brake_tripped_at'][:19]}")
    if state.get("monthly_brake_tripped_at"):
        lines.append(f"  🔴 Monthly brake tripped at {state['monthly_brake_tripped_at'][:19]}")
    if state.get("brake_cleared_at"):
        lines.append(f"  ✅ Manual clear: {state['brake_cleared_at'][:19]}")
    lines.append("")

    positions = state.get("open_positions", {})
    if positions:
        lines.append("*Open tactical positions:*")
        for inst, p in positions.items():
            side = p.get("side", "?")
            entry_price = float(p.get("entry_price", 0.0))
            size = float(p.get("size", 0.0))
            lev = float(p.get("leverage", 0.0))
            notional = size * entry_price
            funding = float(p.get("cumulative_funding_usd", 0.0))
            funding_pct = funding / notional * 100.0 if notional > 0 else 0.0
            entry_ts = p.get("entry_ts", "")[:19].replace("T", " ")
            lines.append(f"  {side.upper()} {inst} @ {entry_price:.2f} size={size:.2f} lev={lev}x")
            lines.append(f"    entry {entry_ts} UTC | notional ${notional:,.0f}")
            lines.append(f"    funding paid ${funding:,.0f} ({funding_pct:+.2f}%)")
    else:
        lines.append("*Open tactical positions:* none")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def cmd_oilbotjournal(token: str, chat_id: str, args: str) -> None:
    """Show recent oil_botpattern decision records. Deterministic."""
    import json
    from pathlib import Path

    limit = 20
    if args:
        try:
            limit = max(1, min(50, int(args.strip())))
        except ValueError:
            pass

    path = Path(OIL_BOTPATTERN_DECISIONS_JSONL)
    if not path.exists():
        tg_send(token, chat_id,
                "🛢️ No oil_botpattern decisions yet — strategy may be disabled.",
                markdown=True)
        return

    rows: list[dict] = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        tg_send(token, chat_id, f"🛢️ Error reading decisions: {e}", markdown=True)
        return

    rows.sort(key=lambda r: r.get("decided_at", ""), reverse=True)
    rows = rows[:limit]

    if not rows:
        tg_send(token, chat_id, "🛢️ No decisions logged.", markdown=True)
        return

    lines = [f"🛢️ *oil_botpattern decisions* (last {len(rows)})", ""]
    for r in rows:
        ts = r.get("decided_at", "")[:19].replace("T", " ")
        direction = r.get("direction", "?")
        action = r.get("action", "?")
        edge = float(r.get("edge", 0))
        cls = r.get("classification", "?")
        emoji = "✅" if action == "open" else "❌" if action == "skip" else "⏸️"
        lines.append(f"{emoji} `{ts}` *{action}* {direction} edge={edge:.2f} ({cls})")
        failed = [g for g in r.get("gate_results", []) if not g.get("passed", False)]
        for g in failed[:2]:
            lines.append(f"     · blocked: {g.get('name')}: {g.get('reason', '')}")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def cmd_oilbotreviewai(token: str, chat_id: str, args: str) -> None:
    """AI review of recent oil_botpattern decisions. AI-SUFFIXED."""
    import json
    from pathlib import Path

    limit = 50
    if args:
        try:
            limit = max(1, min(200, int(args.strip())))
        except ValueError:
            pass

    path = Path(OIL_BOTPATTERN_DECISIONS_JSONL)
    if not path.exists():
        tg_send(token, chat_id, "🛢️ No decisions to review yet.", markdown=True)
        return

    rows: list[dict] = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        tg_send(token, chat_id, f"🛢️ Error: {e}", markdown=True)
        return

    rows.sort(key=lambda r: r.get("decided_at", ""), reverse=True)
    rows = rows[:limit]

    if not rows:
        tg_send(token, chat_id, "🛢️ No decisions to review.", markdown=True)
        return

    summary_lines = [
        f"Review the last {len(rows)} oil_botpattern strategy decisions. "
        "Summarize: (1) which gate failures are most common, (2) how edge scores "
        "trend, (3) any pattern in classification vs direction, (4) suggestions "
        "for tuning. Keep it concise — max 8 bullet points.",
        "",
        "Decisions:",
    ]
    for r in rows:
        summary_lines.append(json.dumps({
            "t": r.get("decided_at", ""),
            "inst": r.get("instrument"),
            "dir": r.get("direction"),
            "action": r.get("action"),
            "edge": r.get("edge"),
            "cls": r.get("classification"),
            "conf": r.get("classifier_confidence"),
            "gates_failed": [g.get("name") for g in r.get("gate_results", []) if not g.get("passed")],
        }))

    try:
        from cli.telegram_agent import handle_ai_message
        handle_ai_message(token, chat_id, "\n".join(summary_lines))
    except ImportError:
        tg_send(token, chat_id,
                "🛢️ AI review unavailable — telegram_agent not loaded.",
                markdown=True)


# ── Sub-system 6: self-tune harness commands ─────────────────────────

def cmd_selftune(token: str, chat_id: str, _args: str) -> None:
    """Show sub-system 6 self-tune harness state (L1 + L2).

    Deterministic — reads tune config + strategy config + audit log + proposals
    file. NOT AI-driven.
    """
    import json
    from pathlib import Path

    def _read_json(path: str) -> dict:
        try:
            return json.loads(Path(path).read_text()) if Path(path).exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    tune_cfg = _read_json(OIL_BOTPATTERN_TUNE_CONFIG_JSON)
    reflect_cfg = _read_json(OIL_BOTPATTERN_REFLECT_CONFIG_JSON)
    strat_cfg = _read_json(OIL_BOTPATTERN_CONFIG_JSON)
    reflect_state = _read_json(OIL_BOTPATTERN_REFLECT_STATE_JSON)

    tune_enabled = bool(tune_cfg.get("enabled", False))
    reflect_enabled = bool(reflect_cfg.get("enabled", False))

    lines = ["🎛️ *oil_botpattern self-tune harness (sub-system 6)*", ""]
    lines.append(f"*L1 auto-tune:* {'🟢 ON' if tune_enabled else '🔴 OFF'}")
    lines.append(f"*L2 reflect:*   {'🟢 ON' if reflect_enabled else '🔴 OFF'}")
    lines.append("")

    # L1 param snapshot
    bounds = tune_cfg.get("bounds", {}) or {}
    if bounds:
        lines.append("*Tunable params (current / [min–max]):*")
        for name, spec in bounds.items():
            cur = strat_cfg.get(name, "?")
            bmin = spec.get("min", "?")
            bmax = spec.get("max", "?")
            lines.append(f"  `{name}` = {cur}  [{bmin}–{bmax}]")
        lines.append("")

    # Last N audit records (nudge history)
    audit_path = Path(OIL_BOTPATTERN_TUNE_AUDIT_JSONL)
    nudges: list[dict] = []
    if audit_path.exists():
        try:
            with audit_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        nudges.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            nudges = []

    if nudges:
        lines.append(f"*Last nudges (newest 5 of {len(nudges)}):*")
        for rec in nudges[-5:][::-1]:
            ts = (rec.get("applied_at") or "")[:19].replace("T", " ")
            param = rec.get("param", "?")
            old = rec.get("old_value", "?")
            new = rec.get("new_value", "?")
            src = rec.get("source", "?")
            lines.append(f"  `{ts}` {param}: {old} → {new} ({src})")
        lines.append("")
    else:
        lines.append("*Last nudges:* none yet")
        lines.append("")

    # L2 state + pending proposal count
    last_run = reflect_state.get("last_run_at") if reflect_state else None
    if last_run:
        lines.append(f"*L2 last run:* {last_run[:19].replace('T', ' ')} UTC")
    else:
        lines.append("*L2 last run:* never")

    from daemon.iterators.oil_botpattern_reflect import load_proposals
    all_proposals = load_proposals(OIL_BOTPATTERN_PROPOSALS_JSONL)
    pending = [p for p in all_proposals if p.get("status") == "pending"]
    lines.append(f"*Pending proposals:* {len(pending)}  (total {len(all_proposals)})")
    if pending:
        lines.append("  Run `/selftuneproposals` to review.")

    lines.append("")
    lines.append(
        "_L1 nudges param values within bounds. L2 proposes structural "
        "changes — approve with_ `/selftuneapprove <id>` _or_ "
        "`/selftunereject <id>`."
    )

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def cmd_selftuneproposals(token: str, chat_id: str, args: str) -> None:
    """List pending structural proposals from L2 reflect loop.

    Deterministic — reads oil_botpattern_proposals.jsonl directly.
    Optional arg: integer limit (default 10, max 25).
    """
    from daemon.iterators.oil_botpattern_reflect import load_proposals

    limit = 10
    if args.strip():
        try:
            limit = max(1, min(25, int(args.strip())))
        except ValueError:
            pass

    all_proposals = load_proposals(OIL_BOTPATTERN_PROPOSALS_JSONL)
    pending = [p for p in all_proposals if p.get("status") == "pending"]

    if not pending:
        tg_send(token, chat_id,
                "🎛️ No pending self-tune proposals. "
                "L2 reflect loop has not found structural changes to surface.",
                markdown=True)
        return

    # Show newest first
    shown = pending[-limit:][::-1]

    lines = [f"🎛️ *Pending self-tune proposals* (showing {len(shown)} of {len(pending)})", ""]
    for p in shown:
        pid = p.get("id", "?")
        ptype = p.get("type", "?")
        created = (p.get("created_at") or "")[:19].replace("T", " ")
        desc = p.get("description", "")
        action = p.get("proposed_action", {}) or {}
        action_kind = action.get("kind", "?")
        action_path = action.get("path", "")
        old = action.get("old_value")
        new = action.get("new_value")
        notes = action.get("notes", "")

        lines.append(f"*#{pid}* `{ptype}` — {created} UTC")
        lines.append(f"  {desc}")
        if action_kind == "config_change":
            lines.append(f"  Action: `{action_path}` {old} → {new}")
        else:
            lines.append(f"  Action: {action_kind}" + (f" — {notes}" if notes else ""))
        lines.append(f"  `/selftuneapprove {pid}`  `/selftunereject {pid}`")
        lines.append("")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def _apply_proposal_action(proposal: dict) -> tuple[bool, str]:
    """Execute a proposed_action on its target file atomically.

    Returns (ok, message). Never raises — errors come back as ok=False.
    Only `kind="config_change"` is auto-applicable; `kind="advisory"`
    returns ok=True with a reminder that no file was changed.
    """
    import json
    import os
    from pathlib import Path

    action = proposal.get("proposed_action", {}) or {}
    kind = action.get("kind")
    if kind == "advisory":
        return (True, "advisory only — no file change")
    if kind != "config_change":
        return (False, f"unknown action kind {kind!r}")

    target = action.get("target", "")
    path_key = action.get("path", "")
    new_value = action.get("new_value")
    if not target or not path_key:
        return (False, "missing target or path in proposed_action")
    if new_value is None:
        return (False, "no new_value in proposed_action")

    target_path = Path(target)
    if not target_path.exists():
        return (False, f"target file missing: {target}")

    try:
        cfg = json.loads(target_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return (False, f"cannot read {target}: {e}")

    # Only top-level keys supported in L2 v1.
    if path_key not in cfg:
        return (False, f"key {path_key!r} not present in {target}")

    cfg[path_key] = new_value

    try:
        tmp = target_path.with_suffix(target_path.suffix + ".tmp")
        tmp.write_text(json.dumps(cfg, indent=2) + "\n")
        os.replace(tmp, target_path)
    except OSError as e:
        return (False, f"write failed: {e}")

    # Append to audit log
    try:
        audit_path = Path(OIL_BOTPATTERN_TUNE_AUDIT_JSONL)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        audit_path.open("a").write(json.dumps({
            "applied_at": datetime.now(tz=timezone.utc).isoformat(),
            "param": path_key,
            "old_value": action.get("old_value"),
            "new_value": new_value,
            "reason": f"proposal #{proposal.get('id')} approved",
            "stats_sample_size": 0,
            "stats_snapshot": proposal.get("evidence", {}),
            "trade_ids_considered": [],
            "source": "reflect_approved",
        }) + "\n")
    except OSError:
        # Non-fatal — config already updated.
        pass

    return (True, f"applied {path_key}: {action.get('old_value')} → {new_value}")


def cmd_selftuneapprove(token: str, chat_id: str, args: str) -> None:
    """Approve a structural proposal and apply its action to the target file.

    Usage: /selftuneapprove <id>
    Deterministic — no AI involvement.
    """
    import json
    from datetime import datetime, timezone

    from daemon.iterators.oil_botpattern_reflect import (
        find_proposal,
        load_proposals,
        write_proposals_atomic,
    )

    arg = (args or "").strip()
    if not arg:
        tg_send(token, chat_id, "Usage: `/selftuneapprove <id>`", markdown=True)
        return
    try:
        proposal_id = int(arg)
    except ValueError:
        tg_send(token, chat_id, f"Bad id: `{arg}`. Integer expected.", markdown=True)
        return

    proposals = load_proposals(OIL_BOTPATTERN_PROPOSALS_JSONL)
    target = find_proposal(proposals, proposal_id)
    if target is None:
        tg_send(token, chat_id, f"🎛️ Proposal #{proposal_id} not found.", markdown=True)
        return
    if target.get("status") != "pending":
        tg_send(token, chat_id,
                f"🎛️ Proposal #{proposal_id} is {target.get('status')}, not pending.",
                markdown=True)
        return

    ok, msg = _apply_proposal_action(target)
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    target["status"] = "approved" if ok else "pending"
    target["reviewed_at"] = now_iso
    target["reviewed_outcome"] = "applied" if ok else f"error: {msg}"

    try:
        write_proposals_atomic(OIL_BOTPATTERN_PROPOSALS_JSONL, proposals)
    except OSError as e:
        tg_send(token, chat_id,
                f"🎛️ Applied action but failed to update proposals file: {e}",
                markdown=True)
        return

    if ok:
        tg_send(token, chat_id,
                f"✅ Proposal #{proposal_id} approved and applied.\n`{msg}`",
                markdown=True)
    else:
        tg_send(token, chat_id,
                f"⚠️ Proposal #{proposal_id} could NOT be auto-applied: {msg}\n"
                f"Status reverted to pending. Review manually.",
                markdown=True)


def cmd_selftunereject(token: str, chat_id: str, args: str) -> None:
    """Reject a structural proposal. No file changes.

    Usage: /selftunereject <id>
    Deterministic.
    """
    from datetime import datetime, timezone

    from daemon.iterators.oil_botpattern_reflect import (
        find_proposal,
        load_proposals,
        write_proposals_atomic,
    )

    arg = (args or "").strip()
    if not arg:
        tg_send(token, chat_id, "Usage: `/selftunereject <id>`", markdown=True)
        return
    try:
        proposal_id = int(arg)
    except ValueError:
        tg_send(token, chat_id, f"Bad id: `{arg}`. Integer expected.", markdown=True)
        return

    proposals = load_proposals(OIL_BOTPATTERN_PROPOSALS_JSONL)
    target = find_proposal(proposals, proposal_id)
    if target is None:
        tg_send(token, chat_id, f"🎛️ Proposal #{proposal_id} not found.", markdown=True)
        return
    if target.get("status") != "pending":
        tg_send(token, chat_id,
                f"🎛️ Proposal #{proposal_id} is {target.get('status')}, not pending.",
                markdown=True)
        return

    target["status"] = "rejected"
    target["reviewed_at"] = datetime.now(tz=timezone.utc).isoformat()
    target["reviewed_outcome"] = "rejected"

    try:
        write_proposals_atomic(OIL_BOTPATTERN_PROPOSALS_JSONL, proposals)
    except OSError as e:
        tg_send(token, chat_id,
                f"🎛️ Failed to update proposals file: {e}",
                markdown=True)
        return

    tg_send(token, chat_id,
            f"❌ Proposal #{proposal_id} rejected.",
            markdown=True)


# ── Lab Engine commands ────────────────────────────────────────────────

def cmd_lab(token: str, chat_id: str, args: str) -> None:
    """Lab Engine — strategy development pipeline.

    Usage:
      /lab              — show experiment status summary
      /lab discover <m> — profile market and create candidates
      /lab promote <id> — promote graduated experiment
    Deterministic. Zero AI calls.
    """
    from engines.learning.lab_engine import LabEngine
    lab = LabEngine()

    arg = (args or "").strip()
    if not arg or arg == "status":
        if not lab.enabled:
            tg_send(token, chat_id, "🧪 Lab Engine is DISABLED.\nEnable: `data/config/lab.json` → `enabled: true`", markdown=True)
            return
        info = lab.get_status()
        lines = [f"🧪 *Lab Engine* — {info['total']} experiments\n"]
        for status_name, experiments in info.get("by_status", {}).items():
            lines.append(f"*{status_name.upper()}*")
            for e in experiments:
                metrics = e.get("metrics", {})
                sharpe = metrics.get("sharpe", 0) if metrics else 0
                lines.append(f"  `{e['id']}`: {e['strategy']} on {e['market']} (sharpe={sharpe:.2f})")
        tg_send(token, chat_id, "\n".join(lines), markdown=True)
        return

    parts = arg.split(maxsplit=1)
    sub = parts[0].lower()
    sub_arg = parts[1].strip() if len(parts) > 1 else ""

    if sub == "discover" and sub_arg:
        created = lab.discover(sub_arg.upper())
        if created:
            lines = [f"🧪 Created {len(created)} experiments for {sub_arg.upper()}:"]
            for eid in created:
                exp = lab.get_experiment(eid)
                if exp:
                    lines.append(f"  `{exp.id}`: {exp.strategy}")
            tg_send(token, chat_id, "\n".join(lines), markdown=True)
        else:
            tg_send(token, chat_id, f"No new experiments for {sub_arg.upper()}")
    elif sub == "promote" and sub_arg:
        if lab.promote_to_production(sub_arg):
            tg_send(token, chat_id, f"✅ `{sub_arg}` promoted to PRODUCTION (params frozen)", markdown=True)
        else:
            tg_send(token, chat_id, f"Cannot promote `{sub_arg}` — must be 'graduated'", markdown=True)
    elif sub == "retire" and sub_arg:
        if lab.retire_experiment(sub_arg):
            tg_send(token, chat_id, f"🗑 `{sub_arg}` retired", markdown=True)
        else:
            tg_send(token, chat_id, f"Experiment `{sub_arg}` not found", markdown=True)
    else:
        tg_send(token, chat_id,
                "Usage:\n`/lab` — status\n`/lab discover <market>`\n`/lab promote <id>`\n`/lab retire <id>`",
                markdown=True)


def cmd_architect(token: str, chat_id: str, args: str) -> None:
    """Architect Engine — mechanical self-improvement.

    Usage:
      /architect            — show findings + proposal counts
      /architect detect     — run detection now (zero AI, zero cost)
      /architect proposals  — list pending proposals
      /architect approve <id> — approve a proposal
      /architect reject <id>  — reject a proposal
    Deterministic. Zero AI calls. Zero API costs.
    """
    from engines.learning.architect_engine import ArchitectEngine
    arch = ArchitectEngine()

    arg = (args or "").strip()
    if not arg or arg == "status":
        info = arch.get_status()
        lines = [f"🏗 *Architect Engine* — {'ENABLED' if info['enabled'] else 'DISABLED'}\n"]
        lines.append(f"Findings: {info['findings']}")
        for sev, count in info["findings_by_severity"].items():
            if count:
                lines.append(f"  {sev}: {count}")
        lines.append(f"\nProposals: {info['proposals_pending']} pending, {info['proposals_approved']} approved, {info['proposals_applied']} applied")
        tg_send(token, chat_id, "\n".join(lines), markdown=True)
        return

    parts = arg.split(maxsplit=1)
    sub = parts[0].lower()
    sub_arg = parts[1].strip() if len(parts) > 1 else ""

    if sub == "detect":
        if not arch.enabled:
            tg_send(token, chat_id, "🏗 Architect is DISABLED. Enable in `data/config/architect.json`", markdown=True)
            return
        findings = arch.detect()
        if findings:
            proposals = arch.hypothesize(findings)
            lines = [f"🔍 {len(findings)} new patterns detected:"]
            for f in findings:
                lines.append(f"  [{f.severity}] {f.description}")
            if proposals:
                lines.append(f"\n📋 {len(proposals)} proposals generated:")
                for p in proposals:
                    lines.append(f"  `{p.id}`: {p.title}")
            tg_send(token, chat_id, "\n".join(lines), markdown=True)
        else:
            tg_send(token, chat_id, "No new patterns detected.")

    elif sub == "proposals":
        pending = arch.get_pending_proposals()
        if not pending:
            tg_send(token, chat_id, "No pending proposals.")
            return
        lines = [f"📋 {len(pending)} pending proposals:\n"]
        for p in pending:
            lines.append(f"`{p.id}`: *{p.title}*")
            lines.append(f"  {p.description[:120]}")
            lines.append(f"  Impact: {p.expected_impact}")
            lines.append("")
        tg_send(token, chat_id, "\n".join(lines), markdown=True)

    elif sub == "approve" and sub_arg:
        if arch.approve(sub_arg):
            tg_send(token, chat_id, f"✅ Proposal `{sub_arg}` approved", markdown=True)
        else:
            tg_send(token, chat_id, f"Proposal `{sub_arg}` not found or not pending", markdown=True)

    elif sub == "reject" and sub_arg:
        if arch.reject(sub_arg):
            tg_send(token, chat_id, f"❌ Proposal `{sub_arg}` rejected", markdown=True)
        else:
            tg_send(token, chat_id, f"Proposal `{sub_arg}` not found or not pending", markdown=True)

    else:
        tg_send(token, chat_id,
                "Usage:\n`/architect` — status\n`/architect detect`\n`/architect proposals`\n"
                "`/architect approve <id>`\n`/architect reject <id>`",
                markdown=True)


# ── Lesson commands moved to cli/telegram_commands/lessons.py ─────────
# First wedge of the telegram_bot.py monolith split (2026-04-09).
# The four cmd_lessons / cmd_lesson / cmd_lessonauthorai / cmd_lessonsearch
# handlers now live in cli/telegram_commands/lessons.py and are imported
# below so the HANDLERS dict references resolve correctly.
from cli.telegram_commands.lessons import (  # noqa: E402
    cmd_lesson,
    cmd_lessonauthorai,
    cmd_lessons,
    cmd_lessonsearch,
)
from cli.telegram_commands.brutal_review import cmd_brutalreviewai  # noqa: E402
from cli.telegram_commands.entry_critic import cmd_critique  # noqa: E402
from cli.telegram_commands.portfolio import cmd_pnl, cmd_position  # noqa: E402
from cli.telegram_commands.action_queue import cmd_nudge  # noqa: E402
from cli.telegram_commands.chat_history import cmd_chathistory  # noqa: E402
from cli.telegram_commands.patternlib import (  # noqa: E402
    cmd_patterncatalog,
    cmd_patternpromote,
    cmd_patternreject,
)
from cli.telegram_commands.shadow import cmd_shadoweval  # noqa: E402
from cli.telegram_commands.sim import cmd_sim  # noqa: E402
from cli.telegram_commands.readiness import cmd_readiness  # noqa: E402
from cli.telegram_commands.activate import cmd_activate  # noqa: E402
from cli.telegram_commands.adaptlog import cmd_adaptlog  # noqa: E402


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
        "`/pnl` — profit & loss breakdown by market\n"
        "`/orders` — open orders snapshot\n"
        "`/menu` — interactive button terminal (no typing)\n"
        "\n🎯 *Trade Actions (with approval)*\n"
        "`/close BRENTOIL` — close a position. Buttons confirm.\n"
        "`/sl BRENTOIL 65.40` — set stop-loss. Buttons confirm.\n"
        "`/tp BRENTOIL 72.00` — set take-profit. Buttons confirm.\n"
        "No trade executes without your tap.\n"
        "\n🧠 *Conviction & Intelligence*\n"
        "`/thesis` — every thesis file with age + conviction + direction. "
        "Red icon = clamped (>72h stale). Yellow = warning. Green = fresh.\n"
        "`/signals` — Pulse (capital inflow) + Radar (multi-timeframe setups). "
        "Pulse scans every 2 min, Radar every 5 min.\n"
        "`/powerlaw` — BTC power law model state (used by vault rebalancer).\n"
        "\n📈 *Charts*\n"
        "`/chart BRENTOIL 72` — generic dispatcher: any market, any hours\n"
        "`/chartoil 72` — 72h oil shortcut\n"
        "Shortcuts: `/chartbtc`, `/chartgold`, `/chartwti`\n"
        "\n📄 *Brief PDFs*\n"
        "`/brief` — mechanical 1-page PDF (fixed code, no AI). Portfolio, "
        "positions, technicals, funding, chart.\n"
        "`/briefai` — same brief plus the thesis line and catalyst calendar "
        "(those are AI/research-seeded, hence the `ai` suffix).\n"
        "\n📰 *News & Catalysts*\n"
        "`/news` — shows recent catalysts surfaced by the news ingest iterator\n"
        "`/catalysts` — shows upcoming scheduled catalysts from news ingest + iCal sources\n"
        "`/supply` — aggregated view of physical oil supply offline right now\n"
        "`/disruptions` — list top 10 active supply disruptions by confidence*volume\n"
        "`/disrupt refinery Volgograd 200000 bpd active 2026-04-08 \"drone strike\"` — manual entry\n"
        "`/disrupt-update abc12345 status=restored` — update an existing entry (history preserved)\n"
        "`/heatmap [BRENTOIL]` — stop/liquidity heatmap (sub-system 3): top bid/ask walls + recent cascades\n"
        "`/botpatterns [BRENTOIL] [10]` — recent classifications from sub-system 4 (bot-driven vs informed)\n"
        "`/oilbot` — sub-system 5 strategy: kill-switch status, open positions, drawdown brakes\n"
        "`/oilbotjournal [20]` — per-decision audit log (which gates passed/failed, sizing rung, edge)\n"
        "`/oilbotreviewai [50]` — AI summary of recent strategy decisions (the `ai` suffix is required)\n"
        "`/selftune` — sub-system 6 self-tune harness (L1 auto-tune + L2 reflect) state\n"
        "`/selftuneproposals` — list L2 structural proposals pending human review\n"
        "`/selftuneapprove <id>` — approve + atomically apply a proposal's config change\n"
        "`/selftunereject <id>` — reject a proposal (no file change)\n"
        "`/patterncatalog` — sub-system 6 L3 bot-pattern library (live catalog + pending candidates)\n"
        "`/patternpromote <id>` — promote a pending pattern candidate into the live catalog\n"
        "`/patternreject <id>` — reject a pending pattern candidate (catalog untouched)\n"
        "`/shadoweval` — sub-system 6 L4 counterfactual shadow-eval summary\n"
        "`/shadoweval 42` — detailed shadow eval for proposal #42\n"
        "`/sim` — shadow (paper) account for sub-system 5 — balance, open positions, recent trades. Lit up when `decisions_only=true`.\n"
        "`/readiness` — activation preflight for sub-system 5: catalyst/supply/heatmap/classifier/thesis/risk-caps/brakes freshness + master-switch state. Run before flipping shadow → live.\n"
        "`/activate` — guided activation walkthrough. Shows current rung + readiness + next-step hint.\n"
        "`/activate next` — preview the next-rung advance (what patch will be applied).\n"
        "`/activate confirm` — execute the pending advance (within 10 minutes).\n"
        "`/activate back` — soft rollback one rung.\n"
        "`/activate rollback` — hard rollback: immediately set enabled=false.\n"
        "`/adaptlog` — last 10 adaptive evaluator decisions with action, reason, and progress/time/velocity metrics.\n"
        "`/adaptlog 25 exits live BRENTOIL` — filter: last 25 EXIT actions in live mode for BRENTOIL (args combine freely).\n"
        "\n📓 *Trade Lessons*\n"
        "`/lessons` — recent trade post-mortems the agent wrote after each close\n"
        "`/lesson 42` — full verbatim body of lesson #42\n"
        "`/lesson approve 42` — boost its ranking in future prompt injection\n"
        "`/lesson reject 42` — exclude it (anti-pattern; stays searchable)\n"
        "`/lessonsearch weekend wick` — BM25 keyword search over summaries/bodies/tags\n"
        "`/lessonauthorai` — manually trigger AI authoring of pending candidates "
        "(also runs automatically every dream cycle on the same 24h+3 trigger)\n"
        "`/brutalreviewai` — full deep audit of codebase + trading state. "
        "Brutally honest, file-and-line-cited, ranked action list. Run weekly "
        "or after major changes. Output lands at `data/reviews/brutal_review_<date>.md`.\n"
        "`/critique [N|symbol]` — recent entry critiques. The entry_critic "
        "iterator auto-fires a critique on every new position (sizing / direction "
        "/ catalyst timing / liquidity / funding axes, plus suggestions and "
        "lesson recall). This command is the manual lookup for past entries.\n"
        "\n💬 *Chat History — Historical Oracle*\n"
        "Every Telegram message and assistant reply is appended to "
        "`data/daemon/chat_history.jsonl` forever. The writer is append-only; "
        "there is no rotation and no deletion. Going forward, each row also "
        "carries a `market_context` snapshot (equity, positions, prices) so "
        "future analysis can correlate each message with market state at the "
        "time it was sent — priceless training signal as the bot matures.\n"
        "`/chathistory` (or `/ch`) — last 10 entries with timestamps + roles\n"
        "`/chathistory 25` — last N entries (max 50)\n"
        "`/chathistory search oil ceasefire` — substring search across all rows\n"
        "`/chathistory stats` — count, date range, role breakdown, "
        "market-context coverage %, sibling `.bak*` backups\n"
        "\n🪧 *Action Queue (things Chris should do)*\n"
        "`/nudge` — list every operator ritual (restore drill, weekly brutal "
        "review, thesis refresh, lesson queue, backup health, feedback triage). "
        "The action_queue daemon iterator evaluates this list once a day and "
        "posts a Telegram nudge if anything is overdue.\n"
        "`/nudge overdue` — only show items that are past due.\n"
        "`/nudge done <id>` — mark a ritual done now (resets the cadence window).\n"
        "`/nudge add <kind> <days> <desc>` — add a custom time-based reminder.\n"
        "`/nudge remove <id>` — drop a custom item.\n"
        "The agent sees the top recent lessons automatically in its system prompt; "
        "use these commands to browse and curate from Telegram.\n"
        "\n*Rule:* slash commands are fixed code. Anything that depends on AI "
        "carries an `ai` suffix. Natural-language messages always go to the AI.\n"
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
        "\n🏦 *Vault (BTC power-law rebalancer)*\n"
        "`/rebalancer` — status, start, stop the 1h rebalance daemon\n"
        "`/rebalance` — force an immediate rebalance (ignores threshold)\n"
        "\n🔧 *System*\n"
        "`/restart` — restart all services (daemon, bot, heartbeat)\n"
        "`/models` — switch AI model (10 free, 8 paid)\n"
        "`/health` — check what's running (bot, heartbeat, daemon)\n"
        "`/diag` — tool calls, errors, authority status\n"
        "`/memory` — agent learnings and notes\n"
        "\n🛢️ *Watchlist Management*\n"
        "`/addmarket crude` — search and add a new market\n"
        "`/removemarket xyz:CL` — remove a market\n"
        "\n📝 *Tracking (append-only historical log)*\n"
        "`/bug` — file a bug.\n"
        "`/todo <text>` — add a todo. `/todo list|search|done|dismiss|show` for management.\n"
        "`/feedback <text>` — leave feedback. `/feedback list|search|resolve|dismiss|tag|show` for management.\n"
        "All three feed Claude Code next session. Rows are event-sourced — never rewritten in place.\n"
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
        from agent.tools import pending_count
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
        from agent.context_harness import build_multi_market_context
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


# _lock_approval_message, _handle_tool_approval → Moved to cli/telegram_approval.py


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

    states = ThesisState.load_all(DEFAULT_THESIS_DIR)
    if not states:
        tg_send(token, chat_id, "*Thesis States*\n\nNo thesis files found.")
        return

    lines = ["*Thesis States*", ""]
    for market, state in sorted(states.items()):
        age_h = state.age_hours
        raw_conv = state.conviction
        effective = state.effective_conviction()
        clamp_note = ""
        if state.is_very_stale:
            clamp_note = " ⚠️ defensive"
        elif state.is_stale:
            clamp_note = " ⚠️ tapering"

        if state.is_very_stale:
            age_icon = "🔴"
        elif state.is_stale:
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
# Interactive Menu System → Moved to cli/telegram_menu.py
# Approval / pending-input handlers → Moved to cli/telegram_approval.py


# _cached_positions, _btn → Moved to cli/telegram_menu.py



# _build_main_menu, _build_position_detail, _build_watchlist_menu,
# _build_trade_menu, _build_trade_side_menu, _build_account_menu,
# _build_tools_menu, _menu_dispatch, _handle_menu_callback
# → Moved to cli/telegram_menu.py

# _handle_trade_size_prompt, _find_position, _handle_close_position,
# _handle_sl_prompt, _handle_tp_prompt, _handle_pending_input
# → Moved to cli/telegram_approval.py

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
        size = float(pos.get("size", pos.get("szi", 0)))
        from agent.tools import store_pending
        args_dict = {
            "coin": pos.get("coin", resolved),
            "trigger_price": price,
            "side": "sell" if size > 0 else "buy",
            "size": abs(size),
            "dex": pos.get("dex", pos.get("_dex", "")),
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
        size = float(pos.get("size", pos.get("szi", 0)))
        from agent.tools import store_pending
        args_dict = {
            "coin": pos.get("coin", resolved),
            "trigger_price": price,
            "side": "sell" if size > 0 else "buy",
            "size": abs(size),
            "dex": pos.get("dex", pos.get("_dex", "")),
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

# Handlers intentionally excluded from the Telegram menu/help/guide.
# Guardian's cartographer reads this constant and drift.detect_telegram_gaps
# skips every handler listed here, preventing them from surfacing as P1s.
# Add a handler here when it's an admin/meta/power-user command that should
# NOT appear in user-facing surfaces but must still be routable via HANDLERS.
_GUARDIAN_HIDDEN_HANDLERS = frozenset({
    "cmd_feedback_resolve",  # admin-only: mark feedback items resolved
    "cmd_commands",          # power-user meta: category-based command dump
})

# Handlers intentionally excluded from the native Telegram command menu
# (setMyCommands) but still documented in cmd_help / cmd_guide. Use this
# for rarely-invoked operations that would clutter the menu without being
# worth a top-level slot. Guardian treats "missing from menu" as OK for
# these handlers; other registration checks still apply.
_GUARDIAN_MENU_EXEMPT = frozenset({
    "cmd_addmarket",     # watchlist mgmt — help-only, typed rarely
    "cmd_removemarket",  # watchlist mgmt — help-only, typed rarely
})

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
    "/feedback_resolve": cmd_feedback_resolve,
    "/fbr": cmd_feedback_resolve,
    "/memory": cmd_memory,
    "/mem": cmd_memory,
    "/diag": cmd_diag,
    "/watchlist": cmd_watchlist,
    "/w": cmd_watchlist,
    "/powerlaw": cmd_powerlaw,
    "/rebalancer": cmd_rebalancer,
    "/rebalance": cmd_rebalance,
    "/brief": cmd_brief,
    "/b": cmd_brief,
    "/briefai": cmd_briefai,
    "/bai": cmd_briefai,
    "/restart": cmd_restart,
    "/signals": cmd_signals,
    "/sig": cmd_signals,
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
    "/news": cmd_news,
    "/catalysts": cmd_catalysts,
    "/supply": cmd_supply,
    "/disruptions": cmd_disruptions,
    "/disrupt": cmd_disrupt,
    "/disrupt-update": cmd_disrupt_update,
    "/heatmap": cmd_heatmap,
    "/botpatterns": cmd_botpatterns,
    "/oilbot": cmd_oilbot,
    "/oilbotjournal": cmd_oilbotjournal,
    "/oilbotreviewai": cmd_oilbotreviewai,
    "/selftune": cmd_selftune,
    "/selftuneproposals": cmd_selftuneproposals,
    "/selftuneapprove": cmd_selftuneapprove,
    "/selftunereject": cmd_selftunereject,
    "/patterncatalog": cmd_patterncatalog,
    "/patternpromote": cmd_patternpromote,
    "/patternreject": cmd_patternreject,
    "/shadoweval": cmd_shadoweval,
    "/sim": cmd_sim,
    "/readiness": cmd_readiness,
    "/activate": cmd_activate,
    "/adaptlog": cmd_adaptlog,
    "/lessons": cmd_lessons,
    "/lesson": cmd_lesson,
    "/lessonsearch": cmd_lessonsearch,
    "/lessonauthorai": cmd_lessonauthorai,
    "/brutalreviewai": cmd_brutalreviewai,
    "/critique": cmd_critique,
    "/nudge": cmd_nudge,
    "/chathistory": cmd_chathistory,
    "/ch": cmd_chathistory,
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
    "brief": cmd_brief,
    "b": cmd_brief,
    "briefai": cmd_briefai,
    "bai": cmd_briefai,
    "restart": cmd_restart,
    "restartall": cmd_restartall,
    "signals": cmd_signals,
    "sig": cmd_signals,
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
    "news": cmd_news,
    "catalysts": cmd_catalysts,
    "supply": cmd_supply,
    "disruptions": cmd_disruptions,
    "disrupt": cmd_disrupt,
    "heatmap": cmd_heatmap,
    "botpatterns": cmd_botpatterns,
    "oilbot": cmd_oilbot,
    "oilbotjournal": cmd_oilbotjournal,
    "oilbotreviewai": cmd_oilbotreviewai,
    "selftune": cmd_selftune,
    "selftuneproposals": cmd_selftuneproposals,
    "selftuneapprove": cmd_selftuneapprove,
    "selftunereject": cmd_selftunereject,
    "/lab": cmd_lab,
    "lab": cmd_lab,
    "/architect": cmd_architect,
    "architect": cmd_architect,
    "patterncatalog": cmd_patterncatalog,
    "patternpromote": cmd_patternpromote,
    "patternreject": cmd_patternreject,
    "shadoweval": cmd_shadoweval,
    "sim": cmd_sim,
    "readiness": cmd_readiness,
    "activate": cmd_activate,
    "adaptlog": cmd_adaptlog,
    "disrupt-update": cmd_disrupt_update,
    "lessons": cmd_lessons,
    "lesson": cmd_lesson,
    "lessonsearch": cmd_lessonsearch,
    "lessonauthorai": cmd_lessonauthorai,
    "brutalreviewai": cmd_brutalreviewai,
    "critique": cmd_critique,
    "chathistory": cmd_chathistory,
    "ch": cmd_chathistory,
    "nudge": cmd_nudge,
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
        # Conviction & Intelligence
        {"command": "thesis", "description": "Show all thesis states with conviction + age"},
        {"command": "signals", "description": "Recent Pulse + Radar signals"},
        # Charts
        {"command": "chart", "description": "Generic chart dispatcher — /chart <market> [hours]"},
        {"command": "chartoil", "description": "Oil price chart (add hours)"},
        {"command": "chartbtc", "description": "BTC price chart"},
        {"command": "chartgold", "description": "Gold price chart"},
        {"command": "watchlist", "description": "All markets + prices"},
        {"command": "brief", "description": "Mechanical brief PDF (no AI content)"},
        {"command": "briefai", "description": "AI brief PDF — adds thesis + catalysts"},
        {"command": "news", "description": "Show last 10 catalysts by severity"},
        {"command": "catalysts", "description": "Show upcoming catalysts in next 7 days"},
        {"command": "supply", "description": "Show current supply disruption state"},
        {"command": "disruptions", "description": "List top 10 active supply disruptions"},
        {"command": "disrupt", "description": "Manually log a supply disruption"},
        {"command": "disrupt-update", "description": "Update an existing supply disruption"},
        {"command": "heatmap", "description": "Show stop/liquidity heatmap (sub-system 3)"},
        {"command": "botpatterns", "description": "Show recent bot-pattern classifications (sub-system 4)"},
        {"command": "oilbot", "description": "oil_botpattern strategy state (sub-system 5)"},
        {"command": "oilbotjournal", "description": "Recent oil_botpattern decision records"},
        {"command": "oilbotreviewai", "description": "AI review of oil_botpattern strategy"},
        {"command": "lab", "description": "Lab — strategy development pipeline"},
        {"command": "architect", "description": "Architect — mechanical self-improvement"},
        {"command": "selftune", "description": "Self-tune harness state (sub-system 6)"},
        {"command": "selftuneproposals", "description": "List pending L2 structural proposals"},
        {"command": "selftuneapprove", "description": "/selftuneapprove <id> — approve + apply a proposal"},
        {"command": "selftunereject", "description": "/selftunereject <id> — reject a proposal"},
        {"command": "patterncatalog", "description": "Bot-pattern library state (sub-system 6 L3)"},
        {"command": "patternpromote", "description": "/patternpromote <id> — promote a candidate into the live catalog"},
        {"command": "patternreject", "description": "/patternreject <id> — reject a candidate (catalog untouched)"},
        {"command": "shadoweval", "description": "Shadow counterfactual eval results (sub-system 6 L4)"},
        {"command": "sim", "description": "Shadow (paper) account state — balance, open positions, recent trades"},
        {"command": "readiness", "description": "Sub-system 5 activation preflight checklist"},
        {"command": "activate", "description": "Guided sub-system 5 activation walkthrough (rung advances + rollback)"},
        {"command": "adaptlog", "description": "Query the adaptive evaluator decision log (filters: exits/trails/live/shadow/SYM)"},
        {"command": "lessons", "description": "Recent trade post-mortems from the lesson corpus"},
        {"command": "lesson", "description": "View/approve/reject a lesson by id"},
        {"command": "lessonsearch", "description": "BM25 search over the lesson corpus"},
        {"command": "lessonauthorai", "description": "Author pending lesson candidates via AI (dream cycle also runs this)"},
        {"command": "brutalreviewai", "description": "Run the Brutal Review Loop — full deep audit (AI)"},
        {"command": "critique", "description": "Show recent entry critiques (deterministic)"},
        {"command": "chathistory", "description": "Browse the historical-oracle chat log (last N / search / stats)"},
        {"command": "nudge", "description": "Things Chris should do — restore drill, brutal review, lesson queue"},
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
        {"command": "restart", "description": "Restart all services (daemon + bot + heartbeat)"},
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

    # Audit F9: log chat history continuity at startup so the operator can
    # confirm prior conversation context is intact across restarts. The bot
    # is already stateless across restarts (every message reloads history
    # from disk via _load_chat_history), but this gives explicit visibility.
    try:
        history_path = Path("data/daemon/chat_history.jsonl")
        if history_path.exists():
            lines = [l for l in history_path.read_text().splitlines() if l.strip()]
            if lines:
                last_entry = json.loads(lines[-1])
                last_ts = last_entry.get("ts", 0)
                age_min = (time.time() - last_ts) / 60 if last_ts else -1
                last_role = last_entry.get("role", "?")
                log.info(
                    "Chat history continuity: %d entries on disk, last=%s %.1fm ago",
                    len(lines), last_role, age_min,
                )
            else:
                log.info("Chat history continuity: file present but empty")
        else:
            log.info("Chat history continuity: no prior history (first run)")
    except Exception as e:
        log.warning("Failed to log chat history continuity at startup: %s", e)

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
                    log.error("Command %s failed: %s", cmd_key, e, exc_info=True)
                    if _diag:
                        _diag.log_error("telegram_cmd", f"{cmd_key} failed: {e}")
                    tg_send(token, reply_chat_id,
                            f"`{cmd_key}` failed: {type(e).__name__}\n"
                            f"_{e}_\n\n"
                            f"Try again or /help for commands.")
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
                from agent.tools import cleanup_expired_pending
                cleanup_expired_pending()
            except Exception:
                pass

        # Alert user after sustained polling failure
        if _tg_api._poll_fail_count == 5:
            try:
                tg_send(token, chat_id, "Telegram API unreachable (5 consecutive failures). Retrying with backoff.")
            except Exception:
                pass

        if running:
            time.sleep(_poll_backoff_seconds())

    # Cleanup
    PID_FILE.unlink(missing_ok=True)
    log.info("Telegram bot stopped.")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    run()
