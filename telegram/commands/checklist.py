"""Evening + Morning checklist slash commands.

/evening — pre-sleep safety cockpit for all markets with open positions.
/morning — post-sleep debrief: what filled, what got swept, decisions pending.

Both are 100% deterministic Python — zero LLM calls, zero API costs.
Output is capped at ~3500 chars per message; multi-message if needed.

Registered in telegram/bot.py HANDLERS, _set_telegram_commands(), cmd_help().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

log = logging.getLogger("telegram.checklist")

# ── Display helpers ───────────────────────────────────────────

_STATUS_EMOJI = {
    "pass": "✅",
    "warn": "⚠️",
    "fail": "❌",
    "skip": "⏭",
}

_SCORE_LABEL = {
    "pass": "ALL CLEAR",
    "warn": "NEEDS ATTENTION",
    "fail": "DANGER — CHECK REQUIRED",
}

MAX_MSG_LEN = 3400  # Conservative limit — Telegram max is 4096


def _render_market_block(result: dict, mode: str) -> str:
    """Render one market's checklist result as a Telegram block."""
    market = result.get("market", "?")
    bare = market.replace("xyz:", "")
    status = result.get("status", "pass")
    score = result.get("score", 1.0)
    items = result.get("items", [])

    status_emoji = _STATUS_EMOJI.get(status, "❓")
    score_pct = int(score * 100)

    lines = [f"{status_emoji} *{bare}* — {score_pct}% pass"]

    # Show fails first, then warns — skip passes unless nothing else
    fails = [i for i in items if i["status"] == "fail"]
    warns = [i for i in items if i["status"] == "warn"]

    for item in fails:
        lines.append(f"  ❌ {item['reason']}")

    for item in warns:
        lines.append(f"  ⚠️ {item['reason']}")

    if not fails and not warns:
        # All clear — show a compact summary
        pass_count = sum(1 for i in items if i["status"] == "pass")
        skip_count = sum(1 for i in items if i["status"] == "skip")
        lines.append(f"  ✅ {pass_count} checks passed, {skip_count} skipped")

    return "\n".join(lines)


def _split_messages(text: str) -> List[str]:
    """Split text at newlines to stay under MAX_MSG_LEN."""
    if len(text) <= MAX_MSG_LEN:
        return [text]

    chunks = []
    current = []
    current_len = 0

    for line in text.split("\n"):
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > MAX_MSG_LEN and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def _get_positions_summary(positions: list) -> str:
    """Compact positions summary for the header."""
    if not positions:
        return "No open positions"
    parts = []
    for p in positions:
        coin = str(p.get("coin", "?")).replace("xyz:", "")
        size = float(p.get("size", 0))
        direction = "L" if size > 0 else "S"
        lev = p.get("leverage", "?")
        upnl = float(p.get("upnl", 0))
        sign = "+" if upnl >= 0 else ""
        parts.append(f"{coin} {direction}{lev}x `{sign}${upnl:,.0f}`")
    return " | ".join(parts)


# ── /evening command ──────────────────────────────────────────


def cmd_evening(token: str, chat_id: str, args: str) -> None:
    """Pre-sleep safety cockpit.

    Usage: /evening [MARKET]
    If MARKET provided, filter to that market only.
    """
    from telegram.bot import tg_send
    from engines.checklist.runner import build_ctx, run_checklist, run_all_markets, _load_thesis
    from common.account_state import fetch_registered_account_state

    tg_send(token, chat_id, "Running evening checklist...")

    try:
        bundle = fetch_registered_account_state()
        positions = bundle.get("positions", [])
        total_equity = float(bundle.get("account", {}).get("total_equity", 0))
        from exchange.helpers import _get_all_orders
        # Fetch orders from every configured wallet so vault positions get SL/TP audit
        orders = []
        seen_oids: set = set()
        for acct in bundle.get("accounts", []):
            addr = acct.get("address", "")
            if not addr:
                continue
            for o in _get_all_orders(addr):
                oid = o.get("oid") or id(o)
                if oid not in seen_oids:
                    seen_oids.add(oid)
                    orders.append(o)

        ctx = build_ctx(positions=positions, orders=orders, total_equity=total_equity)

        # Filter market if arg provided
        filter_market = args.strip().upper() if args.strip() else None

        ts_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
        header_lines = [
            f"🌙 *Evening Checklist* — {ts_str}",
            f"Equity: `${total_equity:,.2f}` | Positions: {_get_positions_summary(positions)}",
            "",
        ]

        if filter_market:
            # Find the full coin name with xyz: prefix if needed
            resolved = _resolve_market(filter_market, positions)
            markets_to_run = [resolved] if resolved else []
            if not markets_to_run:
                tg_send(token, chat_id,
                        f"Unknown market: {filter_market}\nUse: /evening or /evening SILVER")
                return
        else:
            # Run all markets with open positions
            if not positions:
                tg_send(token, chat_id,
                        "🌙 *Evening Checklist*\n\nNo open positions — all clear for tonight! 🛌")
                return
            markets_to_run = list({p.get("coin", "") for p in positions if p.get("coin")})

        market_blocks = []
        all_fails = 0
        all_warns = 0

        for market in markets_to_run:
            # Inject market-specific thesis
            market_ctx = dict(ctx)
            market_ctx["thesis"] = _load_thesis(market)
            market_ctx["market"] = market

            result = run_checklist(market, "evening", market_ctx)
            market_blocks.append(_render_market_block(result, "evening"))
            all_fails += len([i for i in result.get("items", []) if i["status"] == "fail"])
            all_warns += len([i for i in result.get("items", []) if i["status"] == "warn"])

        # Summary footer
        if all_fails > 0:
            footer = f"❌ *{all_fails} FAIL(S)* — do NOT sleep until resolved"
        elif all_warns > 0:
            footer = f"⚠️ *{all_warns} warning(s)* — review before sleep"
        else:
            footer = "✅ All clear — safe to sleep 🛌"

        body = "\n\n".join(header_lines + market_blocks + ["", footer])

        for chunk in _split_messages(body):
            tg_send(token, chat_id, chunk)

    except Exception as exc:
        log.exception("Evening checklist failed")
        tg_send(token, chat_id, f"❌ Evening checklist error: {exc}")


# ── /morning command ──────────────────────────────────────────


def cmd_morning(token: str, chat_id: str, args: str) -> None:
    """Post-sleep debrief cockpit.

    Usage: /morning [MARKET]
    """
    from telegram.bot import tg_send
    from engines.checklist.runner import build_ctx, run_checklist, run_all_markets, _load_thesis
    from common.account_state import fetch_registered_account_state

    tg_send(token, chat_id, "Running morning debrief...")

    try:
        bundle = fetch_registered_account_state()
        positions = bundle.get("positions", [])
        total_equity = float(bundle.get("account", {}).get("total_equity", 0))
        from exchange.helpers import _get_all_orders
        # Fetch orders from every configured wallet so vault positions get SL/TP audit
        orders = []
        seen_oids_m: set = set()
        for acct in bundle.get("accounts", []):
            addr = acct.get("address", "")
            if not addr:
                continue
            for o in _get_all_orders(addr):
                oid = o.get("oid") or id(o)
                if oid not in seen_oids_m:
                    seen_oids_m.add(oid)
                    orders.append(o)

        ctx = build_ctx(positions=positions, orders=orders, total_equity=total_equity)

        filter_market = args.strip().upper() if args.strip() else None

        ts_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
        header_lines = [
            f"☀️ *Morning Debrief* — {ts_str}",
            f"Equity: `${total_equity:,.2f}` | Positions: {_get_positions_summary(positions)}",
            "",
        ]

        if filter_market:
            resolved = _resolve_market(filter_market, positions)
            markets_to_run = [resolved] if resolved else []
            if not markets_to_run:
                tg_send(token, chat_id,
                        f"Unknown market: {filter_market}\nUse: /morning or /morning SILVER")
                return
        else:
            # Morning: always run approved thesis markets + open positions
            approved = ["BTC", "xyz:BRENTOIL", "xyz:GOLD", "xyz:SILVER"]
            position_coins = [p.get("coin", "") for p in positions if p.get("coin")]
            markets_to_run = list(dict.fromkeys(approved + position_coins))

        market_blocks = []
        all_warns = 0

        for market in markets_to_run:
            market_ctx = dict(ctx)
            market_ctx["thesis"] = _load_thesis(market)
            market_ctx["market"] = market

            result = run_checklist(market, "morning", market_ctx)
            market_blocks.append(_render_market_block(result, "morning"))
            all_warns += len([i for i in result.get("items", []) if i["status"] == "warn"])

        # Sweep risk summary across all held markets
        sweep_lines = _build_sweep_summary(markets_to_run, ctx)

        if all_warns > 0:
            footer = f"⚠️ *{all_warns} item(s)* need review before trading"
        else:
            footer = "✅ Morning clear — Asia session loading 🌏"

        body = "\n\n".join(
            header_lines
            + market_blocks
            + (["", "🔍 *Sweep Risk*", "\n".join(sweep_lines)] if sweep_lines else [])
            + ["", footer]
        )

        for chunk in _split_messages(body):
            tg_send(token, chat_id, chunk)

    except Exception as exc:
        log.exception("Morning checklist failed")
        tg_send(token, chat_id, f"❌ Morning checklist error: {exc}")


def _resolve_market(arg: str, positions: list) -> Optional[str]:
    """Resolve a user-supplied market name to the full coin identifier."""
    bare = arg.replace("xyz:", "").upper()
    # Check open positions first
    for p in positions:
        coin = str(p.get("coin", ""))
        if coin.replace("xyz:", "").upper() == bare:
            return coin
    # Known approved markets
    known = {
        "BTC": "BTC",
        "BRENTOIL": "xyz:BRENTOIL",
        "GOLD": "xyz:GOLD",
        "SILVER": "xyz:SILVER",
        "CL": "xyz:CL",
        "SP500": "xyz:SP500",
        "NATGAS": "xyz:NATGAS",
    }
    return known.get(bare)


def _build_sweep_summary(markets: list, ctx: dict) -> List[str]:
    """Build sweep risk one-liner per market."""
    from engines.checklist.sweep_detector import detect_sweep_risk

    lines = []
    for market in markets:
        market_ctx = dict(ctx)
        market_ctx["market"] = market
        try:
            sr = detect_sweep_risk(market, market_ctx)
            score = sr.get("score", 0)
            bare = market.replace("xyz:", "")
            score_emoji = {0: "🟢", 1: "🟡", 2: "🟠", 3: "🔴"}.get(score, "⚪")
            reasoning = sr.get("reasoning", "")
            lines.append(f"  {score_emoji} {bare}: {reasoning}")
        except Exception:
            pass

    return lines
