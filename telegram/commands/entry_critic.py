"""Entry-critic Telegram lookup command.

The Trade Entry Critic iterator (daemon/iterators/entry_critic.py)
detects new positions, scores them deterministically, and persists each
row to data/research/entry_critiques.jsonl.  The auto-fired alert is the
primary surface; this command is the manual lookup for after-the-fact
review.

Data is fetched via ``agent.tool_functions.read_entry_critiques`` — the
single source of truth (tools share one implementation, per architecture).

Commands exported:
    cmd_critique  — show recent entry critiques (deterministic, no AI)

Usage::
    /critique                — last 5 critiques, compact list
    /critique BTC            — last 5 critiques for BTC
    /critique BTC 10         — last 10 critiques for BTC
    /critique 1              — newest critique, full detail
    /critique BTC 1          — newest BTC critique, full detail
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

# ── Overall label → display emoji (per spec) ───────────────────────────
# PASS=✅  MIXED=⚠️  FAIL=🔴  NO_THESIS=❓  unknown=·
_LABEL_EMOJI: dict[str, str] = {
    # Canonical iterator labels
    "GREAT ENTRY": "✅",
    "GOOD ENTRY": "✅",
    "OK ENTRY": "⚠️",
    "RISKY ENTRY": "🔴",
    "BAD ENTRY": "🔴",
    "MIXED ENTRY": "⚠️",
    "NO THESIS": "❓",
    # Shortened variants written by some paths
    "GREAT": "✅",
    "GOOD": "✅",
    "OK": "⚠️",
    "RISKY": "🔴",
    "BAD": "🔴",
    "MIXED": "⚠️",
    "PASS": "✅",
    "FAIL": "🔴",
}

_VERDICT_MARKER: dict[str, str] = {
    "GREAT": "✅", "ALIGNED": "✅", "LEAD": "✅", "SAFE": "✅", "CHEAP": "✅",
    "OK": "⚠️", "FAIR": "⚠️", "NEUTRAL": "⚠️",
    "OVERWEIGHT": "⚠️", "LATE": "⚠️", "CASCADE_RISK": "⚠️",
    "EXPENSIVE": "⚠️", "UNDERWEIGHT": "⚠️",
    "OPPOSED": "🔴", "BAD": "🔴", "DANGER": "🔴",
    "NO_THESIS": "❓",
}


def _label_emoji(overall: str) -> str:
    return _LABEL_EMOJI.get(overall.upper(), "·")


def _verdict_marker(verdict: str) -> str:
    return _VERDICT_MARKER.get(verdict.upper(), "·")


def _age_str(created_at: str) -> str:
    """Return human-readable age like '3h 12m ago' from ISO-8601 UTC string."""
    if not created_at:
        return ""
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        secs = int(time.time() - dt.timestamp())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"{h}h {m}m ago" if m else f"{h}h ago"
    except (ValueError, TypeError):
        return created_at[:16].replace("T", " ")


def cmd_critique(token: str, chat_id: str, args: str) -> None:
    """Show recent entry critiques from data/research/entry_critiques.jsonl.

    /critique             — last 5 critiques, compact list
    /critique BTC         — last 5 for BTC (xyz: prefix stripped automatically)
    /critique BTC 10      — last 10 for BTC
    /critique 1           — most recent critique, full detail
    /critique BTC 1       — most recent BTC critique, full detail

    Deterministic — reads the JSONL written by the entry_critic iterator.
    No AI.
    """
    from telegram.bot import tg_send
    from agent.tool_functions import read_entry_critiques

    parts = args.strip().split() if args else []
    instrument_filter: str | None = None
    limit = 5

    for p in parts:
        if p.isdigit():
            limit = max(1, min(20, int(p)))
        else:
            instrument_filter = p.upper()

    result = read_entry_critiques(limit=limit, market=instrument_filter)
    rows = result.get("critiques", [])
    total = result.get("total", 0)

    if not rows:
        scope = f" for {instrument_filter}" if instrument_filter else ""
        tg_send(token, chat_id,
                f"No entry critiques{scope}. "
                "Daemon entry_critic iterator fires on every new position.")
        return

    if limit == 1 or (not args.strip() and len(rows) == 1):
        tg_send(token, chat_id, _format_full(rows[0]))
    else:
        tg_send(token, chat_id, _format_compact(rows, instrument_filter, total))


# ── Formatters ──────────────────────────────────────────────────────────

def _format_compact(rows: list[dict], instrument_filter: str | None, total: int) -> str:
    scope = f" — {instrument_filter}" if instrument_filter else ""
    shown = len(rows)
    lines = [f"*Entry Critiques{scope}* ({shown} of {total})", ""]
    for r in rows:
        instrument = r.get("instrument", "?")
        direction = (r.get("direction") or "?").upper()
        grade = r.get("grade") or {}
        overall = grade.get("overall_label", "?")
        emoji = _label_emoji(overall)
        p_n = grade.get("pass_count", 0)
        w_n = grade.get("warn_count", 0)
        f_n = grade.get("fail_count", 0)
        age = _age_str(r.get("created_at", ""))
        entry_price = r.get("entry_price")
        # First suggestion as "short reason"
        suggestions = grade.get("suggestions") or []
        reason = suggestions[0][:60] if suggestions else overall
        px_str = f"@{entry_price}" if entry_price else ""
        lines.append(
            f"{emoji} *{instrument}* {direction} {px_str}  "
            f"({p_n}✅/{w_n}⚠️/{f_n}🔴)  {age}"
        )
        if reason and reason != overall:
            lines.append(f"   _{reason}_")
    lines.append("")
    lines.append("Use `/critique 1` for the latest full critique.")
    return "\n".join(lines)


def _format_full(row: dict) -> str:
    instrument = row.get("instrument", "?")
    direction = (row.get("direction") or "?").upper()
    entry_price = row.get("entry_price")
    entry_qty = row.get("entry_qty")
    created_at = (row.get("created_at") or "")[:19].replace("T", " ")
    age = _age_str(row.get("created_at", ""))
    grade = row.get("grade") or {}
    signals = row.get("signals") or {}

    overall = grade.get("overall_label", "?")
    emoji = _label_emoji(overall)
    p_n = grade.get("pass_count", 0)
    w_n = grade.get("warn_count", 0)
    f_n = grade.get("fail_count", 0)

    lines = [
        f"*Entry Critique — {instrument} {direction}*",
        f"_{created_at} UTC ({age})_",
        f"Entry: `{entry_qty}` @ `${entry_price}`",
        "",
    ]

    for axis, label in (
        ("sizing", "Sizing"),
        ("direction", "Direction"),
        ("catalyst_timing", "Timing"),
        ("liquidity", "Liquidity"),
        ("funding", "Funding"),
    ):
        verdict = grade.get(axis, "?")
        detail = grade.get(f"{axis}_detail", "")
        marker = _verdict_marker(verdict)
        lines.append(f"{marker} *{label}:* {verdict} — {detail}")

    # Signals compact block
    rsi = signals.get("rsi")
    atr_pct = signals.get("atr_pct")
    liq_cushion = signals.get("liquidation_cushion_pct")
    snapshot_flags = signals.get("snapshot_flags") or []
    sigs = []
    if rsi is not None:
        sigs.append(f"RSI {rsi:.1f}")
    if atr_pct is not None:
        sigs.append(f"ATR {atr_pct:.2f}%")
    if liq_cushion is not None:
        sigs.append(f"liq-cushion {liq_cushion:.1f}%")
    if snapshot_flags:
        sigs.append(" ".join(snapshot_flags[:3]))
    if sigs:
        lines.append("")
        lines.append(f"_Signals: {' · '.join(sigs)}_")

    lessons = signals.get("lesson_ids") or []
    if lessons:
        lines.append(f"_Lessons recalled: {', '.join(f'#{x}' for x in lessons[:5])}_")

    lines.append("")
    lines.append(f"{emoji} *{overall}*  ({p_n}✅ / {w_n}⚠️ / {f_n}🔴)")

    suggestions = grade.get("suggestions") or []
    if suggestions:
        lines.append("")
        lines.append("*Suggestions:*")
        for s in suggestions[:5]:
            lines.append(f"  · {s}")

    degraded = row.get("degraded") or {}
    missing = [k for k, v in degraded.items() if v]
    if missing:
        lines.append("")
        lines.append(f"_Degraded inputs: {', '.join(missing)}_")

    return "\n".join(lines)
