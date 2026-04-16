"""Action Queue (nudge ledger) Telegram command.

``/nudge`` surfaces the "things Chris should do" queue that the
``action_queue`` daemon iterator maintains. Deterministic — no AI.
Reads / writes ``data/research/action_queue.jsonl`` via
``modules.action_queue.ActionQueue``.

Usage:
    /nudge                       show every item, overdue first
    /nudge overdue               show only overdue items
    /nudge done <id>             mark an item done right now (resets cadence)
    /nudge add <kind> <days> <description...>
                                 add a custom time-based item to the queue
    /nudge remove <id>           remove a custom item
"""
from __future__ import annotations

import time

from engines.learning.action_queue import (
    DEFAULT_STATE_PATH,
    ActionItem,
    ActionQueue,
)


def cmd_nudge(token: str, chat_id: str, args: str) -> None:
    """User-Action Queue — list, add, remove, and mark-done nudge items."""
    from telegram.bot import tg_send

    parts = args.strip().split()
    sub = parts[0].lower() if parts else ""

    try:
        q = ActionQueue(state_path=DEFAULT_STATE_PATH)
        q.load()
    except Exception as e:
        tg_send(token, chat_id, f"Action queue: failed to load state: `{e}`")
        return

    now_ts = time.time()

    # ── done ──
    if sub == "done":
        if len(parts) < 2:
            tg_send(token, chat_id, "Usage: `/nudge done <id>`")
            return
        item_id = parts[1]
        if q.get(item_id) is None:
            tg_send(token, chat_id, f"Unknown action id: `{item_id}`.\nUse `/nudge` to see the queue.")
            return
        q.mark_done(item_id, now_ts=now_ts)
        try:
            q.save()
        except OSError as e:
            tg_send(token, chat_id, f"Marked `{item_id}` done, but save failed: `{e}`")
            return
        tg_send(token, chat_id, f"Marked `{item_id}` done. Nudges suppressed until the next cadence window.")
        return

    # ── add ──
    if sub == "add":
        # /nudge add <kind> <cadence_days> <description...>
        if len(parts) < 4:
            tg_send(
                token, chat_id,
                "Usage: `/nudge add <kind> <cadence_days> <description>`\n"
                "Example: `/nudge add weekly_check 7 Review open thesis files`"
            )
            return
        kind = parts[1]
        try:
            cadence_days = int(parts[2])
            if cadence_days < 0:
                raise ValueError
        except ValueError:
            tg_send(token, chat_id, f"Invalid cadence_days: `{parts[2]}` (must be a non-negative integer)")
            return
        description = " ".join(parts[3:])
        # Use the kind as the id unless it collides; then append a suffix.
        item_id = kind
        suffix = 1
        while q.get(item_id) is not None:
            suffix += 1
            item_id = f"{kind}_{suffix}"
        q.upsert(ActionItem(
            id=item_id,
            kind=kind,
            description=description,
            cadence_days=cadence_days,
            severity="advisory",
        ))
        try:
            q.save()
        except OSError as e:
            tg_send(token, chat_id, f"Added, but save failed: `{e}`")
            return
        tg_send(
            token, chat_id,
            f"Added action item `{item_id}` (kind={kind}, cadence={cadence_days}d).\n"
            f"_{description}_",
        )
        return

    # ── remove ──
    if sub == "remove":
        if len(parts) < 2:
            tg_send(token, chat_id, "Usage: `/nudge remove <id>`")
            return
        item_id = parts[1]
        if not q.remove(item_id):
            tg_send(token, chat_id, f"Unknown action id: `{item_id}`.")
            return
        try:
            q.save()
        except OSError as e:
            tg_send(token, chat_id, f"Removed, but save failed: `{e}`")
            return
        tg_send(token, chat_id, f"Removed action item `{item_id}`.")
        return

    # ── list (overdue or full) ──
    only_overdue = sub == "overdue"
    if only_overdue:
        items_to_show = q.all_overdue(now_ts=now_ts)
    else:
        items_to_show = q.items

    if not items_to_show:
        if only_overdue:
            tg_send(token, chat_id, "Action queue: nothing overdue right now.")
        else:
            tg_send(token, chat_id, "Action queue is empty.")
        return

    # Sort: overdue first, then by severity, then by id
    sev_rank = {"overdue": 0, "warning": 1, "advisory": 2}

    def _sort_key(item: ActionItem):
        overdue_rank = 0 if item.is_overdue(now_ts) else 1
        sev = sev_rank.get(item.escalated_severity(now_ts), 3)
        return (overdue_rank, sev, item.id)

    items_to_show = sorted(items_to_show, key=_sort_key)

    header = "*Action queue — overdue*" if only_overdue else "*Action queue*"
    n_overdue = sum(1 for i in items_to_show if i.is_overdue(now_ts))
    lines: list[str] = [header, f"_{n_overdue}/{len(items_to_show)} overdue_", ""]
    for item in items_to_show:
        status, marker = _status_marker(item, now_ts)
        lines.append(f"{marker} `{item.id}` — {item.description}")
        lines.append(f"    _{_detail(item, now_ts)}_  (`{status}`)")
    lines.append("")
    lines.append(
        "`/nudge done <id>`  `/nudge add <kind> <days> <desc>`  "
        "`/nudge remove <id>`  `/nudge overdue`"
    )
    tg_send(token, chat_id, "\n".join(lines))


# ── Helpers ──────────────────────────────────────────────────────────────


def _status_marker(item: ActionItem, now_ts: float) -> tuple[str, str]:
    """Return (status string, single-line marker) for list rows."""
    if not item.is_overdue(now_ts):
        return ("ok", "[ok]")
    sev = item.escalated_severity(now_ts)
    if sev == "overdue":
        return ("overdue", "[!!]")
    if sev == "warning":
        return ("warning", "[!]")
    return ("advisory", "[i]")


def _detail(item: ActionItem, now_ts: float) -> str:
    """Short per-item status line used in both list and nudge views."""
    from engines.learning.action_queue import PER_SESSION_KINDS, THRESHOLD_KINDS

    if item.kind in PER_SESSION_KINDS:
        return "per-session ritual"
    if item.kind in THRESHOLD_KINDS:
        count = item.context.get("pending_count", "?")
        return f"pending count = {count} (threshold {item.cadence_days})"
    if item.last_done_ts <= 0:
        return f"never done; cadence {item.cadence_days}d"
    age_days = (now_ts - item.last_done_ts) / 86400.0
    return f"last done {age_days:.1f}d ago; cadence {item.cadence_days}d"
