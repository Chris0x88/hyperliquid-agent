"""Entry-critic Telegram lookup command — third submodule in the
cli/telegram_commands/ split (after lessons.py, brutal_review.py).

The Trade Entry Critic iterator (cli/daemon/iterators/entry_critic.py)
detects new positions, scores them against a deterministic signal stack,
posts a Telegram alert immediately, and persists the row to
data/research/entry_critiques.jsonl. The auto-fired alerts are the
primary surface — this command is the manual lookup for after-the-fact
review of past entries.

Deterministic. No AI. The full grading was already computed by the
iterator at entry time; we just read the JSONL and reformat.

Commands exported:
    cmd_critique  — show recent entry critiques (deterministic)
"""
from __future__ import annotations

import json
from pathlib import Path

ENTRY_CRITIQUES_JSONL = "data/research/entry_critiques.jsonl"

_OVERALL_EMOJI = {
    "GREAT": "🟢",
    "GOOD": "✅",
    "OK": "🟡",
    "RISKY": "⚠️",
    "BAD": "❌",
}


def cmd_critique(token: str, chat_id: str, args: str) -> None:
    """Show recent entry critiques from data/research/entry_critiques.jsonl.

    Usage:
        /critique             — most recent critique (full detail)
        /critique 5           — last 5 critiques (compact list)
        /critique BTC         — last 5 critiques filtered to instrument
        /critique BTC 10      — last 10 critiques filtered to instrument

    Deterministic — reads the JSONL written by the entry_critic iterator
    when each new position was detected. No AI.
    """
    from cli.telegram_bot import tg_send

    parts = args.strip().split() if args else []
    instrument_filter: str | None = None
    limit = 1

    # Parse args: integer-only → limit; string-only → instrument; both → instrument + limit
    for p in parts:
        if p.isdigit():
            limit = max(1, min(20, int(p)))
        else:
            instrument_filter = p.upper()

    # If only instrument was given, default to 5 entries
    if instrument_filter and len(parts) == 1:
        limit = 5

    path = Path(ENTRY_CRITIQUES_JSONL)
    if not path.exists():
        tg_send(
            token,
            chat_id,
            "📊 No entry critiques yet — the entry_critic iterator hasn't "
            "detected any new positions. (Or the daemon isn't running.)",
        )
        return

    rows: list[dict] = []
    try:
        with path.open("r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        tg_send(token, chat_id, f"📊 Error reading critiques: {e}")
        return

    # Filter by instrument if requested. Compare both raw and stripped forms
    # so xyz:BRENTOIL and BRENTOIL both match.
    if instrument_filter:
        def _match(r: dict) -> bool:
            inst = (r.get("instrument") or "").upper()
            stripped = inst.replace("XYZ:", "")
            return inst == instrument_filter or stripped == instrument_filter

        rows = [r for r in rows if _match(r)]

    # Most recent first
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    rows = rows[:limit]

    if not rows:
        scope = f" for {instrument_filter}" if instrument_filter else ""
        tg_send(token, chat_id, f"📊 No entry critiques{scope} found.")
        return

    if limit == 1:
        tg_send(token, chat_id, _format_one_full(rows[0]))
    else:
        tg_send(token, chat_id, _format_compact_list(rows, instrument_filter))


def _format_one_full(row: dict) -> str:
    """Full single-critique view — matches the iterator's live alert format."""
    instrument = row.get("instrument", "?")
    direction = (row.get("direction") or "?").upper()
    entry_price = row.get("entry_price")
    entry_qty = row.get("entry_qty")
    created_at = (row.get("created_at") or "")[:19].replace("T", " ")
    grade = row.get("grade") or {}
    signals = row.get("signals") or {}

    overall = grade.get("overall_label", "?")
    emoji = _OVERALL_EMOJI.get(overall, "·")
    pass_n = grade.get("pass_count", 0)
    warn_n = grade.get("warn_count", 0)
    fail_n = grade.get("fail_count", 0)

    lines = [
        f"📊 *Entry Critique — {instrument} {direction} {entry_qty} @ {entry_price}*",
        f"_{created_at} UTC_",
        "",
    ]
    for axis, axis_label in (
        ("sizing", "Sizing"),
        ("direction", "Direction"),
        ("catalyst_timing", "Timing"),
        ("liquidity", "Liquidity"),
        ("funding", "Funding"),
    ):
        verdict = grade.get(axis, "?")
        detail = grade.get(f"{axis}_detail", "")
        marker = _verdict_marker(verdict)
        lines.append(f"{marker} *{axis_label}:* {verdict} — {detail}")

    lessons = signals.get("lesson_ids") or []
    if lessons:
        lines.append("")
        lines.append(f"📚 *Lessons consulted:* {', '.join(f'#{lid}' for lid in lessons[:5])}")

    lines.append("")
    lines.append(f"{emoji} *OVERALL: {overall}*  ({pass_n} ✅ / {warn_n} ⚠️ / {fail_n} ❌)")

    suggestions = grade.get("suggestions") or []
    if suggestions:
        lines.append("")
        lines.append("💡 *Suggestions:*")
        for s in suggestions[:5]:
            lines.append(f"  · {s}")

    degraded = row.get("degraded") or {}
    missing = [k for k, v in degraded.items() if v]
    if missing:
        lines.append("")
        lines.append(f"_Degraded inputs: {', '.join(missing)}_")

    return "\n".join(lines)


def _format_compact_list(rows: list[dict], instrument_filter: str | None) -> str:
    """One-line-per-critique compact view."""
    title_scope = f" — {instrument_filter}" if instrument_filter else ""
    lines = [f"📊 *Recent Entry Critiques{title_scope} ({len(rows)})*", ""]
    for r in rows:
        ts = (r.get("created_at") or "")[:16].replace("T", " ")
        instrument = r.get("instrument", "?")
        direction = (r.get("direction") or "?").upper()
        qty = r.get("entry_qty")
        price = r.get("entry_price")
        grade = r.get("grade") or {}
        overall = grade.get("overall_label", "?")
        emoji = _OVERALL_EMOJI.get(overall, "·")
        pass_n = grade.get("pass_count", 0)
        warn_n = grade.get("warn_count", 0)
        fail_n = grade.get("fail_count", 0)
        lines.append(
            f"{emoji} `{ts}` *{instrument}* {direction} {qty}@{price}  "
            f"{overall} ({pass_n}✅/{warn_n}⚠️/{fail_n}❌)"
        )
    lines.append("")
    lines.append("Use `/critique` (no args) for the latest full critique.")
    return "\n".join(lines)


def _verdict_marker(verdict: str) -> str:
    """Map an axis verdict to an inline marker."""
    if verdict in ("GREAT", "ALIGNED", "LEAD", "SAFE", "CHEAP"):
        return "✅"
    if verdict in ("OK", "FAIR", "NEUTRAL"):
        return "🟡"
    if verdict in ("OVERWEIGHT", "LATE", "CASCADE_RISK", "EXPENSIVE", "UNDERWEIGHT"):
        return "⚠️"
    if verdict in ("OPPOSED", "BAD", "DANGER"):
        return "❌"
    if verdict == "NO_THESIS":
        return "·"
    return "·"
