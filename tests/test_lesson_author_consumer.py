"""Tests for the lesson candidate consumer (wedge 6).

Covers:
- _author_pending_lessons in cli/telegram_agent.py
  * empty candidate dir → no-op
  * happy path (mocked _call_anthropic): candidate → lesson row → candidate deleted
  * model returns malformed sentinels → failed counter, candidate left in place
  * empty model response → failed, candidate left
  * idempotency: duplicate journal_entry_id → skip + delete candidate
  * model raises → failed, candidate left
- /lessonauthorai Telegram command (5-surface registration)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import common.memory as common_memory
    monkeypatch.setattr(common_memory, "_DB_PATH", path)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_candidates(tmp_path):
    d = tmp_path / "lesson_candidates"
    d.mkdir()
    return d


def _candidate_dict(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "kind": "lesson_candidate",
        "created_at": "2026-04-09T05:00:00Z",
        "journal_entry": {
            "entry_id": "xyz:BRENTOIL-1712633100000",
            "instrument": "xyz:BRENTOIL",
            "direction": "long",
            "entry_price": 89.5,
            "exit_price": 91.2,
            "pnl": 17.0,
            "roe_pct": 1.9,
            "holding_ms": 3_600_000,
            "entry_source": "thesis_driven",
            "close_reason": "take_profit",
            "entry_ts": 1712629500000,
            "close_ts": 1712633100000,
            "retrospective": "Worked as planned.",
        },
        "thesis_snapshot": None,
        "thesis_snapshot_path": None,
        "learnings_md_slice": "",
        "news_context_at_open": "",
        "autoresearch_eval_window": "",
        "market": "xyz:BRENTOIL",
        "direction": "long",
        "signal_source": "thesis_driven",
        "pnl_usd": 17.0,
        "roe_pct": 1.9,
        "holding_ms": 3_600_000,
        "trade_closed_at": "2026-04-09T04:55:00Z",
        "journal_entry_id": "xyz:BRENTOIL-1712633100000",
    }
    base.update(overrides)
    return base


def _write_candidate(dir_: Path, name: str, **overrides) -> Path:
    path = dir_ / f"{name}.json"
    path.write_text(json.dumps(_candidate_dict(**overrides)))
    return path


def _valid_response(
    lesson_type: str = "entry_timing",
    summary: str = "BRENTOIL long on EIA draw — entry ahead of print, +1.9% in 1h.",
    tags: str = "supply-disruption, eia-confirmed",
) -> str:
    return (
        f"<<<LESSON_TYPE>>>\n{lesson_type}\n<<<END_LESSON_TYPE>>>\n\n"
        f"<<<LESSON_SUMMARY>>>\n{summary}\n<<<END_LESSON_SUMMARY>>>\n\n"
        f"<<<LESSON_TAGS>>>\n{tags}\n<<<END_LESSON_TAGS>>>\n\n"
        f"## Analysis\n\n(a) what happened: EIA confirmed the draw.\n"
    )


# ---------------------------------------------------------------------------
# _author_pending_lessons
# ---------------------------------------------------------------------------

class TestAuthorPendingLessonsHelper:
    def test_no_candidate_dir_is_noop(self, tmp_db, tmp_path):
        from telegram.agent import _author_pending_lessons
        result = _author_pending_lessons(
            candidate_dir=str(tmp_path / "missing"),
        )
        assert result == {"processed": 0, "failed": 0, "skipped": 0, "errors": []}

    def test_empty_dir_is_noop(self, tmp_db, tmp_candidates):
        from telegram.agent import _author_pending_lessons
        result = _author_pending_lessons(candidate_dir=str(tmp_candidates))
        assert result["processed"] == 0
        assert result["failed"] == 0

    def test_happy_path_authors_and_persists(self, tmp_db, tmp_candidates):
        from common import memory as common_memory
        path = _write_candidate(tmp_candidates, "test1")

        with patch(
            "telegram.agent._call_anthropic",
            return_value={"content": _valid_response()},
        ) as mock_call:
            from telegram.agent import _author_pending_lessons
            result = _author_pending_lessons(candidate_dir=str(tmp_candidates))

        assert result["processed"] == 1
        assert result["failed"] == 0
        assert not path.exists()  # candidate consumed

        # The model was called with Haiku
        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs.get("model_override") == "claude-haiku-4-5"

        # Lesson row landed
        rows = common_memory.search_lessons(query="EIA draw")
        assert len(rows) == 1
        assert rows[0]["market"] == "xyz:BRENTOIL"
        assert rows[0]["direction"] == "long"
        assert rows[0]["lesson_type"] == "entry_timing"
        assert rows[0]["journal_entry_id"] == "xyz:BRENTOIL-1712633100000"

    def test_max_lessons_limit(self, tmp_db, tmp_candidates):
        for i in range(5):
            _write_candidate(
                tmp_candidates,
                f"c{i}",
                journal_entry_id=f"id-{i}",
                journal_entry={"entry_id": f"id-{i}", "instrument": "xyz:BRENTOIL", "direction": "long",
                                "entry_price": 89, "exit_price": 90, "pnl": 5, "roe_pct": 1,
                                "holding_ms": 1000, "entry_source": "manual", "close_reason": "tp",
                                "entry_ts": 1, "close_ts": 2},
            )

        with patch("telegram.agent._call_anthropic", return_value={"content": _valid_response()}):
            from telegram.agent import _author_pending_lessons
            result = _author_pending_lessons(candidate_dir=str(tmp_candidates), max_lessons=2)

        assert result["processed"] == 2
        # 3 candidates remaining
        assert len(list(tmp_candidates.glob("*.json"))) == 3

    def test_malformed_response_leaves_candidate(self, tmp_db, tmp_candidates):
        path = _write_candidate(tmp_candidates, "bad")
        bad_response = "no sentinels here at all"

        with patch("telegram.agent._call_anthropic", return_value={"content": bad_response}):
            from telegram.agent import _author_pending_lessons
            result = _author_pending_lessons(candidate_dir=str(tmp_candidates))

        assert result["processed"] == 0
        assert result["failed"] == 1
        assert "parse failed" in result["errors"][0]
        assert path.exists()  # left in place for next run

    def test_empty_response_leaves_candidate(self, tmp_db, tmp_candidates):
        path = _write_candidate(tmp_candidates, "empty")

        with patch("telegram.agent._call_anthropic", return_value={"content": ""}):
            from telegram.agent import _author_pending_lessons
            result = _author_pending_lessons(candidate_dir=str(tmp_candidates))

        assert result["failed"] == 1
        assert "empty model response" in result["errors"][0]
        assert path.exists()

    def test_model_exception_leaves_candidate(self, tmp_db, tmp_candidates):
        path = _write_candidate(tmp_candidates, "boom")

        def raise_it(*a, **kw):
            raise RuntimeError("rate limit")

        with patch("telegram.agent._call_anthropic", side_effect=raise_it):
            from telegram.agent import _author_pending_lessons
            result = _author_pending_lessons(candidate_dir=str(tmp_candidates))

        assert result["failed"] == 1
        assert "model call failed" in result["errors"][0]
        assert path.exists()

    def test_idempotency_skips_duplicate(self, tmp_db, tmp_candidates):
        from common import memory as common_memory

        # Pre-seed a lesson with the same journal_entry_id
        common_memory.log_lesson({
            "created_at": "2026-04-09T01:00:00Z",
            "trade_closed_at": "2026-04-09T00:55:00Z",
            "market": "xyz:BRENTOIL",
            "direction": "long",
            "signal_source": "thesis_driven",
            "lesson_type": "entry_timing",
            "outcome": "win",
            "pnl_usd": 17.0,
            "roe_pct": 1.9,
            "holding_ms": 3_600_000,
            "conviction_at_open": None,
            "journal_entry_id": "xyz:BRENTOIL-1712633100000",
            "thesis_snapshot_path": None,
            "summary": "pre-seeded",
            "body_full": "pre-seeded body",
            "tags": [],
            "reviewed_by_chris": 0,
        })

        path = _write_candidate(tmp_candidates, "dup")

        with patch("telegram.agent._call_anthropic", return_value={"content": _valid_response()}) as mock_call:
            from telegram.agent import _author_pending_lessons
            result = _author_pending_lessons(candidate_dir=str(tmp_candidates))

        # The model still got called (we don't check duplicates before
        # calling — that would require an extra round trip), but the
        # lesson was NOT inserted twice. Candidate file is removed.
        assert mock_call.called
        assert result["processed"] == 0  # not counted as new
        assert not path.exists()

        # Still only one lesson with that journal_entry_id
        rows = common_memory.search_lessons(query="", limit=100)
        matches = [r for r in rows if r["journal_entry_id"] == "xyz:BRENTOIL-1712633100000"]
        assert len(matches) == 1
        assert matches[0]["summary"] == "pre-seeded"  # original wins

    def test_partial_batch(self, tmp_db, tmp_candidates):
        """Mix of good + bad candidates: good ones land, bad ones survive."""
        good = _write_candidate(
            tmp_candidates,
            "good",
            journal_entry_id="good-id",
            journal_entry={"entry_id": "good-id", "instrument": "xyz:BRENTOIL", "direction": "long",
                            "entry_price": 89, "exit_price": 90, "pnl": 5, "roe_pct": 1,
                            "holding_ms": 1000, "entry_source": "manual", "close_reason": "tp",
                            "entry_ts": 1, "close_ts": 2},
        )
        bad = _write_candidate(
            tmp_candidates,
            "bad",
            journal_entry_id="bad-id",
            journal_entry={"entry_id": "bad-id", "instrument": "xyz:BRENTOIL", "direction": "long",
                            "entry_price": 89, "exit_price": 90, "pnl": 5, "roe_pct": 1,
                            "holding_ms": 1000, "entry_source": "manual", "close_reason": "tp",
                            "entry_ts": 1, "close_ts": 2},
        )

        # Alternate between valid and broken responses
        responses = [{"content": _valid_response()}, {"content": "broken"}]

        with patch("telegram.agent._call_anthropic", side_effect=responses):
            from telegram.agent import _author_pending_lessons
            result = _author_pending_lessons(candidate_dir=str(tmp_candidates))

        assert result["processed"] == 1
        assert result["failed"] == 1
        # Sorted glob → 'bad' before 'good' → bad gets the valid response, good gets broken
        # Either way: exactly one candidate remains, exactly one lesson row exists
        remaining = list(tmp_candidates.glob("*.json"))
        assert len(remaining) == 1


# ---------------------------------------------------------------------------
# /lessonauthorai Telegram command
# ---------------------------------------------------------------------------

def _body(send) -> str:
    return send.call_args[0][2]


class TestCmdLessonauthorai:
    def test_no_candidates(self, tmp_db, tmp_path, monkeypatch):
        # Point the helper at an empty dir via patching
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch("telegram.agent._author_pending_lessons", return_value={
            "processed": 0, "failed": 0, "skipped": 0, "errors": [],
        }):
            with patch("telegram.bot.tg_send") as send:
                from telegram.bot import cmd_lessonauthorai
                cmd_lessonauthorai("tok", "chat", "")
                assert "No pending lesson candidates" in _body(send)

    def test_invalid_arg(self, tmp_db):
        with patch("telegram.bot.tg_send") as send:
            from telegram.bot import cmd_lessonauthorai
            cmd_lessonauthorai("tok", "chat", "abc")
            assert "Usage" in _body(send)

    def test_default_count(self, tmp_db):
        with patch("telegram.agent._author_pending_lessons", return_value={
            "processed": 2, "failed": 0, "skipped": 0, "errors": [],
        }) as mock_helper:
            with patch("telegram.bot.tg_send") as send:
                from telegram.bot import cmd_lessonauthorai
                cmd_lessonauthorai("tok", "chat", "")
                # Default max_lessons is 3
                assert mock_helper.call_args.kwargs["max_lessons"] == 3
                assert "2 authored" in _body(send)
                assert "✅" in _body(send)

    def test_explicit_count(self, tmp_db):
        with patch("telegram.agent._author_pending_lessons", return_value={
            "processed": 5, "failed": 0, "skipped": 0, "errors": [],
        }) as mock_helper:
            with patch("telegram.bot.tg_send"):
                from telegram.bot import cmd_lessonauthorai
                cmd_lessonauthorai("tok", "chat", "5")
                assert mock_helper.call_args.kwargs["max_lessons"] == 5

    def test_all_count(self, tmp_db):
        with patch("telegram.agent._author_pending_lessons", return_value={
            "processed": 25, "failed": 0, "skipped": 0, "errors": [],
        }) as mock_helper:
            with patch("telegram.bot.tg_send"):
                from telegram.bot import cmd_lessonauthorai
                cmd_lessonauthorai("tok", "chat", "all")
                assert mock_helper.call_args.kwargs["max_lessons"] == 25

    def test_count_clamped_to_25(self, tmp_db):
        with patch("telegram.agent._author_pending_lessons", return_value={
            "processed": 25, "failed": 0, "skipped": 0, "errors": [],
        }) as mock_helper:
            with patch("telegram.bot.tg_send"):
                from telegram.bot import cmd_lessonauthorai
                cmd_lessonauthorai("tok", "chat", "1000")
                assert mock_helper.call_args.kwargs["max_lessons"] == 25

    def test_failures_listed_in_response(self, tmp_db):
        with patch("telegram.agent._author_pending_lessons", return_value={
            "processed": 1,
            "failed": 2,
            "skipped": 0,
            "errors": ["c1.json: parse failed", "c2.json: model call failed"],
        }):
            with patch("telegram.bot.tg_send") as send:
                from telegram.bot import cmd_lessonauthorai
                cmd_lessonauthorai("tok", "chat", "")
                body = _body(send)
                assert "1 authored" in body
                assert "2 failed" in body
                assert "parse failed" in body
                assert "model call failed" in body

    def test_helper_exception_returns_friendly_error(self, tmp_db):
        with patch("telegram.agent._author_pending_lessons", side_effect=RuntimeError("boom")):
            with patch("telegram.bot.tg_send") as send:
                from telegram.bot import cmd_lessonauthorai
                cmd_lessonauthorai("tok", "chat", "")
                assert "Authoring failed" in _body(send)
                assert "boom" in _body(send)


# ---------------------------------------------------------------------------
# Registration surfaces
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_handlers_dict_has_slash_and_bare(self):
        from telegram.bot import HANDLERS
        assert "/lessonauthorai" in HANDLERS
        assert "lessonauthorai" in HANDLERS

    def test_handler_points_at_command(self):
        from telegram.bot import HANDLERS, cmd_lessonauthorai
        assert HANDLERS["/lessonauthorai"] is cmd_lessonauthorai
        assert HANDLERS["lessonauthorai"] is cmd_lessonauthorai

    def test_cmd_help_lists_lessonauthorai(self):
        with patch("telegram.bot.tg_send") as send:
            from telegram.bot import cmd_help
            cmd_help("tok", "chat", "")
            assert "/lessonauthorai" in _body(send)

    def test_cmd_guide_lists_lessonauthorai(self):
        with patch("telegram.bot.tg_send") as send:
            from telegram.bot import cmd_guide
            cmd_guide("tok", "chat", "")
            assert "/lessonauthorai" in _body(send)

    def test_ai_suffix_present(self):
        """Per CLAUDE.md slash-command rule, the AI-dependent command must
        carry the `ai` suffix."""
        from telegram.bot import HANDLERS
        assert any(name.endswith("ai") and "lesson" in name for name in HANDLERS)
