"""Chat history Telegram command — browse the historical-oracle log.

Deterministic (no AI) — reads ``data/daemon/chat_history.jsonl`` directly.
Per Chris's explicit instruction, chat history is preserved forever as a
historical oracle correlating messages with market state at the time the
message was sent. This command gives read-only windows into it.

Sub-commands:
    /chathistory                — last 10 entries
    /chathistory 25             — last N entries (clamped 1..50)
    /chathistory search <query> — substring search across all entries
    /chathistory stats          — count, date range, role distribution

The lazy ``tg_send`` import inside each function avoids a circular
dependency with telegram_bot.py — same pattern the other telegram_commands
submodules use.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict


_HISTORY_PATH = Path("data/daemon/chat_history.jsonl")

_MAX_N = 50
_DEFAULT_N = 10
_MAX_SEARCH_RESULTS = 20
_SNIPPET_CHARS = 220  # per-entry preview in Telegram bodies


def _load_all_rows() -> List[Dict]:
    """Load every row from the live chat history file.

    Returns an empty list if the file is missing or unreadable. Malformed
    lines are silently skipped so one bad row doesn't black out the whole
    command.
    """
    if not _HISTORY_PATH.exists():
        return []
    rows: List[Dict] = []
    try:
        for line in _HISTORY_PATH.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows


def _fmt_ts(ts: int) -> str:
    """Format a unix ts as `YYYY-MM-DD HH:MM` in UTC."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "?"


def _snippet(text: str, max_chars: int = _SNIPPET_CHARS) -> str:
    """Clip ``text`` to a single-line preview suitable for Telegram."""
    if not isinstance(text, str):
        text = str(text)
    # Flatten newlines so multi-line assistant messages stay readable in the
    # listing view. Users can inspect full bodies with the search subcommand
    # or by reading the JSONL directly.
    flat = text.replace("\n", " ").replace("\r", " ")
    if len(flat) <= max_chars:
        return flat
    return flat[:max_chars - 3] + "..."


def _fmt_row(row: Dict) -> str:
    """Format one row as two Telegram lines: header + snippet."""
    ts = _fmt_ts(row.get("ts", 0))
    role = row.get("role", "?")
    role_icon = {"user": "👤", "assistant": "🤖"}.get(role, "·")
    user = row.get("user")
    user_part = f" {user}" if user else ""
    model = row.get("model")
    model_part = f" `{model.split('/')[-1]}`" if model else ""
    snippet = _snippet(row.get("text", ""))
    return f"{role_icon} `{ts}`{user_part}{model_part}\n    {snippet}"


def cmd_chathistory(token: str, chat_id: str, args: str) -> None:
    """``/chathistory`` dispatcher — last N, search, or stats.

    Deterministic. Reads only. Never writes or mutates the history file.
    """
    from cli.telegram_bot import tg_send

    arg = (args or "").strip()
    rows = _load_all_rows()

    if not rows:
        tg_send(token, chat_id,
                "💬 *Chat History*\n\n"
                "No entries yet. The history file is empty or missing:\n"
                f"`{_HISTORY_PATH}`")
        return

    # --- sub-command routing --------------------------------------------
    if arg.lower().startswith("stats"):
        _render_stats(token, chat_id, rows)
        return

    if arg.lower().startswith("search"):
        query = arg[len("search"):].strip()
        if not query:
            tg_send(token, chat_id,
                    "💬 *Chat History — Search*\n\n"
                    "Usage: `/chathistory search <query>`\n"
                    "Searches across all entries (case-insensitive).")
            return
        _render_search(token, chat_id, rows, query)
        return

    # --- default: last N -----------------------------------------------
    n = _DEFAULT_N
    if arg:
        try:
            n = max(1, min(_MAX_N, int(arg)))
        except ValueError:
            tg_send(token, chat_id,
                    "💬 *Chat History*\n\n"
                    "Usage:\n"
                    "  `/chathistory` — last 10\n"
                    "  `/chathistory 25` — last N\n"
                    "  `/chathistory search <query>`\n"
                    "  `/chathistory stats`")
            return
    _render_tail(token, chat_id, rows, n)


def _render_tail(token: str, chat_id: str, rows: List[Dict], n: int) -> None:
    """Render the last N rows."""
    from cli.telegram_bot import tg_send
    recent = rows[-n:]
    lines = [f"💬 *Chat History — Last {len(recent)} of {len(rows)}*", ""]
    for row in recent:
        lines.append(_fmt_row(row))
    lines.append("")
    lines.append(f"Total on disk: `{len(rows)}` rows. "
                 f"Use `/chathistory stats` for the full picture.")
    tg_send(token, chat_id, "\n".join(lines))


def _render_search(token: str, chat_id: str, rows: List[Dict], query: str) -> None:
    """Render case-insensitive substring search results (most recent first)."""
    from cli.telegram_bot import tg_send
    q = query.lower()
    matches = [r for r in rows if q in (r.get("text") or "").lower()]
    if not matches:
        tg_send(token, chat_id,
                f"💬 *Chat History — Search*\n\n"
                f"No entries match `{query}`. Searched `{len(rows)}` rows.")
        return
    # Most recent first — user wants to see "how did I last talk about oil"
    matches.reverse()
    shown = matches[:_MAX_SEARCH_RESULTS]
    lines = [
        f"💬 *Chat History — Search*",
        f"Query: `{query}` · `{len(matches)}` matches "
        f"(showing latest `{len(shown)}`)",
        "",
    ]
    for row in shown:
        lines.append(_fmt_row(row))
    if len(matches) > len(shown):
        lines.append("")
        lines.append(f"_...plus {len(matches) - len(shown)} older matches_")
    tg_send(token, chat_id, "\n".join(lines))


def _render_stats(token: str, chat_id: str, rows: List[Dict]) -> None:
    """Render count, date range, role distribution, market_context coverage."""
    from cli.telegram_bot import tg_send

    total = len(rows)
    roles: Dict[str, int] = {}
    earliest_ts = None
    latest_ts = None
    with_mc = 0
    users = set()

    for row in rows:
        role = row.get("role", "?")
        roles[role] = roles.get(role, 0) + 1
        ts = row.get("ts")
        if isinstance(ts, int) and ts > 0:
            if earliest_ts is None or ts < earliest_ts:
                earliest_ts = ts
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
        if row.get("market_context") is not None:
            with_mc += 1
        u = row.get("user")
        if isinstance(u, str) and u:
            users.add(u)

    lines = [
        "💬 *Chat History — Stats*",
        "",
        f"Total entries: `{total}`",
    ]
    if earliest_ts and latest_ts:
        lines.append(f"Earliest: `{_fmt_ts(earliest_ts)}` UTC")
        lines.append(f"Latest:   `{_fmt_ts(latest_ts)}` UTC")
        span_days = (latest_ts - earliest_ts) / 86400
        lines.append(f"Span: `{span_days:.1f}` days")
    lines.append("")
    lines.append("*Role distribution*")
    for role, count in sorted(roles.items(), key=lambda x: -x[1]):
        pct = (count / total * 100) if total else 0
        icon = {"user": "👤", "assistant": "🤖"}.get(role, "·")
        lines.append(f"  {icon} {role}: `{count}` ({pct:.0f}%)")
    lines.append("")
    mc_pct = (with_mc / total * 100) if total else 0
    lines.append(f"Market-context correlated: `{with_mc}` ({mc_pct:.0f}%)")
    if users:
        lines.append(f"Distinct users: `{len(users)}` "
                     f"({', '.join(sorted(users))})")

    # Sibling backup files — historical, preserved, referenced for audit.
    bak_files = sorted(
        p for p in _HISTORY_PATH.parent.glob("chat_history.jsonl.bak*")
        if p.is_file()
    )
    if bak_files:
        lines.append("")
        lines.append("*Sibling backups (preserved — never deleted)*")
        for p in bak_files:
            try:
                lc = sum(1 for _ in p.open())
                kb = p.stat().st_size / 1024
                lines.append(f"  `{p.name}`: `{lc}` rows (`{kb:.0f}KB`)")
            except OSError:
                continue

    tg_send(token, chat_id, "\n".join(lines))
