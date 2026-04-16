"""Tests for /lessons, /lesson, and /lessonsearch Telegram commands.

Patches `tg_send` to capture outbound message bodies. Uses a temp memory.db
via monkeypatch — common.memory helpers resolve _DB_PATH at call time as of
5382a0b, so the handlers naturally hit the temp DB.
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest

from telegram.bot import cmd_lessons, cmd_lesson, cmd_lessonsearch


@pytest.fixture
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import common.memory as common_memory
    monkeypatch.setattr(common_memory, "_DB_PATH", path)
    yield path
    os.unlink(path)


def _seed(**overrides) -> int:
    from common import memory as common_memory
    base = {
        "created_at": "2026-04-09T05:00:00Z",
        "trade_closed_at": "2026-04-09T04:55:00Z",
        "market": "xyz:BRENTOIL",
        "direction": "long",
        "signal_source": "thesis_driven",
        "lesson_type": "entry_timing",
        "outcome": "win",
        "pnl_usd": 123.45,
        "roe_pct": 8.7,
        "holding_ms": 3_600_000,
        "conviction_at_open": 0.72,
        "journal_entry_id": "xyz:BRENTOIL-1",
        "thesis_snapshot_path": None,
        "summary": "BRENTOIL long on EIA draw, +8.7% in 1h.",
        "body_full": "## Analysis\n\n(a) what happened: EIA confirmed.\n",
        "tags": ["supply-disruption"],
        "reviewed_by_chris": 0,
    }
    base.update(overrides)
    return common_memory.log_lesson(base)


def _body(send) -> str:
    """Extract the message body from the most recent tg_send call."""
    return send.call_args[0][2]


# ---------------------------------------------------------------------------
# /lessons
# ---------------------------------------------------------------------------

class TestCmdLessons:
    def test_empty_corpus_shows_friendly_message(self, tmp_db):
        with patch("telegram.bot.tg_send") as send:
            cmd_lessons("tok", "chat", "")
            assert send.call_count == 1
            assert "No lessons" in _body(send)

    def test_lists_recent_lessons(self, tmp_db):
        _seed(summary="first lesson", trade_closed_at="2026-04-09T12:00:00Z")
        _seed(summary="second lesson", trade_closed_at="2026-04-08T12:00:00Z")
        with patch("telegram.bot.tg_send") as send:
            cmd_lessons("tok", "chat", "")
            body = _body(send)
            assert "first lesson" in body
            assert "second lesson" in body
            assert "#1" in body and "#2" in body
            # Recency: first lesson before second
            assert body.index("first lesson") < body.index("second lesson")

    def test_limit_argument(self, tmp_db):
        for i in range(15):
            _seed(summary=f"lesson {i}", trade_closed_at=f"2026-04-0{i % 9 + 1}T12:00:00Z")
        with patch("telegram.bot.tg_send") as send:
            cmd_lessons("tok", "chat", "5")
            body = _body(send)
            # Header says 5 lessons
            assert "Latest 5" in body

    def test_limit_clamped_to_25(self, tmp_db):
        for i in range(30):
            _seed(summary=f"lesson {i}", trade_closed_at=f"2026-04-0{i % 9 + 1}T12:00:00Z")
        with patch("telegram.bot.tg_send") as send:
            cmd_lessons("tok", "chat", "1000")
            body = _body(send)
            # Capped at 25
            assert "Latest 25" in body

    def test_invalid_limit_uses_default(self, tmp_db):
        _seed()
        with patch("telegram.bot.tg_send") as send:
            cmd_lessons("tok", "chat", "abc")
            assert send.call_count == 1  # didn't crash

    def test_approved_flag_shown(self, tmp_db):
        from common import memory as common_memory
        rid = _seed(summary="approved one")
        common_memory.set_lesson_review(rid, 1)
        with patch("telegram.bot.tg_send") as send:
            cmd_lessons("tok", "chat", "")
            assert "✅" in _body(send)

    def test_rejected_excluded_by_default(self, tmp_db):
        from common import memory as common_memory
        rid_r = _seed(summary="rejected one")
        _seed(summary="kept one")
        common_memory.set_lesson_review(rid_r, -1)
        with patch("telegram.bot.tg_send") as send:
            cmd_lessons("tok", "chat", "")
            body = _body(send)
            assert "kept one" in body
            assert "rejected one" not in body


# ---------------------------------------------------------------------------
# /lesson
# ---------------------------------------------------------------------------

class TestCmdLessonRead:
    def test_no_args_shows_usage(self, tmp_db):
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", "")
            assert "Usage" in _body(send)

    def test_invalid_id_shows_error(self, tmp_db):
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", "abc")
            assert "Invalid id" in _body(send)

    def test_missing_id_returns_not_found(self, tmp_db):
        _seed()  # ensure schema exists
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", "999")
            assert "not found" in _body(send).lower()

    def test_returns_full_body(self, tmp_db):
        rid = _seed()
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", str(rid))
            body = _body(send)
            assert f"Lesson #{rid}" in body
            assert "xyz:BRENTOIL" in body
            assert "thesis_driven" in body
            assert "(a) what happened" in body
            assert "Verbatim body" in body

    def test_renders_tags(self, tmp_db):
        rid = _seed(tags=["fed-day", "false-breakout"])
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", str(rid))
            body = _body(send)
            assert "fed-day" in body
            assert "false-breakout" in body

    def test_renders_review_status(self, tmp_db):
        from common import memory as common_memory
        rid = _seed()
        common_memory.set_lesson_review(rid, 1)
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", str(rid))
            assert "approved" in _body(send)

    def test_long_body_truncated(self, tmp_db):
        rid = _seed(body_full="x" * 5000)
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", str(rid))
            body = _body(send)
            assert "truncated" in body
            # Total message stays under telegram cap
            assert len(body) < 4096


class TestCmdLessonCuration:
    def test_approve(self, tmp_db):
        from common import memory as common_memory
        rid = _seed()
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", f"approve {rid}")
            assert "approved" in _body(send)
        assert common_memory.get_lesson(rid)["reviewed_by_chris"] == 1

    def test_reject(self, tmp_db):
        from common import memory as common_memory
        rid = _seed()
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", f"reject {rid}")
            assert "rejected" in _body(send)
        assert common_memory.get_lesson(rid)["reviewed_by_chris"] == -1

    def test_unreview(self, tmp_db):
        from common import memory as common_memory
        rid = _seed(reviewed_by_chris=1)
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", f"unreview {rid}")
            assert "unreviewed" in _body(send)
        assert common_memory.get_lesson(rid)["reviewed_by_chris"] == 0

    def test_curate_missing_id(self, tmp_db):
        _seed()
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", "approve 999")
            assert "not found" in _body(send).lower()

    def test_curate_missing_arg(self, tmp_db):
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", "approve")
            assert "Usage" in _body(send)

    def test_curate_invalid_id(self, tmp_db):
        with patch("telegram.bot.tg_send") as send:
            cmd_lesson("tok", "chat", "approve abc")
            assert "Invalid id" in _body(send)


# ---------------------------------------------------------------------------
# /lessonsearch
# ---------------------------------------------------------------------------

class TestCmdLessonsearch:
    def test_no_query_shows_usage(self, tmp_db):
        with patch("telegram.bot.tg_send") as send:
            cmd_lessonsearch("tok", "chat", "")
            assert "Usage" in _body(send)

    def test_no_hits(self, tmp_db):
        _seed(summary="brent supply story")
        with patch("telegram.bot.tg_send") as send:
            cmd_lessonsearch("tok", "chat", "nonexistent xyzzy term")
            assert "No lessons match" in _body(send)

    def test_returns_hits(self, tmp_db):
        _seed(
            summary="weekend wick stopped us out",
            body_full="Weekend wick took the stop.",
            tags=["weekend-wick"],
        )
        _seed(
            summary="CPI catalyst played out",
            body_full="CPI thesis confirmed.",
            tags=["cpi"],
            market="xyz:GOLD",
        )
        with patch("telegram.bot.tg_send") as send:
            cmd_lessonsearch("tok", "chat", "weekend wick")
            body = _body(send)
            assert "weekend wick stopped" in body
            assert "CPI catalyst" not in body
            assert "1 hit" in body or "Search:" in body

    def test_injection_resistance(self, tmp_db):
        _seed()
        for bad in ['" OR 1=1', "*", "(foo)", "NOT AND OR"]:
            with patch("telegram.bot.tg_send") as send:
                cmd_lessonsearch("tok", "chat", bad)
                assert send.call_count == 1  # never crashes


# ---------------------------------------------------------------------------
# Registration surfaces
# ---------------------------------------------------------------------------

class TestRegistrationSurfaces:
    def test_handlers_dict_has_slash_and_bare(self):
        from telegram.bot import HANDLERS
        for cmd in ("lessons", "lesson", "lessonsearch"):
            assert f"/{cmd}" in HANDLERS, f"/{cmd} missing from HANDLERS"
            assert cmd in HANDLERS, f"bare '{cmd}' missing from HANDLERS"

    def test_handlers_point_at_lesson_funcs(self):
        from telegram.bot import HANDLERS, cmd_lessons, cmd_lesson, cmd_lessonsearch
        assert HANDLERS["/lessons"] is cmd_lessons
        assert HANDLERS["/lesson"] is cmd_lesson
        assert HANDLERS["/lessonsearch"] is cmd_lessonsearch

    def test_cmd_help_lists_lesson_commands(self):
        with patch("telegram.bot.tg_send") as send:
            from telegram.bot import cmd_help
            cmd_help("tok", "chat", "")
            body = _body(send)
            assert "/lessons" in body
            assert "/lesson" in body
            assert "/lessonsearch" in body

    def test_cmd_guide_lists_lesson_commands(self):
        with patch("telegram.bot.tg_send") as send:
            from telegram.bot import cmd_guide
            cmd_guide("tok", "chat", "")
            body = _body(send)
            assert "/lessons" in body
            assert "/lessonsearch" in body
