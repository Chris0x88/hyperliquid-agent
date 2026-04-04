"""Tool output renderers — format dicts for different consumers.

Two renderers:
- render_for_ai: compact, token-efficient, no decoration
- render_for_telegram: rich Telegram markdown with emoji (future, Phase E)
"""
from __future__ import annotations

import json
from typing import Any, Dict


# ═══════════════════════════════════════════════════════════════════════
# AI Renderer — compact, token-efficient
# ═══════════════════════════════════════════════════════════════════════

def render_for_ai(tool_name: str, data: dict) -> str:
    """Format tool output for AI agent — compact, token-efficient."""
    renderer = _AI_RENDERERS.get(tool_name, _render_generic_ai)
    try:
        return renderer(data)
    except Exception as e:
        return f"render error: {e}"


def _render_status_ai(data: dict) -> str:
    if "error" in data:
        return f"ERROR: {data['error']}"
    lines = [f"equity=${data['equity']:,.2f}"]
    for p in data.get("positions", []):
        d = "L" if p["direction"] == "LONG" else "S"
        line = f"{p['coin']} {d}{p['size']:.1f}@{p['entry_px']:,.2f} uPnL={p['upnl']:+,.2f} {p['leverage']}x"
        if p.get("liquidation_px"):
            line += f" liq={p['liquidation_px']:,.2f}"
        lines.append(line)
    for s in data.get("spot", []):
        lines.append(f"spot:{s['coin']}={s['total']:.2f}")
    return " | ".join(lines)


def _render_live_price_ai(data: dict) -> str:
    if "error" in data:
        return f"ERROR: {data['error']}"
    prices = data.get("prices", {})
    return " | ".join(f"{k}=${v:,.2f}" for k, v in prices.items())


def _render_analyze_ai(data: dict) -> str:
    if "error" in data:
        return f"ERROR: {data['error']}"
    parts = [f"{data['coin']}=${data['price']:,.2f}"]
    if data.get("technicals"):
        parts.append(data["technicals"])
    if data.get("signals"):
        parts.append(data["signals"])
    return "\n".join(parts)


def _render_market_brief_ai(data: dict) -> str:
    if "error" in data:
        return f"ERROR: {data['error']}"
    return data.get("brief", "No brief available")


def _render_funding_ai(data: dict) -> str:
    if "error" in data:
        return f"ERROR: {data['error']}"
    return (
        f"{data['coin']} ${data['price']:,.2f} ({data['change_24h_pct']:+.1f}%) "
        f"funding={data['funding_rate']*100:.4f}%/h ({data['funding_ann_pct']:.1f}%ann) "
        f"OI=${data['oi']/1e6:.1f}M vol=${data['volume_24h']/1e6:.1f}M"
    )


def _render_orders_ai(data: dict) -> str:
    if "error" in data:
        return f"ERROR: {data['error']}"
    orders = data.get("orders", [])
    if not orders:
        return "No open orders"
    lines = [f"{len(orders)} orders:"]
    for o in orders[:15]:
        lines.append(f"  {o['side']} {o['size']} {o['coin']} @{o['price']}")
    return "\n".join(lines)


def _render_journal_ai(data: dict) -> str:
    entries = data.get("entries", [])
    if not entries:
        return "No trade entries"
    lines = [f"Last {len(entries)} trades:"]
    for e in entries:
        lines.append(f"  {e['timestamp']} {e['coin']} {e['side']} {e['size']} @{e['price']} PnL:{e['pnl']}")
    return "\n".join(lines)


def _render_thesis_ai(data: dict) -> str:
    theses = data.get("theses", {})
    if not theses:
        return "No active theses"
    lines = []
    for mkt, t in theses.items():
        lines.append(f"{mkt}: {t['direction']} conv={t['conviction']:.2f} — {t.get('summary', '')[:80]}")
    return "\n".join(lines)


def _render_daemon_ai(data: dict) -> str:
    if "error" in data:
        return f"ERROR: {data['error']}"
    return (
        f"tier={data['tier']} tick={data['tick']} gate={data['gate']} "
        f"strategies={','.join(data.get('strategies', []))}"
    )


def _render_generic_ai(data: dict) -> str:
    """Fallback: compact JSON."""
    if "error" in data:
        return f"ERROR: {data['error']}"
    return json.dumps(data, default=str, separators=(",", ":"))


_AI_RENDERERS: Dict[str, Any] = {
    "status": _render_status_ai,
    "account_summary": _render_status_ai,
    "live_price": _render_live_price_ai,
    "analyze_market": _render_analyze_ai,
    "market_brief": _render_market_brief_ai,
    "check_funding": _render_funding_ai,
    "get_orders": _render_orders_ai,
    "trade_journal": _render_journal_ai,
    "thesis_state": _render_thesis_ai,
    "daemon_health": _render_daemon_ai,
}
