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

def tg_send(token: str, chat_id: str, text: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        return r.json().get("ok", False)
    except Exception as e:
        log.warning("Send failed: %s", e)
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
    lines = [f"Portfolio ({datetime.now(timezone.utc).strftime('%a %H:%M UTC')})", ""]

    # Spot
    spot = _hl_post({"type": "spotClearinghouseState", "user": MAIN_ADDR})
    for b in spot.get("balances", []):
        total = float(b.get("total", 0))
        if total > 0.01:
            coin = b["coin"]
            lines.append(f"  {coin}: ${total:,.2f}" if coin == "USDC" else f"  {coin}: {total:.4f}")

    # ALL perp positions (native + xyz clearinghouses)
    positions = _get_all_positions(MAIN_ADDR)
    if positions:
        lines.append("\nPOSITIONS:")
        for pos in positions:
            coin = pos.get('coin', '?')
            size = pos.get('szi', '0')
            entry = pos.get('entryPx', '0')
            upnl = pos.get('unrealizedPnl', '0')
            lev = pos.get('leverage', {})
            liq = pos.get('liquidationPx', 'N/A')
            lev_val = lev.get('value', '?') if isinstance(lev, dict) else lev
            lines.append(f"  {coin}: {size} @ ${entry}")
            lines.append(f"    uPnL: ${upnl} | {lev_val}x | liq: ${liq}")

    # Account values
    values = _get_account_values(MAIN_ADDR)
    total_perps = values['native'] + values['xyz']
    if total_perps > 0:
        lines.append(f"\nPerps equity: ${total_perps:,.2f}")

    # ALL open orders (native + xyz)
    orders = _get_all_orders(MAIN_ADDR)
    if orders:
        lines.append(f"\nORDERS ({len(orders)}):")
        for o in orders:
            side = "BUY" if o.get("side") == "B" else "SELL"
            lines.append(f"  {side} {o.get('sz')} {o.get('coin')} @ ${o.get('limitPx')}")

    # Vault
    vault = _hl_post({"type": "clearinghouseState", "user": VAULT_ADDR})
    vmarg = vault.get("marginSummary", {})
    vpos = vault.get("assetPositions", [])
    val = float(vmarg.get("accountValue", 0))
    lines.append(f"\nVAULT: ${val:,.2f}")
    for p in vpos:
        pos = p["position"]
        lines.append(f"  {pos['coin']}: {pos['szi']} @ ${pos['entryPx']} | uPnL: ${pos['unrealizedPnl']}")

    lines.append(f"\nLiquidity: {_liquidity_regime()}")
    tg_send(token, chat_id, "\n".join(lines))


def cmd_price(token: str, chat_id: str, _args: str) -> None:
    mids = _hl_post({"type": "allMids"})
    lines = ["Prices:"]

    for coin in APPROVED_MARKETS:
        if coin in mids:
            lines.append(f"  {coin}: ${float(mids[coin]):,.2f}")
        else:
            # xyz markets — use L2 book
            try:
                book = _hl_post({"type": "l2Book", "coin": coin})
                levels = book.get("levels", [])
                if len(levels) >= 2 and levels[0] and levels[1]:
                    mid = (float(levels[0][0]["px"]) + float(levels[1][0]["px"])) / 2
                    lines.append(f"  {coin}: ${mid:,.2f}")
                else:
                    lines.append(f"  {coin}: --")
            except Exception:
                lines.append(f"  {coin}: --")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_orders(token: str, chat_id: str, _args: str) -> None:
    orders = _get_all_orders(MAIN_ADDR)
    if not orders:
        tg_send(token, chat_id, "No open orders.")
        return
    lines = [f"Open Orders ({len(orders)}):"]
    for o in orders:
        side = "BUY" if o.get("side") == "B" else "SELL"
        lines.append(f"  {side} {o.get('sz')} {o.get('coin')} @ ${o.get('limitPx')}")
    tg_send(token, chat_id, "\n".join(lines))


def cmd_pnl(token: str, chat_id: str, _args: str) -> None:
    lines = ["P&L Summary:"]

    # Main — all positions (native + xyz)
    positions = _get_all_positions(MAIN_ADDR)
    values = _get_account_values(MAIN_ADDR)
    main_val = values['native'] + values['xyz']

    for pos in positions:
        lines.append(f"  Main {pos.get('coin')}: uPnL ${pos.get('unrealizedPnl')}")

    # Vault
    vault = _hl_post({"type": "clearinghouseState", "user": VAULT_ADDR})
    vault_val = float(vault.get("marginSummary", {}).get("accountValue", 0))
    for p in vault.get("assetPositions", []):
        pos = p["position"]
        lines.append(f"  Vault {pos['coin']}: uPnL ${pos['unrealizedPnl']}")

    lines.append(f"\nMain equity: ${main_val:,.2f}")
    lines.append(f"Vault equity: ${vault_val:,.2f}")
    lines.append(f"Total: ${main_val + vault_val:,.2f}")

    # Profit lock ledger
    ledger = Path("data/daemon/profit_locks.jsonl")
    if ledger.exists():
        total_locked = sum(
            json.loads(line).get("locked_usd", 0)
            for line in ledger.read_text().splitlines()
            if line.strip()
        )
        lines.append(f"Profits locked: ${total_locked:,.2f}")

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
        # Show available markets
        lines = ["Usage: /chart <market> [hours]", "", "Markets:"]
        for name, coin, aliases, cat in WATCHLIST:
            hint = aliases[0] if aliases else coin
            lines.append(f"  /chart{hint}  — {name}")
        lines.append("\nExamples:")
        lines.append("  /chartoil 72")
        lines.append("  /chartbtc 168")
        lines.append("  /chartgold 48")
        tg_send(token, chat_id, "\n".join(lines))
        return

    coin = resolve_coin(parts[0])
    if not coin:
        tg_send(token, chat_id, f"Unknown market: {parts[0]}\nTry /chart to see available markets.")
        return

    hours = 72
    if len(parts) > 1:
        try:
            hours = int(parts[1])
        except ValueError:
            pass

    # Find display name
    display = next((w[0] for w in WATCHLIST if w[1] == coin), coin)
    tg_send(token, chat_id, f"Generating {display} {hours}h chart...")
    try:
        from cli.chart_engine import ChartEngine
        engine = ChartEngine()
        path = engine.price_action(coin, hours=hours)
        # Send directly to this chat (works in both DMs and groups)
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        with open(path, "rb") as f:
            requests.post(url, data={"chat_id": chat_id, "caption": f"{display} ({coin}) — {hours}h"},
                         files={"photo": f}, timeout=30)
    except Exception as e:
        tg_send(token, chat_id, f"Chart error: {e}")


def cmd_watchlist(token: str, chat_id: str, _args: str) -> None:
    """Show the watchlist with current prices."""
    mids = _hl_post({"type": "allMids"})
    lines = ["Watchlist:", ""]
    by_cat: dict[str, list] = {}
    for name, coin, aliases, cat in WATCHLIST:
        by_cat.setdefault(cat, []).append((name, coin, aliases))

    for cat, markets in by_cat.items():
        lines.append(f"{cat.upper()}")
        for name, coin, aliases in markets:
            price = None
            if coin in mids:
                price = float(mids[coin])
            else:
                try:
                    book = _hl_post({"type": "l2Book", "coin": coin})
                    levels = book.get("levels", [])
                    if len(levels) >= 2 and levels[0] and levels[1]:
                        price = (float(levels[0][0]["px"]) + float(levels[1][0]["px"])) / 2
                except Exception:
                    pass
            px = f"${price:,.2f}" if price else "--"
            hint = aliases[0] if aliases else ""
            lines.append(f"  {name:<12} {px:>12}   /chart{hint}")
        lines.append("")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_powerlaw(token: str, chat_id: str, _args: str) -> None:
    """Generate and send the BTC Power Law chart."""
    tg_send(token, chat_id, "Generating Power Law chart...")
    try:
        from plugins.power_law.charting import generate_powerlaw_png
        import io
        png_bytes = generate_powerlaw_png()
        requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": "BTC Power Law — Floor / Ceiling / Fair Value"},
            files={"photo": ("powerlaw.png", io.BytesIO(png_bytes), "image/png")},
            timeout=30)
    except Exception as e:
        tg_send(token, chat_id, f"Power Law chart error: {e}")


def cmd_help(token: str, chat_id: str, _args: str) -> None:
    tg_send(token, chat_id,
        "*Trading*\n"
        "/market <sym> — technicals + funding (/m oil)\n"
        "/position     — detailed risk report (/pos)\n"
        "/status       — portfolio overview\n"
        "/pnl          — profit & loss\n"
        "\n*Charts & Data*\n"
        "/chart <sym> [hrs] — price chart (/chart oil 72)\n"
        "/watchlist    — markets + prices (/w)\n"
        "/powerlaw     — BTC model\n"
        "/orders       — open orders\n"
        "/price        — quick prices\n"
        "\n*Daemon*\n"
        "/rebalancer start|stop|status\n"
        "/rebalance    — force vault rebalance\n"
        "\n*System*\n"
        "/bug <desc>   — report a bug\n"
        "/feedback <text> — submit feedback (/fb)\n"
        "/diag         — diagnostics\n"
        "/commands     — full CLI list\n"
        "/help         — this message")


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
            tg_send(token, chat_id, "Vault rebalancer is already running.")
            return
        try:
            subprocess.run(
                ["launchctl", "load", "-w",
                 str(Path.home() / "Library/LaunchAgents" / f"{_LAUNCHD_LABEL}.plist")],
                check=True, timeout=10,
            )
            tg_send(token, chat_id, "Vault rebalancer started.")
        except Exception as e:
            tg_send(token, chat_id, f"Start failed: {e}")

    elif action == "stop":
        try:
            subprocess.run(
                ["launchctl", "unload", "-w",
                 str(Path.home() / "Library/LaunchAgents" / f"{_LAUNCHD_LABEL}.plist")],
                check=True, timeout=10,
            )
            tg_send(token, chat_id, "Vault rebalancer stopped.")
        except Exception as e:
            tg_send(token, chat_id, f"Stop failed: {e}")

    else:
        running = _rebalancer_is_running()
        status = "RUNNING" if running else "STOPPED"
        pid_file = Path("data/vault_rebalancer.pid")
        pid = pid_file.read_text().strip() if pid_file.exists() else "—"
        tg_send(token, chat_id,
                f"Vault rebalancer: {status}\n"
                f"PID: {pid}\n"
                f"Vault: {VAULT_ADDR}\n"
                f"Tick: 1h | Max leverage: 1x")


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
                    f"Rebalanced: {result['direction']} "
                    f"${result.get('amount_usd', 0):.2f} "
                    f"@ ${result.get('fill_price', 0):,.0f}\n"
                    f"Target: {result.get('target_btc_pct', 0):.1f}% BTC")
        else:
            tg_send(token, chat_id,
                    f"No trade needed — {result.get('reason', 'already at target')}\n"
                    f"Current: {result.get('current_btc_pct', 0):.1f}% | "
                    f"Target: {result.get('target_btc_pct', 0):.1f}%")
    except Exception as e:
        tg_send(token, chat_id, f"Rebalance error: {e}")


def cmd_market(token: str, chat_id: str, args: str) -> None:
    """Market update with technicals. Usage: /market <symbol>"""
    parts = args.split() if args else []
    if not parts:
        tg_send(token, chat_id, "Usage: /market <symbol>\nExamples: /market oil, /market btc, /market gold")
        return

    coin = resolve_coin(parts[0])
    if not coin:
        tg_send(token, chat_id, f"Unknown market: {parts[0]}\nTry: oil, btc, gold, silver, natgas, sp500")
        return

    display = next((w[0] for w in WATCHLIST if w[1] == coin), coin)
    lines = [f"*{display}* ({coin})", ""]

    # Current price
    mids = _hl_post({"type": "allMids"})
    price = None
    if coin in mids:
        price = float(mids[coin])
    else:
        try:
            book = _hl_post({"type": "l2Book", "coin": coin})
            levels = book.get("levels", [])
            if len(levels) >= 2 and levels[0] and levels[1]:
                price = (float(levels[0][0]["px"]) + float(levels[1][0]["px"])) / 2
        except Exception:
            pass

    if price:
        lines.append(f"Price: `${price:,.2f}`")
    else:
        lines.append("Price: unavailable")

    # Try to get market snapshot (technicals)
    try:
        from common.market_snapshot import build_snapshot, render_snapshot
        from modules.candle_cache import CandleCache
        cache = CandleCache()
        snap = build_snapshot(coin, cache, price or 0)
        brief = render_snapshot(snap, detail="brief")
        lines.append("")
        lines.append(brief)
    except Exception as e:
        log.debug("Snapshot unavailable for %s: %s", coin, e)

    # Funding rate for perp positions
    try:
        if coin.startswith("xyz:"):
            meta = _hl_post({"type": "metaAndAssetCtxs", "dex": "xyz"})
        else:
            meta = _hl_post({"type": "metaAndAssetCtxs"})
        if isinstance(meta, list) and len(meta) >= 2:
            asset_ctxs = meta[1]
            universe = meta[0].get("universe", [])
            for i, u in enumerate(universe):
                if u.get("name") == coin or u.get("name") == coin.replace("xyz:", ""):
                    if i < len(asset_ctxs):
                        fr = float(asset_ctxs[i].get("funding", 0))
                        oi = float(asset_ctxs[i].get("openInterest", 0))
                        lines.append(f"\nFunding: `{fr*100:.4f}%/h` ({fr*8760*100:.1f}% ann)")
                        if oi > 0:
                            lines.append(f"OI: `${oi:,.0f}`")
                    break
    except Exception:
        pass

    lines.append(f"\nLiquidity: {_liquidity_regime()}")
    tg_send(token, chat_id, "\n".join(lines))


def cmd_position(token: str, chat_id: str, _args: str) -> None:
    """Detailed position report with risk metrics."""
    positions = _get_all_positions(MAIN_ADDR)
    values = _get_account_values(MAIN_ADDR)
    total_equity = values['native'] + values['xyz']

    if not positions:
        tg_send(token, chat_id, "No open positions.")
        return

    lines = [f"*Positions* ({datetime.now(timezone.utc).strftime('%H:%M UTC')})", ""]

    for pos in positions:
        coin = pos.get('coin', '?')
        size = float(pos.get('szi', 0))
        entry = float(pos.get('entryPx', 0))
        upnl = float(pos.get('unrealizedPnl', 0))
        liq = pos.get('liquidationPx')
        lev = pos.get('leverage', {})
        lev_val = lev.get('value', '?') if isinstance(lev, dict) else lev
        margin_used = float(pos.get('marginUsed', 0))
        dex = pos.get('_dex', 'native')

        direction = "LONG" if size > 0 else "SHORT"
        pnl_emoji = "+" if upnl >= 0 else ""

        lines.append(f"*{coin}* ({dex}) — {direction}")
        lines.append(f"  Size: `{abs(size)}` @ `${entry:,.2f}`")
        lines.append(f"  uPnL: `{pnl_emoji}${upnl:,.2f}`")
        lines.append(f"  Leverage: `{lev_val}x` | Margin: `${margin_used:,.2f}`")

        if liq and liq != "N/A":
            liq_f = float(liq)
            current_price = entry  # approximate
            try:
                mids = _hl_post({"type": "allMids"})
                if coin in mids:
                    current_price = float(mids[coin])
                elif f"xyz:{coin}" in mids:
                    current_price = float(mids[f"xyz:{coin}"])
            except Exception:
                pass
            if current_price > 0 and liq_f > 0:
                liq_dist = abs(current_price - liq_f) / current_price * 100
                lines.append(f"  Liq: `${liq_f:,.2f}` ({liq_dist:.1f}% away)")
            else:
                lines.append(f"  Liq: `${liq_f:,.2f}`")

        # Check for SL/TP orders
        orders = _get_all_orders(MAIN_ADDR)
        sl_found = False
        tp_found = False
        for o in orders:
            if o.get('coin') == coin:
                if o.get('orderType') == 'Stop Market' or (o.get('triggerCondition') and o.get('side') != ('B' if size > 0 else 'A')):
                    sl_found = True
                elif o.get('reduceOnly'):
                    tp_found = True
        lines.append(f"  SL: {'SET' if sl_found else 'MISSING'} | TP: {'SET' if tp_found else 'MISSING'}")
        if not sl_found or not tp_found:
            lines.append(f"  ⚠ {'No SL!' if not sl_found else ''} {'No TP!' if not tp_found else ''}")
        lines.append("")

    lines.append(f"Total equity: `${total_equity:,.2f}`")
    lines.append(f"Liquidity: {_liquidity_regime()}")
    tg_send(token, chat_id, "\n".join(lines))


def cmd_bug(token: str, chat_id: str, args: str) -> None:
    """Report a bug. Usage: /bug <description>"""
    if not args.strip():
        tg_send(token, chat_id, "Usage: /bug <description>\nExample: /bug SL not being set on new BRENTOIL entries")
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

    tg_send(token, chat_id, f"Bug logged. Claude Code will pick it up.\n\n{args.strip()[:100]}")
    log.info("Bug reported via Telegram: %s", args.strip()[:80])


def cmd_feedback(token: str, chat_id: str, args: str) -> None:
    """Submit feedback. Usage: /feedback <text>"""
    if not args.strip():
        tg_send(token, chat_id, "Usage: /feedback <text>\nExample: /feedback market updates need more detail on technicals")
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

    tg_send(token, chat_id, "Feedback recorded. Thanks!")
    log.info("Feedback via Telegram: %s", args.strip()[:80])


def cmd_diag(token: str, chat_id: str, _args: str) -> None:
    """Show diagnostic summary."""
    if not _diag:
        tg_send(token, chat_id, "Diagnostics module not available.")
        return

    summary = _diag.get_summary()
    lines = ["*Diagnostics*", ""]
    lines.append(f"Uptime: {summary['uptime_seconds']}s")
    lines.append(f"Tool calls: {summary['total_tool_calls']}")
    lines.append(f"Errors: {summary['total_errors']}")

    if summary['errors']:
        lines.append("\n*Recent error sources:*")
        for src, count in summary['errors'].items():
            lines.append(f"  {src}: {count}")

    recent_errors = _diag.get_recent_errors(limit=3)
    if recent_errors:
        lines.append("\n*Last errors:*")
        for err in recent_errors:
            data = err.get('data', {})
            lines.append(f"  [{err.get('ts', '?')}] {data.get('source', data.get('tool', '?'))}: {data.get('message', data.get('error', '?'))[:100]}")

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
    "/feedback": cmd_feedback,
    "/fb": cmd_feedback,
    "/diag": cmd_diag,
    "/watchlist": cmd_watchlist,
    "/w": cmd_watchlist,
    "/powerlaw": cmd_powerlaw,
    "/rebalancer": cmd_rebalancer,
    "/rebalance": cmd_rebalance,
    "/help": cmd_help,
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
    "feedback": cmd_feedback,
    "fb": cmd_feedback,
    "diag": cmd_diag,
    "watchlist": cmd_watchlist,
    "w": cmd_watchlist,
    "powerlaw": cmd_powerlaw,
    "rebalancer": cmd_rebalancer,
    "rebalance": cmd_rebalance,
    "help": cmd_help,
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


def run() -> None:
    """Main polling loop. Runs forever until SIGTERM/SIGINT."""
    token = _keychain_read("bot_token")
    chat_id = _keychain_read("chat_id")
    if not token or not chat_id:
        log.error("Telegram credentials not in Keychain. Run setup first.")
        sys.exit(1)

    # Kill any existing instance first
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if old_pid != os.getpid():
                os.kill(old_pid, signal.SIGTERM)
                time.sleep(0.5)
                log.info("Killed previous bot instance (PID %d)", old_pid)
        except (OSError, ValueError):
            pass
        PID_FILE.unlink(missing_ok=True)

    PID_FILE.write_text(str(os.getpid()))

    running = True

    def _stop(signum, frame):
        nonlocal running
        log.info("Stopping telegram bot (signal %d)", signum)
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info("Telegram bot started — polling every %.0fs", POLL_INTERVAL)
    tg_send(token, chat_id, "Bot online. /help for commands.")

    offset = _get_last_update_id() + 1

    while running:
        updates = tg_get_updates(token, offset)

        for update in updates:
            uid = update.get("update_id", 0)
            offset = uid + 1
            _set_last_update_id(uid)

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
                except Exception as e:
                    log.error("Command %s failed: %s", cmd_key, e)
                    if _diag:
                        _diag.log_error("telegram_cmd", f"{cmd_key} failed: {e}")
                    tg_send(token, reply_chat_id, f"Error: {e}")
            else:
                # Not a command — silently ignore in group chats
                # (OpenClaw bot handles free text)
                # In DMs, queue for Claude's scheduled check-in
                is_group = msg.get("chat", {}).get("type", "") in ("group", "supergroup")
                if is_group:
                    log.debug("Ignoring free text in group (OpenClaw handles): %s", text[:50])
                else:
                    # Dedup: check if this message_id was already queued
                    msg_id = msg.get("message_id")
                    already_queued = False
                    if COMMAND_QUEUE.exists():
                        try:
                            for line in COMMAND_QUEUE.read_text().splitlines():
                                if line.strip():
                                    existing = json.loads(line)
                                    if existing.get("message_id") == msg_id:
                                        already_queued = True
                                        break
                        except Exception:
                            pass

                    if not already_queued:
                        COMMAND_QUEUE.parent.mkdir(parents=True, exist_ok=True)
                        entry = {
                            "timestamp": int(time.time()),
                            "message_id": msg_id,
                            "text": text,
                            "user": msg.get("from", {}).get("first_name", ""),
                        }
                        with open(COMMAND_QUEUE, "a") as f:
                            f.write(json.dumps(entry) + "\n")
                        log.info("Queued for Claude: %s", text[:80])
                    else:
                        log.debug("Dedup: message_id %s already queued", msg_id)

        if running:
            time.sleep(POLL_INTERVAL)

    # Cleanup
    PID_FILE.unlink(missing_ok=True)
    log.info("Telegram bot stopped.")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    run()
