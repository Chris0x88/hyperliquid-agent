"""Tests for modules.action_queue — the pure-logic nudge ledger.

Covers:
  - ActionItem dataclass: is_overdue / days_overdue / escalated_severity
    dispatch by kind (time, threshold, per-session)
  - ActionQueue load/save round-trip
  - Seed-defaults merge: schema additions land on next load, custom items
    survive across restarts
  - mark_done + mark_nudged timestamps
  - evaluate() filters by overdue + 24h nudge cooldown + drops per-session
  - all_overdue() returns everything regardless of cooldown
  - format_nudge_telegram() groups by severity and formats details
  - Nudge cooldown: back-to-back evaluates don't re-surface the same item
  - Each cadence type: weekly, quarterly, when_pending_gt
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from modules.action_queue import (
    NUDGE_COOLDOWN_S,
    ActionItem,
    ActionQueue,
    default_action_items,
    format_nudge_telegram,
)


DAY_S = 86_400


# ── ActionItem dispatch ──────────────────────────────────────────────────


class TestActionItemOverdue:
    def test_time_based_never_done_is_overdue(self):
        item = ActionItem(id="x", kind="brutal_review", description="", cadence_days=7)
        assert item.is_overdue(now_ts=1000.0) is True
        # days_overdue for never-done returns the cadence as the baseline
        assert item.days_overdue(now_ts=1000.0) == pytest.approx(7.0)

    def test_time_based_inside_cadence_not_overdue(self):
        now = 10_000_000.0
        item = ActionItem(
            id="x", kind="brutal_review", description="", cadence_days=7,
            last_done_ts=now - 3 * DAY_S,
        )
        assert item.is_overdue(now) is False
        assert item.days_overdue(now) == pytest.approx(0.0)

    def test_time_based_past_cadence_is_overdue(self):
        now = 10_000_000.0
        item = ActionItem(
            id="x", kind="brutal_review", description="", cadence_days=7,
            last_done_ts=now - 8 * DAY_S,
        )
        assert item.is_overdue(now) is True
        assert item.days_overdue(now) == pytest.approx(1.0)

    def test_quarterly_cadence(self):
        now = 100_000_000.0
        item = ActionItem(
            id="x", kind="restore_drill", description="", cadence_days=90,
            last_done_ts=now - 85 * DAY_S,
        )
        assert item.is_overdue(now) is False
        item2 = ActionItem(
            id="x", kind="restore_drill", description="", cadence_days=90,
            last_done_ts=now - 91 * DAY_S,
        )
        assert item2.is_overdue(now) is True

    def test_threshold_kind_below_threshold(self):
        item = ActionItem(
            id="x", kind="lesson_approval_queue", description="", cadence_days=5,
            context={"pending_count": 3},
        )
        assert item.is_overdue(now_ts=1000.0) is False

    def test_threshold_kind_at_threshold(self):
        item = ActionItem(
            id="x", kind="lesson_approval_queue", description="", cadence_days=5,
            context={"pending_count": 5},
        )
        assert item.is_overdue(now_ts=1000.0) is True

    def test_threshold_kind_bad_context_treated_as_zero(self):
        item = ActionItem(
            id="x", kind="lesson_approval_queue", description="", cadence_days=5,
            context={"pending_count": "not-a-number"},
        )
        assert item.is_overdue(now_ts=1000.0) is False

    def test_per_session_kind_always_overdue(self):
        item = ActionItem(
            id="x", kind="alignment_ritual", description="", cadence_days=0,
        )
        assert item.is_overdue(now_ts=1000.0) is True


class TestEscalatedSeverity:
    def test_time_based_within_cadence_returns_base(self):
        now = 10_000_000.0
        item = ActionItem(
            id="x", kind="brutal_review", description="", cadence_days=7,
            severity="advisory",
            last_done_ts=now - 2 * DAY_S,
        )
        assert item.escalated_severity(now) == "advisory"

    def test_time_based_1x_overdue_becomes_warning(self):
        now = 10_000_000.0
        # 7d cadence, last done 15d ago => overdue by 8d => >= cadence => warning
        item = ActionItem(
            id="x", kind="brutal_review", description="", cadence_days=7,
            severity="advisory",
            last_done_ts=now - 15 * DAY_S,
        )
        assert item.escalated_severity(now) == "warning"

    def test_time_based_2x_overdue_becomes_overdue(self):
        now = 10_000_000.0
        # 7d cadence, last done 30d ago => overdue by 23d => >= 2*cadence => overdue
        item = ActionItem(
            id="x", kind="brutal_review", description="", cadence_days=7,
            severity="advisory",
            last_done_ts=now - 30 * DAY_S,
        )
        assert item.escalated_severity(now) == "overdue"

    def test_threshold_escalates_with_count(self):
        base = {"id": "x", "kind": "lesson_approval_queue", "description": "",
                "cadence_days": 5, "severity": "advisory"}
        at = ActionItem(**base, context={"pending_count": 5})
        mid = ActionItem(**base, context={"pending_count": 8})
        high = ActionItem(**base, context={"pending_count": 12})
        assert at.escalated_severity(1000.0) == "advisory"
        assert mid.escalated_severity(1000.0) == "warning"
        assert high.escalated_severity(1000.0) == "overdue"

    def test_per_session_returns_base_severity(self):
        item = ActionItem(
            id="x", kind="alignment_ritual", description="", cadence_days=0,
            severity="advisory",
        )
        assert item.escalated_severity(1000.0) == "advisory"


# ── ActionQueue load/save ────────────────────────────────────────────────


class TestLoadSaveRoundtrip:
    def test_fresh_load_seeds_defaults(self, tmp_path):
        q = ActionQueue(state_path=str(tmp_path / "q.jsonl"))
        q.load()
        ids = [i.id for i in q.items]
        # All seeds present, order preserved
        expected = [i.id for i in default_action_items()]
        assert ids == expected

    def test_save_then_load_preserves_state(self, tmp_path):
        path = tmp_path / "q.jsonl"
        q1 = ActionQueue(state_path=str(path))
        q1.load()
        q1.mark_done("brutal_review", now_ts=9999.0)
        q1.save()

        q2 = ActionQueue(state_path=str(path))
        q2.load()
        assert q2.get("brutal_review").last_done_ts == 9999.0

    def test_load_merges_new_seeds_over_existing_file(self, tmp_path):
        """If the JSONL file is missing some seed items, load() appends them."""
        path = tmp_path / "q.jsonl"
        # Write a partial file that only has one item
        path.write_text(
            json.dumps({
                "id": "brutal_review",
                "kind": "brutal_review",
                "description": "stale description",
                "cadence_days": 7,
                "last_done_ts": 5000.0,
                "last_nudged_ts": 0.0,
                "severity": "advisory",
                "context": {},
            }) + "\n"
        )
        q = ActionQueue(state_path=str(path))
        q.load()
        # All seeds appear
        ids = {i.id for i in q.items}
        expected = {i.id for i in default_action_items()}
        assert expected.issubset(ids)
        # The overlapping one kept its on-disk timestamp
        assert q.get("brutal_review").last_done_ts == 5000.0

    def test_load_preserves_custom_items(self, tmp_path):
        path = tmp_path / "q.jsonl"
        q = ActionQueue(state_path=str(path))
        q.load()
        custom = ActionItem(
            id="custom_check",
            kind="custom_check",
            description="user-added check",
            cadence_days=30,
        )
        q.upsert(custom)
        q.save()

        q2 = ActionQueue(state_path=str(path))
        q2.load()
        assert q2.get("custom_check") is not None
        assert q2.get("custom_check").description == "user-added check"

    def test_load_skips_garbage_lines(self, tmp_path):
        path = tmp_path / "q.jsonl"
        path.write_text(
            "{not json\n"
            + json.dumps({"missing": "required_fields"}) + "\n"
            + json.dumps({
                "id": "brutal_review",
                "kind": "brutal_review",
                "description": "ok",
                "cadence_days": 7,
            }) + "\n"
        )
        q = ActionQueue(state_path=str(path))
        q.load()  # should not raise
        assert q.get("brutal_review") is not None


# ── Mutations ────────────────────────────────────────────────────────────


class TestMutations:
    def test_mark_done_updates_timestamp_and_clears_nudge(self, tmp_path):
        q = ActionQueue(state_path=str(tmp_path / "q.jsonl"))
        q.load()
        q.mark_nudged("brutal_review", now_ts=1000.0)
        assert q.get("brutal_review").last_nudged_ts == 1000.0

        q.mark_done("brutal_review", now_ts=2000.0)
        item = q.get("brutal_review")
        assert item.last_done_ts == 2000.0
        assert item.last_nudged_ts == 0.0

    def test_mark_done_unknown_id_returns_false(self, tmp_path):
        q = ActionQueue(state_path=str(tmp_path / "q.jsonl"))
        q.load()
        assert q.mark_done("no_such_id") is False

    def test_set_context_replaces_payload(self, tmp_path):
        q = ActionQueue(state_path=str(tmp_path / "q.jsonl"))
        q.load()
        q.set_context("lesson_approval_queue", {"pending_count": 12})
        assert q.get("lesson_approval_queue").context["pending_count"] == 12

    def test_remove(self, tmp_path):
        q = ActionQueue(state_path=str(tmp_path / "q.jsonl"))
        q.load()
        assert q.remove("brutal_review") is True
        assert q.get("brutal_review") is None
        assert q.remove("brutal_review") is False  # idempotent


# ── Evaluate / cooldown ─────────────────────────────────────────────────


class TestEvaluate:
    def _fresh_queue(self, tmp_path) -> ActionQueue:
        q = ActionQueue(state_path=str(tmp_path / "q.jsonl"))
        q.load()
        return q

    def test_never_done_items_are_overdue_on_first_evaluate(self, tmp_path):
        q = self._fresh_queue(tmp_path)
        overdue = q.evaluate(now_ts=1_000_000.0)
        # Every non-per-session seed item starts overdue (never done)
        ids = {i.id for i in overdue}
        assert "brutal_review" in ids
        assert "restore_drill" in ids
        assert "feedback_review" in ids
        # alignment_ritual is per-session → NOT auto-nudged
        assert "alignment_ritual" not in ids
        # lesson_approval_queue defaults to pending_count=0 so not overdue
        assert "lesson_approval_queue" not in ids

    def test_nudge_cooldown_suppresses_repeat(self, tmp_path):
        q = self._fresh_queue(tmp_path)
        now = 1_000_000.0
        first = q.evaluate(now_ts=now)
        assert first  # something overdue
        # Simulate the iterator marking them nudged
        for item in first:
            q.mark_nudged(item.id, now_ts=now)
        # Back-to-back call returns nothing for any recently nudged item
        second = q.evaluate(now_ts=now + 60)
        assert second == []

    def test_nudge_cooldown_expires_after_24h(self, tmp_path):
        q = self._fresh_queue(tmp_path)
        now = 1_000_000.0
        for item in q.evaluate(now_ts=now):
            q.mark_nudged(item.id, now_ts=now)
        # 24h + 1s later: cooldown expired
        later = now + NUDGE_COOLDOWN_S + 1
        second = q.evaluate(now_ts=later)
        assert second  # overdue items come back

    def test_threshold_item_respects_pending_count(self, tmp_path):
        q = self._fresh_queue(tmp_path)
        now = 1_000_000.0
        # default pending_count == 0 → not overdue
        overdue_ids = {i.id for i in q.evaluate(now_ts=now)}
        assert "lesson_approval_queue" not in overdue_ids
        # Bump context above threshold (5)
        q.set_context("lesson_approval_queue", {"pending_count": 10})
        overdue_ids = {i.id for i in q.evaluate(now_ts=now)}
        assert "lesson_approval_queue" in overdue_ids

    def test_all_overdue_includes_per_session(self, tmp_path):
        q = self._fresh_queue(tmp_path)
        ids = {i.id for i in q.all_overdue(now_ts=1000.0)}
        assert "alignment_ritual" in ids

    def test_mark_done_removes_item_from_overdue(self, tmp_path):
        q = self._fresh_queue(tmp_path)
        now = 1_000_000.0
        q.mark_done("brutal_review", now_ts=now)
        overdue_ids = {i.id for i in q.evaluate(now_ts=now + 60)}
        assert "brutal_review" not in overdue_ids


# ── Telegram formatting ──────────────────────────────────────────────────


class TestFormatNudge:
    def test_empty_list(self):
        out = format_nudge_telegram([])
        assert "nothing overdue" in out

    def test_contains_each_item_and_severity_groups(self):
        now = 100_000_000.0
        items = [
            ActionItem(
                id="brutal_review", kind="brutal_review",
                description="weekly audit", cadence_days=7,
                last_done_ts=now - 15 * DAY_S,  # warning
            ),
            ActionItem(
                id="restore_drill", kind="restore_drill",
                description="memory restore drill", cadence_days=90,
                last_done_ts=now - 300 * DAY_S,  # 2x+ overdue (300 > 2*90)
            ),
            ActionItem(
                id="feedback_review", kind="feedback_review",
                description="feedback triage", cadence_days=7,
                last_done_ts=now - 8 * DAY_S,  # advisory
            ),
            ActionItem(
                id="lesson_approval_queue", kind="lesson_approval_queue",
                description="lessons", cadence_days=5,
                context={"pending_count": 8},  # warning (>= 1.5x)
            ),
        ]
        text = format_nudge_telegram(items, now_ts=now)
        assert "Action queue nudge" in text
        assert "brutal_review" in text
        assert "restore_drill" in text
        assert "feedback_review" in text
        assert "lesson_approval_queue" in text
        # Each severity label appears at most once in the output
        assert text.count("*OVERDUE*") == 1
        assert text.count("*WARNING*") == 1
        assert text.count("*ADVISORY*") == 1
        # Threshold item shows pending count in the detail line
        assert "pending count = 8" in text
        # Footer prompts the mark-done flow
        assert "/nudge done" in text

    def test_threshold_item_detail_mentions_threshold(self):
        now = 100_000_000.0
        items = [
            ActionItem(
                id="x", kind="lesson_approval_queue",
                description="lessons", cadence_days=5,
                context={"pending_count": 7},
            ),
        ]
        text = format_nudge_telegram(items, now_ts=now)
        assert "threshold 5" in text
