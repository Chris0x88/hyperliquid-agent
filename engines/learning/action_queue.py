"""Action Queue — the "things Chris should do" nudge ledger.

Pure logic, no I/O beyond the explicit load/save JSONL helpers. This module
exists because the HyperLiquid bot has many manual rituals scattered across
the codebase (restore drill, brutal review, thesis refresh, lesson approval,
backup health check, alignment ritual, feedback review) and nothing tracks
them centrally. Chris explicitly said: "there are so many things you are
relying on me to trigger... we need something in the schedule that documents
all this! And prompts the user... otherwise I simply will forget."

This is that ledger. The daemon iterator (``cli/daemon/iterators/action_queue.py``)
calls into this module once a day, auto-updates a few item fields by
inspecting the system, runs ``evaluate()`` to find overdue items, posts a
Telegram digest, and records the nudge so it doesn't fire again until the
next cycle. The Telegram command (``cli/telegram_commands/action_queue.py``)
exposes ``/nudge`` so Chris can list, add, and mark done items from the
phone.

Design choices worth reviewing:

1. **JSONL persistence, not JSON.** One line per item, atomic append-only
   writes with a rewrite on save. Mirrors the existing
   ``data/research/*.jsonl`` pattern used everywhere else in this codebase.
   The state file lives at ``data/research/action_queue.jsonl`` — a
   path shared with the research/journal family because action items are
   operator-facing research state, not trade-critical state.

2. **Cadence kinds are discriminators in the ``kind`` field, not a separate
   enum.** Items with ``kind == "lesson_approval_queue"`` use ``cadence_days``
   as a *threshold count of pending lessons*, not a time interval. Items
   with ``kind == "alignment_ritual"`` use ``cadence_days == 0`` as a
   "per-session, no cadence" marker. All other items interpret
   ``cadence_days`` as a standard day interval. This keeps the dataclass
   simple at the cost of one dispatch in ``is_overdue()``.

3. **Two timestamps, not one.** ``last_done_ts`` and ``last_nudged_ts``
   are separate. Marking an item done resets ``last_done_ts`` AND clears
   ``last_nudged_ts`` so the next nudge cycle starts fresh. Nudging only
   writes ``last_nudged_ts``. This means Chris can be nudged multiple times
   about the same overdue item across days but never within a single
   24h window.

4. **Severity mapped from overdue age**, not stored as a static field. A
   7-day-cadence item that is 2 days late is ``advisory``; 14 days late
   is ``warning``; 30+ days late is ``overdue``. The ``severity`` field
   on the item is the *starting* severity — it's the default when an
   item first becomes overdue. ``format_nudge_telegram()`` escalates
   based on how far past due.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Optional


DEFAULT_STATE_PATH = "data/research/action_queue.jsonl"

# Nudge throttle — an item that was nudged within this window is NOT re-nudged
# on the next tick even if still overdue. Prevents daemon restart loops or
# sub-daily tick cadences from spamming the chat.
NUDGE_COOLDOWN_S = 24 * 3600

# Cadence kinds that use ``cadence_days`` as a threshold count rather than
# a day interval. These items go overdue when a *count* (from context) exceeds
# the threshold, not when a time interval has elapsed.
THRESHOLD_KINDS = frozenset({"lesson_approval_queue"})

# Cadence kinds that fire every single tick when ``cadence_days == 0``. Used
# for the alignment ritual which has no natural cadence — it's per-session.
PER_SESSION_KINDS = frozenset({"alignment_ritual"})


# ── Data model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActionItem:
    """One "thing Chris should do" in the queue.

    Frozen so mutations go through ``ActionQueue`` which rewrites the file
    atomically. ``replace()`` is the idiomatic way to make a new copy with
    one field changed.
    """

    id: str
    kind: str
    description: str
    cadence_days: int                  # see THRESHOLD_KINDS / PER_SESSION_KINDS
    last_done_ts: float = 0.0          # epoch seconds; 0 = never
    last_nudged_ts: float = 0.0        # epoch seconds; 0 = never
    severity: str = "advisory"         # starting severity: advisory / warning / overdue
    context: dict[str, Any] = field(default_factory=dict)

    # ── Derived helpers ──

    def is_overdue(self, now_ts: float) -> bool:
        """Return True if this item needs attention right now.

        Dispatch:
          - THRESHOLD_KINDS: overdue when ``context["pending_count"] >= cadence_days``
          - PER_SESSION_KINDS: always overdue (no natural cadence)
          - default: overdue when ``now - last_done_ts >= cadence_days * 86400``

        Items that have never been done (``last_done_ts == 0``) are overdue
        immediately for the default case. Threshold items still require
        ``pending_count`` to cross the bar.
        """
        if self.kind in PER_SESSION_KINDS:
            return True
        if self.kind in THRESHOLD_KINDS:
            try:
                count = int(self.context.get("pending_count", 0))
            except (TypeError, ValueError):
                count = 0
            return count >= int(self.cadence_days)
        if self.last_done_ts <= 0:
            return True
        elapsed_days = (now_ts - self.last_done_ts) / 86400.0
        return elapsed_days >= float(self.cadence_days)

    def days_overdue(self, now_ts: float) -> float:
        """How many days past due this item is. 0 for threshold kinds /
        per-session kinds / not-overdue items."""
        if self.kind in (PER_SESSION_KINDS | THRESHOLD_KINDS):
            return 0.0
        if self.last_done_ts <= 0:
            return float(self.cadence_days)
        elapsed_days = (now_ts - self.last_done_ts) / 86400.0
        return max(0.0, elapsed_days - float(self.cadence_days))

    def escalated_severity(self, now_ts: float) -> str:
        """Return the effective severity right now. Escalates time-based
        items based on how far past due they are:
          0    <= overdue <  cadence      → advisory
          cadence <= overdue < 2*cadence  → warning
          2*cadence <= overdue            → overdue
        Threshold items use the pending count as the escalation axis:
          count == threshold               → advisory
          count == 1.5*threshold           → warning
          count >= 2*threshold             → overdue
        Per-session items always return the base severity.
        """
        if self.kind in PER_SESSION_KINDS:
            return self.severity
        if self.kind in THRESHOLD_KINDS:
            try:
                count = int(self.context.get("pending_count", 0))
            except (TypeError, ValueError):
                count = 0
            threshold = max(1, int(self.cadence_days))
            if count >= 2 * threshold:
                return "overdue"
            if count >= int(threshold * 1.5):
                return "warning"
            return "advisory"

        overdue = self.days_overdue(now_ts)
        if overdue <= 0:
            return self.severity
        cadence = max(1, int(self.cadence_days))
        if overdue >= 2 * cadence:
            return "overdue"
        if overdue >= cadence:
            return "warning"
        return "advisory"


# ── Queue ────────────────────────────────────────────────────────────────


class ActionQueue:
    """In-memory queue backed by a JSONL file.

    Use ``load()`` to read, ``save()`` to write, and ``evaluate()`` to get
    overdue items that have NOT been nudged in the past 24h.

    Custom items (user-added via ``/nudge add``) are stored alongside seed
    items. When the seed list changes (e.g. a new item is added to
    ``default_action_items()``), ``load()`` merges the disk file with the
    seed defaults: any seed item ID not present on disk is appended; any
    disk item not in the seed list is kept as-is (so custom items survive).
    """

    def __init__(self, state_path: str = DEFAULT_STATE_PATH):
        self._state_path = Path(state_path)
        self._items: dict[str, ActionItem] = {}

    # ── Properties ──

    @property
    def items(self) -> list[ActionItem]:
        """Snapshot list of items in insertion order."""
        return list(self._items.values())

    def get(self, item_id: str) -> Optional[ActionItem]:
        return self._items.get(item_id)

    # ── Load / save ──

    def load(self) -> None:
        """Read the JSONL file and merge with the seed defaults.

        If the file does not exist, seeds the queue from ``default_action_items()``.
        If the file exists, reads it line-by-line and upserts. Any seed item
        whose ID is not present on disk is then appended (so schema additions
        land on the next tick). Custom items with no matching seed entry are
        kept as-is.
        """
        disk_items: dict[str, ActionItem] = {}
        if self._state_path.exists():
            try:
                with self._state_path.open("r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        try:
                            item = _row_to_item(row)
                        except (TypeError, ValueError, KeyError):
                            continue
                        disk_items[item.id] = item
            except OSError:
                disk_items = {}

        # Start with seed defaults so insertion order is stable across
        # restarts; then overwrite with disk state where present.
        merged: dict[str, ActionItem] = {}
        for seed in default_action_items():
            if seed.id in disk_items:
                merged[seed.id] = disk_items[seed.id]
            else:
                merged[seed.id] = seed
        # Keep any disk-only (custom) items that the seed list doesn't know
        # about. They go at the end.
        for item_id, item in disk_items.items():
            if item_id not in merged:
                merged[item_id] = item
        self._items = merged

    def save(self) -> None:
        """Atomic rewrite of the JSONL file.

        Writes to a .tmp file, fsyncs, then renames. If the parent directory
        does not exist, it is created.
        """
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        with tmp.open("w") as f:
            for item in self._items.values():
                f.write(json.dumps(_item_to_row(item), sort_keys=True))
                f.write("\n")
        tmp.replace(self._state_path)

    # ── Mutations ──

    def upsert(self, item: ActionItem) -> None:
        """Insert or replace an item by id."""
        self._items[item.id] = item

    def remove(self, item_id: str) -> bool:
        """Delete an item. Returns True if removed."""
        return self._items.pop(item_id, None) is not None

    def mark_done(self, item_id: str, now_ts: Optional[float] = None) -> bool:
        """Record that Chris just did this thing. Resets ``last_done_ts``
        to ``now_ts`` and clears ``last_nudged_ts`` so the next nudge cycle
        starts fresh. Returns True if the item existed."""
        if item_id not in self._items:
            return False
        ts = float(now_ts if now_ts is not None else time.time())
        old = self._items[item_id]
        self._items[item_id] = replace(old, last_done_ts=ts, last_nudged_ts=0.0)
        return True

    def mark_nudged(self, item_id: str, now_ts: Optional[float] = None) -> bool:
        """Record that we just posted a nudge about this item. Returns True
        if the item existed."""
        if item_id not in self._items:
            return False
        ts = float(now_ts if now_ts is not None else time.time())
        old = self._items[item_id]
        self._items[item_id] = replace(old, last_nudged_ts=ts)
        return True

    def set_context(self, item_id: str, context: dict[str, Any]) -> bool:
        """Replace the context payload on an item (e.g. auto-updated
        ``pending_count`` from the iterator). Returns True if the item
        existed."""
        if item_id not in self._items:
            return False
        old = self._items[item_id]
        self._items[item_id] = replace(old, context=dict(context))
        return True

    # ── Evaluation ──

    def evaluate(self, now_ts: Optional[float] = None) -> list[ActionItem]:
        """Return items that are overdue AND have not been nudged in the
        past ``NUDGE_COOLDOWN_S`` seconds.

        Skips per-session items when called from the daemon (they're only
        surfaced by the Telegram ``/nudge`` command, not by auto-nudges —
        otherwise every tick would blast a reminder). Per-session items
        are still returned by ``all_overdue()``.
        """
        ts = float(now_ts if now_ts is not None else time.time())
        out: list[ActionItem] = []
        for item in self._items.values():
            if item.kind in PER_SESSION_KINDS:
                continue
            if not item.is_overdue(ts):
                continue
            if item.last_nudged_ts > 0 and (ts - item.last_nudged_ts) < NUDGE_COOLDOWN_S:
                continue
            out.append(item)
        return out

    def all_overdue(self, now_ts: Optional[float] = None) -> list[ActionItem]:
        """Every overdue item regardless of nudge history. Used by
        ``/nudge`` and ``/nudge overdue`` to show the full picture."""
        ts = float(now_ts if now_ts is not None else time.time())
        return [item for item in self._items.values() if item.is_overdue(ts)]


# ── Seed list ────────────────────────────────────────────────────────────


def default_action_items() -> list[ActionItem]:
    """The initial queue of rituals Chris needs to remember.

    Keep this list in sync with ``docs/wiki/operations/`` runbooks. When you
    add a new operator ritual to the wiki, add it here too so the nudge
    system knows about it.
    """
    return [
        ActionItem(
            id="restore_drill",
            kind="restore_drill",
            description=(
                "Run the memory.db restore drill — see "
                "docs/wiki/operations/memory-restore-drill.md"
            ),
            cadence_days=90,
            severity="warning",
        ),
        ActionItem(
            id="brutal_review",
            kind="brutal_review",
            description="Run /brutalreviewai for the weekly deep audit",
            cadence_days=7,
            severity="advisory",
        ),
        ActionItem(
            id="thesis_refresh_check",
            kind="thesis_refresh_check",
            description=(
                "Check thesis files in data/thesis/ — anything older than "
                "14 days needs refresh or formal park"
            ),
            cadence_days=7,
            severity="advisory",
        ),
        ActionItem(
            id="lesson_approval_queue",
            kind="lesson_approval_queue",
            description=(
                "Approve or reject pending lessons via /lessons + "
                "/lesson approve|reject <id>"
            ),
            cadence_days=5,  # threshold count — >= 5 pending triggers nudge
            severity="advisory",
        ),
        ActionItem(
            id="backup_health_check",
            kind="backup_health_check",
            description=(
                "Verify newest memory.db backup is <2h old and integrity "
                "check passes"
            ),
            cadence_days=7,
            severity="warning",
        ),
        ActionItem(
            id="alignment_ritual",
            kind="alignment_ritual",
            description="Run /alignment at start and end of each Claude Code session",
            cadence_days=0,  # per-session, no time cadence
            severity="advisory",
        ),
        ActionItem(
            id="feedback_review",
            kind="feedback_review",
            description="Review unresolved /feedback entries",
            cadence_days=7,
            severity="advisory",
        ),
    ]


# ── Telegram formatting ──────────────────────────────────────────────────


def format_nudge_telegram(items: list[ActionItem], now_ts: Optional[float] = None) -> str:
    """Build a single Telegram message that summarises everything overdue.

    Groups items by escalated severity (overdue → warning → advisory) and
    uses Markdown V1 that tg_send already handles. Keeps line count bounded
    so a long queue doesn't produce a message Telegram will reject.
    """
    if not items:
        return "Action queue: nothing overdue."

    ts = float(now_ts if now_ts is not None else time.time())
    by_sev: dict[str, list[ActionItem]] = {"overdue": [], "warning": [], "advisory": []}
    for item in items:
        sev = item.escalated_severity(ts)
        by_sev.setdefault(sev, []).append(item)

    lines: list[str] = ["*Action queue nudge*"]
    header_suffix = _overdue_summary(items, ts)
    if header_suffix:
        lines.append(header_suffix)
    lines.append("")

    for sev_label, marker in (("overdue", "[!!]"), ("warning", "[!]"), ("advisory", "[i]")):
        group = by_sev.get(sev_label, [])
        if not group:
            continue
        lines.append(f"*{sev_label.upper()}*")
        for item in group:
            lines.append(f"  {marker} `{item.id}` — {item.description}")
            detail = _detail_line(item, ts)
            if detail:
                lines.append(f"      _{detail}_")
        lines.append("")

    lines.append("Mark done with `/nudge done <id>` once you've handled it.")
    return "\n".join(lines).rstrip()


def _overdue_summary(items: list[ActionItem], now_ts: float) -> str:
    n_time = sum(
        1 for i in items
        if i.kind not in (PER_SESSION_KINDS | THRESHOLD_KINDS)
    )
    n_threshold = sum(1 for i in items if i.kind in THRESHOLD_KINDS)
    parts: list[str] = []
    if n_time:
        parts.append(f"{n_time} time-based")
    if n_threshold:
        parts.append(f"{n_threshold} threshold")
    if not parts:
        return ""
    return f"_({' + '.join(parts)} overdue)_"


def _detail_line(item: ActionItem, now_ts: float) -> str:
    if item.kind in PER_SESSION_KINDS:
        return "per-session ritual"
    if item.kind in THRESHOLD_KINDS:
        count = item.context.get("pending_count", "?")
        return f"pending count = {count} (threshold {item.cadence_days})"
    if item.last_done_ts <= 0:
        return f"never done; cadence {item.cadence_days}d"
    age_days = (now_ts - item.last_done_ts) / 86400.0
    overdue_days = item.days_overdue(now_ts)
    return (
        f"last done {age_days:.1f}d ago (cadence {item.cadence_days}d; "
        f"overdue by {overdue_days:.1f}d)"
    )


# ── Serialisation helpers ────────────────────────────────────────────────


def _item_to_row(item: ActionItem) -> dict[str, Any]:
    """Convert an ActionItem to the dict we write to disk. Mirrors
    ``asdict`` but is kept explicit so field additions are deliberate."""
    row = asdict(item)
    # Ensure nested context is a plain dict (asdict handles this but be
    # defensive against non-serialisable values).
    row["context"] = dict(item.context) if item.context else {}
    return row


def _row_to_item(row: dict[str, Any]) -> ActionItem:
    """Reverse of ``_item_to_row``. Accepts missing fields by falling back
    to defaults. Raises KeyError / TypeError / ValueError on malformed rows
    so ``ActionQueue.load`` can catch and skip them."""
    return ActionItem(
        id=str(row["id"]),
        kind=str(row["kind"]),
        description=str(row["description"]),
        cadence_days=int(row.get("cadence_days", 0)),
        last_done_ts=float(row.get("last_done_ts", 0.0) or 0.0),
        last_nudged_ts=float(row.get("last_nudged_ts", 0.0) or 0.0),
        severity=str(row.get("severity", "advisory")),
        context=dict(row.get("context") or {}),
    )
