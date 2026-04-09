"""Lesson corpus Telegram commands.

First wedge of the cli/telegram_bot.py monolith split (2026-04-09). These
four handlers were extracted verbatim from telegram_bot.py — bodies are
unchanged, only their physical location moved.

All four are deterministic except `cmd_lessonauthorai` which has the
mandatory `ai` suffix because its output is model-authored.

Handlers exported:
    cmd_lessons        — list recent lessons
    cmd_lesson         — show / approve / reject / unreview one lesson
    cmd_lessonauthorai — author pending candidates via the dream cycle
    cmd_lessonsearch   — BM25 search over the corpus

The lazy `tg_send` import inside each function avoids a circular dependency
with telegram_bot.py. This is intentional. Do not refactor it without
moving tg_send to its own helper module first.
"""
from __future__ import annotations

import json


def cmd_lessons(token: str, chat_id: str, args: str) -> None:
    """Show the most recent lessons from the trade lesson corpus.

    Deterministic — reads data/memory/memory.db via common.memory.search_lessons.
    Optional argument: integer limit (default 10, max 25).
    Rejected lessons (reviewed_by_chris = -1) are excluded by default.
    """
    from cli.telegram_bot import tg_send
    from common import memory as common_memory

    limit = 10
    if args.strip():
        try:
            limit = max(1, min(25, int(args.strip())))
        except ValueError:
            pass

    try:
        rows = common_memory.search_lessons(limit=limit)
    except Exception as e:
        tg_send(token, chat_id, f"📓 Error reading lessons: {e}")
        return

    if not rows:
        tg_send(token, chat_id, "📓 No lessons yet. The lesson_author iterator "
                                "has not written any post-mortems — the corpus "
                                "is empty until a trade closes after wedge 5 ships.")
        return

    lines = [f"📓 *Latest {len(rows)} lessons*", ""]
    for r in rows:
        lesson_id = r.get("id")
        market = r.get("market", "?")
        direction = r.get("direction", "?")
        outcome = r.get("outcome", "?")
        signal = r.get("signal_source", "?")
        ltype = r.get("lesson_type", "?")
        roe = r.get("roe_pct", 0.0)
        closed = (r.get("trade_closed_at") or "")[:10]
        summary = (r.get("summary") or "").strip()
        reviewed = r.get("reviewed_by_chris", 0)
        flag = " ✅" if reviewed == 1 else ""
        lines.append(f"`#{lesson_id}` {closed} {market} {direction} ({signal}, {ltype})")
        lines.append(f"  → {outcome} {roe:+.1f}%{flag}")
        lines.append(f"  _{summary}_")
        lines.append("")
    lines.append("Use `/lesson <id>` to see the verbatim body.")
    tg_send(token, chat_id, "\n".join(lines))


def cmd_lesson(token: str, chat_id: str, args: str) -> None:
    """Show one lesson by id, or approve/reject a lesson.

    Usage:
        /lesson <id>           — show the verbatim body
        /lesson approve <id>   — mark reviewed_by_chris = 1 (boost ranking)
        /lesson reject <id>    — mark reviewed_by_chris = -1 (exclude, anti-pattern)
        /lesson unreview <id>  — reset reviewed_by_chris = 0

    Deterministic — reads/writes data/memory/memory.db directly, no AI.
    """
    from cli.telegram_bot import tg_send
    from common import memory as common_memory

    parts = args.strip().split()
    if not parts:
        tg_send(token, chat_id,
                "Usage: `/lesson <id>` or `/lesson approve|reject|unreview <id>`")
        return

    if parts[0] in ("approve", "reject", "unreview"):
        if len(parts) < 2:
            tg_send(token, chat_id, f"Usage: `/lesson {parts[0]} <id>`")
            return
        try:
            lesson_id = int(parts[1])
        except ValueError:
            tg_send(token, chat_id, f"Invalid id: {parts[1]!r}")
            return
        status_map = {"approve": 1, "reject": -1, "unreview": 0}
        status = status_map[parts[0]]
        try:
            ok = common_memory.set_lesson_review(lesson_id, status)
        except Exception as e:
            tg_send(token, chat_id, f"Error: {e}")
            return
        if not ok:
            tg_send(token, chat_id, f"Lesson #{lesson_id} not found.")
            return
        flag = {1: "approved ✅", -1: "rejected ❌", 0: "unreviewed"}[status]
        tg_send(token, chat_id, f"Lesson #{lesson_id} marked {flag}.")
        return

    try:
        lesson_id = int(parts[0])
    except ValueError:
        tg_send(token, chat_id, f"Invalid id: {parts[0]!r}")
        return

    try:
        row = common_memory.get_lesson(lesson_id)
    except Exception as e:
        tg_send(token, chat_id, f"Error reading lesson: {e}")
        return
    if row is None:
        tg_send(token, chat_id, f"Lesson #{lesson_id} not found.")
        return

    tags_raw = row.get("tags") or "[]"
    try:
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else list(tags_raw)
    except (ValueError, TypeError):
        tags = []

    reviewed = row.get("reviewed_by_chris", 0)
    review_flag = {1: "approved ✅", -1: "rejected ❌", 0: "unreviewed"}[reviewed]

    header = [
        f"📓 *Lesson #{row.get('id')}*",
        f"*Closed:* {row.get('trade_closed_at', '?')[:16]}",
        f"*Market:* {row.get('market', '?')} {row.get('direction', '?')}",
        f"*Signal:* {row.get('signal_source', '?')} · {row.get('lesson_type', '?')}",
        f"*Outcome:* {row.get('outcome', '?')}  "
        f"PnL ${row.get('pnl_usd', 0):+.2f}  ROE {row.get('roe_pct', 0):+.2f}%",
        f"*Review:* {review_flag}",
    ]
    if tags:
        header.append(f"*Tags:* {', '.join(tags)}")
    header.append("")
    header.append(f"_{(row.get('summary') or '').strip()}_")
    header.append("")
    header.append("*Verbatim body:*")
    header.append("```")
    body = (row.get("body_full") or "").strip()
    max_body = 3000
    if len(body) > max_body:
        body = body[:max_body] + "\n... [truncated, full body in memory.db]"
    header.append(body)
    header.append("```")
    tg_send(token, chat_id, "\n".join(header))


def cmd_lessonauthorai(token: str, chat_id: str, args: str) -> None:
    """Author pending lesson candidates: hand them to the agent and persist.

    AI-dependent — uses Claude Haiku via _call_anthropic in telegram_agent.
    Per CLAUDE.md slash-command rule, the `ai` suffix is required because
    this command's output (the lesson summary, analysis, tags) is written
    by the model.

    Usage:
        /lessonauthorai          — author the next 3 pending candidates
        /lessonauthorai 1        — author 1
        /lessonauthorai all      — author every pending candidate (capped at 25
                                   to keep the bot responsive)
    """
    from cli.telegram_bot import tg_send

    arg = (args or "").strip().lower()
    if arg == "all":
        max_lessons = 25
    elif arg:
        try:
            max_lessons = max(1, min(25, int(arg)))
        except ValueError:
            tg_send(token, chat_id, "Usage: `/lessonauthorai [N|all]`")
            return
    else:
        max_lessons = 3

    try:
        from cli.telegram_agent import _author_pending_lessons
        result = _author_pending_lessons(max_lessons=max_lessons)
    except Exception as e:
        tg_send(token, chat_id, f"📓 Authoring failed: {e}")
        return

    processed = result.get("processed", 0)
    failed = result.get("failed", 0)
    errors = result.get("errors", []) or []

    if processed == 0 and failed == 0:
        tg_send(token, chat_id, "📓 No pending lesson candidates to author.")
        return

    lines = [f"📓 *Lesson authoring*: {processed} authored, {failed} failed", ""]
    if processed:
        lines.append(f"✅ Wrote {processed} new lesson(s) to the corpus.")
        lines.append("Use `/lessons` to browse them.")
    if failed:
        lines.append("")
        lines.append("⚠️ Failures (candidates left in place for next run):")
        for err in errors[:5]:
            lines.append(f"  - {err}")
        if len(errors) > 5:
            lines.append(f"  ... and {len(errors) - 5} more")
    tg_send(token, chat_id, "\n".join(lines))


def cmd_lessonsearch(token: str, chat_id: str, args: str) -> None:
    """BM25-ranked search over the lesson corpus.

    Usage: /lessonsearch <query>
    Deterministic — reads data/memory/memory.db directly, no AI.
    """
    from cli.telegram_bot import tg_send
    from common import memory as common_memory

    query = args.strip()
    if not query:
        tg_send(token, chat_id, "Usage: `/lessonsearch <query>`")
        return

    try:
        rows = common_memory.search_lessons(query=query, limit=10)
    except Exception as e:
        tg_send(token, chat_id, f"📓 Search failed: {e}")
        return

    if not rows:
        tg_send(token, chat_id, f"📓 No lessons match `{query}`.")
        return

    lines = [f"📓 *Search: `{query}` — {len(rows)} hit(s)*", ""]
    for r in rows:
        lesson_id = r.get("id")
        market = r.get("market", "?")
        direction = r.get("direction", "?")
        outcome = r.get("outcome", "?")
        roe = r.get("roe_pct", 0.0)
        summary = (r.get("summary") or "").strip()
        lines.append(f"`#{lesson_id}` {market} {direction} → {outcome} {roe:+.1f}%")
        lines.append(f"  _{summary}_")
        lines.append("")
    lines.append("Use `/lesson <id>` to see the verbatim body.")
    tg_send(token, chat_id, "\n".join(lines))
