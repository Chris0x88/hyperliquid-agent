"""Tests for modules/feedback_store.py — event-sourced feedback + todos.

Covers:
- Legacy backwards-compat loading (the 21 entries on disk have no id/status)
- add → status defaults to open
- resolve/dismiss → event row appended, status reflects on reload
- tag → event row appended, tags accumulate
- Search returns substring matches, filtered by status
- Multiple status changes → most recent wins
- Original primary row never modified on disk
- Id resolver handles short prefixes
- Both feedback and todos stores share semantics
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules import feedback_store as fs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_legacy_feedback(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _read_raw(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fb_path(tmp_path: Path) -> Path:
    return tmp_path / "feedback.jsonl"


@pytest.fixture
def td_path(tmp_path: Path) -> Path:
    return tmp_path / "todos.jsonl"


# ---------------------------------------------------------------------------
# Backwards-compat loading
# ---------------------------------------------------------------------------


def test_load_legacy_rows_without_id_status_tags(fb_path: Path) -> None:
    """Legacy schema (timestamp+source+text only) loads cleanly.

    This mirrors the 21 rows already on disk in agent-cli/data/feedback.jsonl.
    Every field must be present after load. Default status is open.
    """
    _write_legacy_feedback(
        fb_path,
        [
            {
                "timestamp": "2026-04-02T06:20:33.378177+00:00",
                "source": "telegram",
                "text": "slash commands need an overhaul",
            },
            {
                "timestamp": "2026-04-02T06:22:12.912804+00:00",
                "source": "telegram",
                "text": "diag command shows zero tool calls",
            },
        ],
    )
    items = fs.load_feedback(fb_path)
    assert len(items) == 2
    assert all(i.status == "open" for i in items)
    assert all(i.tags == [] for i in items)
    assert all(i.id.startswith("fb_") for i in items)
    # Deterministic — same text + timestamp → same id across runs.
    assert items[0].id == fs._legacy_id(items[0].timestamp, items[0].text, "fb")


def test_legacy_resolved_field_maps_to_status(fb_path: Path) -> None:
    """Legacy rows with ``resolved: true`` are treated as resolved on read."""
    _write_legacy_feedback(
        fb_path,
        [
            {
                "timestamp": "2026-04-03T00:00:00+00:00",
                "source": "telegram",
                "text": "already resolved",
                "resolved": True,
            },
            {
                "timestamp": "2026-04-03T00:01:00+00:00",
                "source": "telegram",
                "text": "still open",
                "resolved": False,
            },
        ],
    )
    items = fs.load_feedback(fb_path)
    statuses = {i.text: i.status for i in items}
    assert statuses["already resolved"] == "resolved"
    assert statuses["still open"] == "open"


def test_legacy_id_is_deterministic(fb_path: Path) -> None:
    """Same (ts, text) produces the same id across two separate loads."""
    _write_legacy_feedback(
        fb_path,
        [
            {
                "timestamp": "2026-04-03T00:00:00+00:00",
                "source": "telegram",
                "text": "stable id please",
            }
        ],
    )
    id1 = fs.load_feedback(fb_path)[0].id
    id2 = fs.load_feedback(fb_path)[0].id
    assert id1 == id2


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------


def test_add_feedback_defaults_to_open(fb_path: Path) -> None:
    new_id = fs.add_feedback("brand new thing", path=fb_path)
    assert new_id.startswith("fb_")
    items = fs.load_feedback(fb_path)
    assert len(items) == 1
    assert items[0].id == new_id
    assert items[0].status == "open"
    assert items[0].tags == []


def test_add_feedback_with_tags(fb_path: Path) -> None:
    new_id = fs.add_feedback("tagged item", tags=["ux", "cli"], path=fb_path)
    item = fs.get_feedback(new_id, path=fb_path)
    assert item is not None
    assert sorted(item.tags) == ["cli", "ux"]


# ---------------------------------------------------------------------------
# Resolve / dismiss — event rows never rewrite primaries
# ---------------------------------------------------------------------------


def test_resolve_appends_event_row_preserves_primary(fb_path: Path) -> None:
    new_id = fs.add_feedback("fix this", path=fb_path)
    raw_before = _read_raw(fb_path)
    assert len(raw_before) == 1

    ok = fs.set_feedback_status(new_id, "resolved", note="fixed in abc123", path=fb_path)
    assert ok is True

    raw_after = _read_raw(fb_path)
    assert len(raw_after) == 2, "event row should be appended, not replace primary"

    # Primary row must be byte-identical to what we wrote.
    assert raw_after[0] == raw_before[0]

    # Event row carries the resolution metadata.
    event = raw_after[1]
    assert event["ref_id"] == new_id
    assert event["event"] == "status_change"
    assert event["from_status"] == "open"
    assert event["to_status"] == "resolved"
    assert event["note"] == "fixed in abc123"

    # Reloaded status reflects the event.
    item = fs.get_feedback(new_id, path=fb_path)
    assert item is not None
    assert item.status == "resolved"
    assert len(item.history) == 1


def test_dismiss_same_as_resolve_different_status(fb_path: Path) -> None:
    new_id = fs.add_feedback("wontfix thing", path=fb_path)
    ok = fs.set_feedback_status(new_id, "dismissed", path=fb_path)
    assert ok is True
    item = fs.get_feedback(new_id, path=fb_path)
    assert item is not None
    assert item.status == "dismissed"


def test_resolve_unknown_id_returns_false(fb_path: Path) -> None:
    fs.add_feedback("one item", path=fb_path)
    ok = fs.set_feedback_status("fb_nope", "resolved", path=fb_path)
    assert ok is False
    # File unchanged.
    raw = _read_raw(fb_path)
    assert len(raw) == 1


def test_multiple_status_changes_most_recent_wins(fb_path: Path) -> None:
    new_id = fs.add_feedback("changing mind", path=fb_path)
    fs.set_feedback_status(new_id, "resolved", path=fb_path)
    fs.set_feedback_status(new_id, "open", note="reopened", path=fb_path)
    fs.set_feedback_status(new_id, "dismissed", note="actually nope", path=fb_path)
    item = fs.get_feedback(new_id, path=fb_path)
    assert item is not None
    assert item.status == "dismissed"
    assert len(item.history) == 3
    # Original primary row still untouched.
    raw = _read_raw(fb_path)
    assert len(raw) == 4  # 1 primary + 3 events
    assert "event" not in raw[0]


def test_resolve_legacy_row(fb_path: Path) -> None:
    """Legacy rows without an id can still be resolved via their synthesised id."""
    _write_legacy_feedback(
        fb_path,
        [
            {
                "timestamp": "2026-04-02T06:20:33.378177+00:00",
                "source": "telegram",
                "text": "legacy item that needs resolving",
            }
        ],
    )
    item = fs.load_feedback(fb_path)[0]
    ok = fs.set_feedback_status(item.id, "resolved", path=fb_path)
    assert ok is True
    reloaded = fs.get_feedback(item.id, path=fb_path)
    assert reloaded is not None
    assert reloaded.status == "resolved"
    # The original legacy row on disk must be untouched.
    raw = _read_raw(fb_path)
    assert raw[0] == {
        "timestamp": "2026-04-02T06:20:33.378177+00:00",
        "source": "telegram",
        "text": "legacy item that needs resolving",
    }


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------


def test_tag_appends_event_row(fb_path: Path) -> None:
    new_id = fs.add_feedback("needs tag", path=fb_path)
    ok = fs.tag_feedback(new_id, "ux", path=fb_path)
    assert ok is True
    item = fs.get_feedback(new_id, path=fb_path)
    assert item is not None
    assert "ux" in item.tags


def test_tag_multiple_accumulates(fb_path: Path) -> None:
    new_id = fs.add_feedback("many tags", path=fb_path)
    fs.tag_feedback(new_id, "ux", path=fb_path)
    fs.tag_feedback(new_id, "cli", path=fb_path)
    fs.tag_feedback(new_id, "p1", path=fb_path)
    item = fs.get_feedback(new_id, path=fb_path)
    assert item is not None
    assert sorted(item.tags) == ["cli", "p1", "ux"]


def test_tag_duplicate_is_idempotent_on_read(fb_path: Path) -> None:
    """Tag event rows are append-only, but replay de-dupes on read."""
    new_id = fs.add_feedback("dup tags", path=fb_path)
    fs.tag_feedback(new_id, "ux", path=fb_path)
    fs.tag_feedback(new_id, "ux", path=fb_path)
    item = fs.get_feedback(new_id, path=fb_path)
    assert item is not None
    assert item.tags == ["ux"]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_substring_match(fb_path: Path) -> None:
    fs.add_feedback("slash commands need work", path=fb_path)
    fs.add_feedback("diag zero tool calls", path=fb_path)
    fs.add_feedback("feedback command list is empty", path=fb_path)

    matches = fs.search_feedback("slash", path=fb_path)
    assert len(matches) == 1
    assert "slash" in matches[0].text.lower()

    # Case-insensitive.
    matches = fs.search_feedback("DIAG", path=fb_path)
    assert len(matches) == 1


def test_search_status_filter(fb_path: Path) -> None:
    id1 = fs.add_feedback("open thing", path=fb_path)
    id2 = fs.add_feedback("resolved thing", path=fb_path)
    fs.set_feedback_status(id2, "resolved", path=fb_path)

    open_matches = fs.search_feedback("thing", status="open", path=fb_path)
    assert [m.id for m in open_matches] == [id1]

    resolved_matches = fs.search_feedback("thing", status="resolved", path=fb_path)
    assert [m.id for m in resolved_matches] == [id2]


def test_search_limit_returns_newest_first(fb_path: Path) -> None:
    for i in range(5):
        fs.add_feedback(f"item number {i}", path=fb_path)
    matches = fs.search_feedback("number", limit=3, path=fb_path)
    assert len(matches) == 3
    # Newest first = reversed append order = highest index first.
    assert "4" in matches[0].text
    assert "3" in matches[1].text
    assert "2" in matches[2].text


def test_search_empty_query_returns_all(fb_path: Path) -> None:
    fs.add_feedback("a", path=fb_path)
    fs.add_feedback("b", path=fb_path)
    matches = fs.search_feedback("", path=fb_path)
    assert len(matches) == 2


# ---------------------------------------------------------------------------
# Append-only contract — original row must NEVER be modified
# ---------------------------------------------------------------------------


def test_primary_row_is_never_modified_on_disk(fb_path: Path) -> None:
    new_id = fs.add_feedback("don't touch me", path=fb_path)
    original_row = _read_raw(fb_path)[0]

    # Pile on mutations.
    fs.set_feedback_status(new_id, "resolved", path=fb_path)
    fs.tag_feedback(new_id, "p1", path=fb_path)
    fs.set_feedback_status(new_id, "open", path=fb_path)
    fs.set_feedback_status(new_id, "dismissed", path=fb_path)

    raw = _read_raw(fb_path)
    assert raw[0] == original_row, "primary row bytes must be untouched"
    # All other rows are events.
    for row in raw[1:]:
        assert fs._is_event_row(row)


# ---------------------------------------------------------------------------
# Id resolver
# ---------------------------------------------------------------------------


def test_resolve_prefix_exact_match(fb_path: Path) -> None:
    new_id = fs.add_feedback("exact", path=fb_path)
    items = fs.load_feedback(fb_path)
    assert fs.resolve_prefix(new_id, items) is not None


def test_resolve_prefix_partial_unique(fb_path: Path) -> None:
    new_id = fs.add_feedback("partial", path=fb_path)
    items = fs.load_feedback(fb_path)
    # Last 4 chars should be unique for a single item.
    partial = new_id[-4:]
    match = fs.resolve_prefix(partial, items)
    assert match is not None
    assert match.id == new_id


def test_resolve_prefix_ambiguous_returns_none(fb_path: Path) -> None:
    fs.add_feedback("one", path=fb_path)
    fs.add_feedback("two", path=fb_path)
    items = fs.load_feedback(fb_path)
    # "fb_" is a prefix of every item — ambiguous.
    assert fs.resolve_prefix("fb_", items) is None


# ---------------------------------------------------------------------------
# Todos — same semantics, different file/prefix
# ---------------------------------------------------------------------------


def test_todos_add_and_done(td_path: Path) -> None:
    new_id = fs.add_todo("fix the chart labels", path=td_path)
    assert new_id.startswith("td_")
    item = fs.get_todo(new_id, path=td_path)
    assert item is not None
    assert item.status == "open"

    ok = fs.set_todo_status(new_id, "done", path=td_path)
    assert ok is True
    assert fs.get_todo(new_id, path=td_path).status == "done"


def test_todos_dismiss(td_path: Path) -> None:
    new_id = fs.add_todo("maybe later", path=td_path)
    fs.set_todo_status(new_id, "dismissed", path=td_path)
    assert fs.get_todo(new_id, path=td_path).status == "dismissed"


def test_todos_legacy_open_schema_loads(td_path: Path) -> None:
    """Legacy rows written by the pre-event cmd_todo had ``status: open`` inline."""
    _write_legacy_feedback(
        td_path,
        [
            {
                "timestamp": "2026-04-05T00:00:00+00:00",
                "source": "telegram",
                "text": "old todo",
                "status": "open",
            }
        ],
    )
    items = fs.load_todos(td_path)
    assert len(items) == 1
    assert items[0].status == "open"
    assert items[0].id.startswith("td_")


def test_todos_search(td_path: Path) -> None:
    fs.add_todo("migrate feedback to events", path=td_path)
    fs.add_todo("wire telegram subcommands", path=td_path)
    matches = fs.search_todos("feedback", path=td_path)
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# Missing file → empty load
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    ghost = tmp_path / "nope.jsonl"
    assert fs.load_feedback(ghost) == []
    assert fs.load_todos(ghost) == []
