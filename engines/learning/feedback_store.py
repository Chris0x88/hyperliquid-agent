"""Append-only event-sourced store for /feedback items.

Purpose
-------
Historical oracle for user-submitted feedback. Chris has been leaving
feedback via Telegram since 2026-04-02; these rows become the most
valuable signal the bot has about what it got wrong, what's stale,
and what to fix next. They must NEVER be lost and NEVER be rewritten
in place.

Design
------
Every file is an append-only JSONL event log. Three event shapes live
in the same file:

1. **Original feedback rows** (legacy schema, emitted by
   telegram_bot.cmd_feedback since April 2026):
       {"timestamp": ..., "source": ..., "text": ...}
   Optionally with ``resolved: bool`` from the pre-eventing code path.

2. **New feedback rows** (emitted by add_feedback()):
       {"id": "fb_<ts>_<rand>", "timestamp": ..., "source": ...,
        "text": ..., "tags": [], "status": "open"}

3. **Event rows** (emitted by set_feedback_status / tag_feedback):
       {"id": "<orig>_<eventname>_<ts>", "ref_id": "<orig>",
        "timestamp": ..., "event": "status_change"|"tag_add",
        "from_status": ..., "to_status": ..., "tag": ..., "note": ...}

An event row ALWAYS has both ``ref_id`` and ``event``. That is the
cheap discriminator used by load_feedback() to split the file into
two streams: primaries and events.

Critical invariants
-------------------
* ``add_feedback`` and all state-change operations ONLY ever call
  ``open(path, "a")``. No ``"w"``, ever.
* Backwards compatibility with the 21 legacy rows on disk is
  **read-only**: we synthesise an ``id`` from the timestamp + a hash
  of the first 32 chars of text so the same legacy row always gets
  the same id across runs. The on-disk row is never modified.
* The legacy ``resolved: true/false`` field is honoured on read as
  the initial status, so historical state changes made by the old
  destructive ``cmd_feedback_resolve`` are preserved. This is a
  one-way bridge — going forward every state change is a new event.
* Computed status is ``open`` unless a status_change event overrides
  it; the most recent event by timestamp wins.

This module is deliberately I/O-minimal: one JSONL file per store,
no database, no external deps. FTS5 indexing is a clean follow-up
wedge but substring search is fine for the 21-row baseline.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# BUG-FIX 2026-04-17: file path is engines/learning/feedback_store.py, so
# .parent.parent = engines/. The project root is one more level up.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Known status vocabularies. Adding a new status is additive; callers
# pass raw strings so we don't hard-fail on unknown values, but new
# flows should pick from these.
FEEDBACK_STATUSES = ("open", "resolved", "dismissed", "wontfix")
TODO_STATUSES = ("open", "done", "dismissed")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FeedbackItem:
    """A single feedback row with its computed state."""

    id: str
    timestamp: str
    source: str
    text: str
    tags: list[str] = field(default_factory=list)
    status: str = "open"
    # Full event history for this item, chronological. Each entry is
    # the raw event dict as read from disk. Primaries are excluded.
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "source": self.source,
            "text": self.text,
            "tags": list(self.tags),
            "status": self.status,
            "history": list(self.history),
        }


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def feedback_path() -> Path:
    """Resolve the canonical feedback JSONL path (agent-cli/data/feedback.jsonl)."""
    return _PROJECT_ROOT / "data" / "feedback.jsonl"


def todos_path() -> Path:
    """Resolve the canonical todos JSONL path (agent-cli/data/todos.jsonl)."""
    return _PROJECT_ROOT / "data" / "todos.jsonl"


# ---------------------------------------------------------------------------
# Id generation
# ---------------------------------------------------------------------------


def _legacy_id(timestamp: str, text: str, prefix: str) -> str:
    """Generate a deterministic id for a legacy row with no id field.

    The same (timestamp, text) ALWAYS produces the same id across
    processes so backwards-compat status events can be keyed against
    the original row.
    """
    key = f"{timestamp}|{text[:32]}".encode("utf-8", errors="replace")
    digest = hashlib.md5(key).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _fresh_id(prefix: str) -> str:
    """Generate a fresh id for a brand-new primary row.

    Format: ``<prefix>_<unix_ts>_<rand4>``. Unix ts keeps lexical
    ordering roughly chronological; rand4 de-dupes collisions inside
    the same second.
    """
    ts = int(time.time())
    rand = f"{random.randint(0, 0xFFFF):04x}"
    return f"{prefix}_{ts}_{rand}"


# ---------------------------------------------------------------------------
# Generic load / mutate
# ---------------------------------------------------------------------------


def _iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    """Yield parsed JSONL rows from ``path``. Empty/missing file yields nothing."""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Silently skip corrupt rows — we never delete them.
                    continue
    except OSError:
        return


def _is_event_row(row: dict[str, Any]) -> bool:
    """Cheap discriminator: event rows have both ``ref_id`` and ``event``."""
    return "ref_id" in row and "event" in row


def _normalise_primary(
    row: dict[str, Any],
    *,
    prefix: str,
    default_status: str,
) -> FeedbackItem:
    """Turn an on-disk primary row into a FeedbackItem with all fields present.

    Handles both:
    * New schema rows (have ``id``, ``tags``, ``status``)
    * Legacy schema rows (just ``timestamp``, ``source``, ``text``,
      optionally ``resolved``)
    """
    text = row.get("text", "")
    timestamp = row.get("timestamp", "")
    source = row.get("source", "telegram")

    row_id = row.get("id")
    if not row_id:
        row_id = _legacy_id(timestamp, text, prefix)

    tags = row.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    status = row.get("status")
    if not status:
        # Legacy ``resolved`` field bridges to status. Feedback uses
        # "resolved", todos use "done". The caller controls the mapping
        # via default_status / the prefix.
        if row.get("resolved") is True:
            status = "resolved" if prefix == "fb" else "done"
        else:
            status = default_status

    return FeedbackItem(
        id=row_id,
        timestamp=timestamp,
        source=source,
        text=text,
        tags=list(tags),
        status=status,
    )


def _load(
    path: Path,
    *,
    prefix: str,
    default_status: str,
) -> list[FeedbackItem]:
    """Load primaries, replay events, and return a list of FeedbackItems.

    Ordering: primaries are returned in the order they were written
    (chronological append order).
    """
    primaries: dict[str, FeedbackItem] = {}
    primary_order: list[str] = []
    events_by_ref: dict[str, list[dict[str, Any]]] = {}

    for row in _iter_rows(path):
        if _is_event_row(row):
            events_by_ref.setdefault(row["ref_id"], []).append(row)
            continue
        item = _normalise_primary(
            row, prefix=prefix, default_status=default_status
        )
        if item.id not in primaries:
            primary_order.append(item.id)
        # If two primaries somehow share an id (shouldn't, but legacy
        # md5 collisions are theoretically possible on identical text),
        # the latest write wins for body, but we keep the first order.
        primaries[item.id] = item

    # Replay events in chronological order per item.
    for ref_id, events in events_by_ref.items():
        item = primaries.get(ref_id)
        if item is None:
            # Orphan event (primary deleted — shouldn't happen, but we
            # never crash on it). Skip.
            continue
        events.sort(key=lambda e: e.get("timestamp", ""))
        item.history = list(events)
        for event in events:
            kind = event.get("event")
            if kind == "status_change":
                new_status = event.get("to_status")
                if isinstance(new_status, str) and new_status:
                    item.status = new_status
            elif kind == "tag_add":
                tag = event.get("tag")
                if isinstance(tag, str) and tag and tag not in item.tags:
                    item.tags.append(tag)
            elif kind == "tag_remove":
                tag = event.get("tag")
                if isinstance(tag, str) and tag in item.tags:
                    item.tags.remove(tag)
            # Unknown event kinds are preserved in history but ignored
            # during replay.

    return [primaries[pid] for pid in primary_order]


def _append(path: Path, row: dict[str, Any]) -> None:
    """Append a single JSONL row. Never overwrites."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Feedback API
# ---------------------------------------------------------------------------


def load_feedback(path: Path | None = None) -> list[FeedbackItem]:
    """Load all feedback items with computed status.

    Args:
        path: optional override (used by tests). Defaults to
              ``agent-cli/data/feedback.jsonl``.
    """
    return _load(
        path or feedback_path(),
        prefix="fb",
        default_status="open",
    )


def add_feedback(
    text: str,
    source: str = "telegram",
    tags: list[str] | None = None,
    *,
    path: Path | None = None,
) -> str:
    """Append a new feedback primary row. Returns the new id."""
    target = path or feedback_path()
    new_id = _fresh_id("fb")
    row = {
        "id": new_id,
        "timestamp": _now_iso(),
        "source": source,
        "text": text,
        "tags": list(tags or []),
        "status": "open",
    }
    _append(target, row)
    return new_id


def set_feedback_status(
    item_id: str,
    status: str,
    note: str = "",
    *,
    path: Path | None = None,
) -> bool:
    """Append a status_change event row. Returns True on success.

    Returns False if the id does not match any existing primary — we
    never emit a status_change event for something that does not exist.
    """
    target = path or feedback_path()
    items = {i.id: i for i in load_feedback(target)}
    item = items.get(item_id)
    if item is None:
        return False
    from_status = item.status
    event = {
        "id": f"{item_id}_status_{int(time.time() * 1000)}",
        "ref_id": item_id,
        "timestamp": _now_iso(),
        "event": "status_change",
        "from_status": from_status,
        "to_status": status,
        "note": note,
    }
    _append(target, event)
    return True


def tag_feedback(
    item_id: str,
    tag: str,
    *,
    path: Path | None = None,
) -> bool:
    """Append a tag_add event row. Returns True on success."""
    target = path or feedback_path()
    items = {i.id: i for i in load_feedback(target)}
    if item_id not in items:
        return False
    event = {
        "id": f"{item_id}_tag_{int(time.time() * 1000)}",
        "ref_id": item_id,
        "timestamp": _now_iso(),
        "event": "tag_add",
        "tag": tag,
        "note": "",
    }
    _append(target, event)
    return True


def get_feedback(
    item_id: str,
    *,
    path: Path | None = None,
) -> FeedbackItem | None:
    """Return a single feedback item by id, or None."""
    for item in load_feedback(path):
        if item.id == item_id:
            return item
    return None


def search_feedback(
    query: str,
    limit: int = 10,
    *,
    status: str | None = None,
    path: Path | None = None,
) -> list[FeedbackItem]:
    """Substring search across feedback text.

    Args:
        query: substring to match (case-insensitive).
        limit: max rows to return.
        status: optional status filter (``"open"``, ``"resolved"``, ...).
        path: test override.

    Returns the most recent matches first.
    """
    q = (query or "").lower().strip()
    items = load_feedback(path)
    matches: list[FeedbackItem] = []
    for item in items:
        if status and item.status != status:
            continue
        if q and q not in (item.text or "").lower():
            continue
        matches.append(item)
    matches.reverse()
    return matches[:limit]


# ---------------------------------------------------------------------------
# Todos API (shares the same store semantics, different file)
# ---------------------------------------------------------------------------


def load_todos(path: Path | None = None) -> list[FeedbackItem]:
    """Load all todo items with computed status."""
    return _load(
        path or todos_path(),
        prefix="td",
        default_status="open",
    )


def add_todo(
    text: str,
    source: str = "telegram",
    tags: list[str] | None = None,
    *,
    path: Path | None = None,
) -> str:
    target = path or todos_path()
    new_id = _fresh_id("td")
    row = {
        "id": new_id,
        "timestamp": _now_iso(),
        "source": source,
        "text": text,
        "tags": list(tags or []),
        "status": "open",
    }
    _append(target, row)
    return new_id


def set_todo_status(
    item_id: str,
    status: str,
    note: str = "",
    *,
    path: Path | None = None,
) -> bool:
    target = path or todos_path()
    items = {i.id: i for i in load_todos(target)}
    item = items.get(item_id)
    if item is None:
        return False
    event = {
        "id": f"{item_id}_status_{int(time.time() * 1000)}",
        "ref_id": item_id,
        "timestamp": _now_iso(),
        "event": "status_change",
        "from_status": item.status,
        "to_status": status,
        "note": note,
    }
    _append(target, event)
    return True


def tag_todo(
    item_id: str,
    tag: str,
    *,
    path: Path | None = None,
) -> bool:
    target = path or todos_path()
    items = {i.id: i for i in load_todos(target)}
    if item_id not in items:
        return False
    event = {
        "id": f"{item_id}_tag_{int(time.time() * 1000)}",
        "ref_id": item_id,
        "timestamp": _now_iso(),
        "event": "tag_add",
        "tag": tag,
        "note": "",
    }
    _append(target, event)
    return True


def get_todo(
    item_id: str,
    *,
    path: Path | None = None,
) -> FeedbackItem | None:
    for item in load_todos(path):
        if item.id == item_id:
            return item
    return None


def search_todos(
    query: str,
    limit: int = 10,
    *,
    status: str | None = None,
    path: Path | None = None,
) -> list[FeedbackItem]:
    q = (query or "").lower().strip()
    items = load_todos(path)
    matches: list[FeedbackItem] = []
    for item in items:
        if status and item.status != status:
            continue
        if q and q not in (item.text or "").lower():
            continue
        matches.append(item)
    matches.reverse()
    return matches[:limit]


# ---------------------------------------------------------------------------
# Resolver used by Telegram when the user types a short prefix
# ---------------------------------------------------------------------------


def resolve_prefix(
    prefix: str,
    items: list[FeedbackItem],
) -> FeedbackItem | None:
    """Match a user-supplied id (full or short prefix) to exactly one item.

    Telegram users rarely copy the full ``fb_1712345678_ab12`` id. We
    allow them to supply the shortest unique suffix-of-seconds + rand
    (e.g. ``ab12``) or the full id. If the prefix matches more than
    one item we return None — the caller should ask the user to be
    more specific.
    """
    if not prefix:
        return None
    prefix = prefix.strip()
    exact = [i for i in items if i.id == prefix]
    if exact:
        return exact[0]
    partial = [i for i in items if prefix in i.id]
    if len(partial) == 1:
        return partial[0]
    return None


__all__ = [
    "FeedbackItem",
    "FEEDBACK_STATUSES",
    "TODO_STATUSES",
    "feedback_path",
    "todos_path",
    "load_feedback",
    "add_feedback",
    "set_feedback_status",
    "tag_feedback",
    "get_feedback",
    "search_feedback",
    "load_todos",
    "add_todo",
    "set_todo_status",
    "tag_todo",
    "get_todo",
    "search_todos",
    "resolve_prefix",
]
