"""Tests for the lessons table and helpers in common/memory.py.

Covers schema migration, insert roundtrip, BM25 ranking via FTS5, filter
combinations, curation (approve/reject), and the append-only trigger.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from common.memory import (
    _init,
    get_lesson,
    log_lesson,
    search_lessons,
    set_lesson_review,
)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


def _base_lesson(**overrides) -> dict:
    d = {
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
        "journal_entry_id": "xyz:BRENTOIL-1712633100000",
        "thesis_snapshot_path": "data/thesis_snapshots/xyz_brentoil_20260409.json",
        "summary": "BRENTOIL long on EIA draw, entry ahead of print, +8.7% in 1h.",
        "body_full": "## Analysis\n\n(a) what happened: EIA draw confirmed at 10:30.",
        "tags": ["supply-disruption", "eia-confirmed"],
        "reviewed_by_chris": 0,
    }
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

class TestSchema:
    def test_tables_created_on_first_write(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        assert rid > 0

        con = sqlite3.connect(tmp_db)
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "lessons" in tables
        assert "lessons_fts" in tables

    def test_indexes_created(self, tmp_db):
        log_lesson(_base_lesson(), db_path=tmp_db)
        con = sqlite3.connect(tmp_db)
        indexes = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        for expected in (
            "idx_lessons_market_dir",
            "idx_lessons_signal",
            "idx_lessons_type",
            "idx_lessons_closed",
        ):
            assert expected in indexes

    def test_triggers_created(self, tmp_db):
        log_lesson(_base_lesson(), db_path=tmp_db)
        con = sqlite3.connect(tmp_db)
        triggers = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert "lessons_ai" in triggers
        assert "lessons_append_only" in triggers
        assert "lessons_tags_au" in triggers

    def test_migration_is_idempotent(self, tmp_db):
        # Run _init twice directly; should not raise
        con = sqlite3.connect(tmp_db)
        _init(con)
        _init(con)
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        assert rid > 0


# ---------------------------------------------------------------------------
# Insert + get roundtrip
# ---------------------------------------------------------------------------

class TestLogAndGetLesson:
    def test_roundtrip(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        row = get_lesson(rid, db_path=tmp_db)
        assert row is not None
        assert row["id"] == rid
        assert row["market"] == "xyz:BRENTOIL"
        assert row["direction"] == "long"
        assert row["signal_source"] == "thesis_driven"
        assert row["outcome"] == "win"
        assert row["pnl_usd"] == 123.45
        assert row["roe_pct"] == 8.7
        assert row["summary"].startswith("BRENTOIL long on EIA draw")
        assert row["journal_entry_id"] == "xyz:BRENTOIL-1712633100000"
        assert row["reviewed_by_chris"] == 0
        # Tags come back as a JSON string (raw SQLite column)
        assert json.loads(row["tags"]) == ["supply-disruption", "eia-confirmed"]

    def test_get_missing_returns_none(self, tmp_db):
        assert get_lesson(999, db_path=tmp_db) is None

    def test_optional_nullable_fields(self, tmp_db):
        lesson = _base_lesson(
            conviction_at_open=None,
            journal_entry_id=None,
            thesis_snapshot_path=None,
        )
        rid = log_lesson(lesson, db_path=tmp_db)
        row = get_lesson(rid, db_path=tmp_db)
        assert row["conviction_at_open"] is None
        assert row["journal_entry_id"] is None
        assert row["thesis_snapshot_path"] is None

    def test_tags_accepts_json_string_input(self, tmp_db):
        lesson = _base_lesson(tags='["weekend-wick","stop-hunt"]')
        rid = log_lesson(lesson, db_path=tmp_db)
        row = get_lesson(rid, db_path=tmp_db)
        assert json.loads(row["tags"]) == ["weekend-wick", "stop-hunt"]

    def test_tags_empty_list(self, tmp_db):
        rid = log_lesson(_base_lesson(tags=[]), db_path=tmp_db)
        row = get_lesson(rid, db_path=tmp_db)
        assert row["tags"] == "[]"

    def test_invalid_direction_raises(self, tmp_db):
        lesson = _base_lesson(direction="diagonal")
        with pytest.raises(sqlite3.IntegrityError):
            log_lesson(lesson, db_path=tmp_db)

    def test_invalid_outcome_raises(self, tmp_db):
        lesson = _base_lesson(outcome="meh")
        with pytest.raises(sqlite3.IntegrityError):
            log_lesson(lesson, db_path=tmp_db)


# ---------------------------------------------------------------------------
# FTS5 search + BM25 ranking
# ---------------------------------------------------------------------------

class TestSearchLessons:
    def _seed(self, tmp_db):
        """Seed a handful of lessons covering different markets and signals."""
        log_lesson(
            _base_lesson(
                market="xyz:BRENTOIL",
                signal_source="thesis_driven",
                lesson_type="entry_timing",
                summary="BRENTOIL long on EIA draw, entry ahead of print, +8.7% in 1h.",
                body_full="EIA draw confirmed thesis. Supply disruption catalyst played out.",
                tags=["supply-disruption", "eia-confirmed"],
                trade_closed_at="2026-04-09T04:55:00Z",
            ),
            db_path=tmp_db,
        )
        log_lesson(
            _base_lesson(
                market="xyz:BRENTOIL",
                signal_source="radar",
                lesson_type="exit_quality",
                outcome="loss",
                pnl_usd=-50.0,
                roe_pct=-4.0,
                summary="BRENTOIL long stopped out on weekend wick — stop too tight.",
                body_full="Stop placed at 1.5x ATR, weekend wick took us out, recovered 20 minutes later.",
                tags=["weekend-wick", "stop-too-tight"],
                trade_closed_at="2026-04-08T23:00:00Z",
            ),
            db_path=tmp_db,
        )
        log_lesson(
            _base_lesson(
                market="BTC",
                signal_source="pulse_signal",
                lesson_type="pattern_recognition",
                summary="BTC long on OI breakout failed — false breakout after Fed dovish tilt.",
                body_full="Pulse signal fired on OI breakout but the breakout never confirmed volume.",
                tags=["fed-day", "false-breakout"],
                outcome="loss",
                pnl_usd=-200.0,
                roe_pct=-6.5,
                trade_closed_at="2026-04-07T15:30:00Z",
            ),
            db_path=tmp_db,
        )
        log_lesson(
            _base_lesson(
                market="xyz:GOLD",
                signal_source="thesis_driven",
                lesson_type="catalyst_timing",
                summary="GOLD long ahead of CPI — hit TP as print came in hot.",
                body_full="Positioned 24h before CPI print. Catalyst played out as thesis predicted.",
                tags=["cpi", "catalyst-played-out"],
                trade_closed_at="2026-04-06T12:00:00Z",
            ),
            db_path=tmp_db,
        )

    def test_empty_query_returns_most_recent_first(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(db_path=tmp_db)
        assert len(results) == 4
        # Most recent trade_closed_at first
        timestamps = [r["trade_closed_at"] for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_fts_query_ranks_relevant_first(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(query="weekend wick stop", db_path=tmp_db, limit=2)
        assert len(results) >= 1
        top = results[0]
        assert "weekend" in top["summary"].lower() or "weekend" in top["body_full"].lower()
        # BM25 score must be populated for MATCH queries
        assert top["bm25_score"] is not None

    def test_fts_query_finds_via_body(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(query="OI breakout volume", db_path=tmp_db)
        assert len(results) >= 1
        assert any("BTC" in r["market"] for r in results)

    def test_fts_query_finds_via_tags(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(query="cpi", db_path=tmp_db)
        assert len(results) >= 1
        assert any("GOLD" in r["market"] for r in results)

    def test_market_filter(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(market="xyz:BRENTOIL", db_path=tmp_db)
        assert len(results) == 2
        assert all(r["market"] == "xyz:BRENTOIL" for r in results)

    def test_direction_filter(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(direction="long", db_path=tmp_db)
        assert len(results) == 4

    def test_signal_source_filter(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(signal_source="thesis_driven", db_path=tmp_db)
        assert len(results) == 2
        assert all(r["signal_source"] == "thesis_driven" for r in results)

    def test_lesson_type_filter(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(lesson_type="exit_quality", db_path=tmp_db)
        assert len(results) == 1
        assert results[0]["lesson_type"] == "exit_quality"

    def test_outcome_filter(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(outcome="loss", db_path=tmp_db)
        assert len(results) == 2
        assert all(r["outcome"] == "loss" for r in results)

    def test_combined_filters_with_query(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(
            query="thesis",
            market="xyz:BRENTOIL",
            signal_source="thesis_driven",
            db_path=tmp_db,
        )
        assert len(results) >= 1
        assert all(r["market"] == "xyz:BRENTOIL" for r in results)
        assert all(r["signal_source"] == "thesis_driven" for r in results)

    def test_limit(self, tmp_db):
        self._seed(tmp_db)
        results = search_lessons(db_path=tmp_db, limit=2)
        assert len(results) == 2

    def test_rejected_excluded_by_default(self, tmp_db):
        rid = log_lesson(_base_lesson(summary="rejected lesson"), db_path=tmp_db)
        log_lesson(_base_lesson(summary="good lesson"), db_path=tmp_db)
        set_lesson_review(rid, -1, db_path=tmp_db)

        results = search_lessons(db_path=tmp_db)
        assert len(results) == 1
        assert results[0]["summary"] == "good lesson"

    def test_include_rejected_option(self, tmp_db):
        rid = log_lesson(_base_lesson(summary="rejected lesson"), db_path=tmp_db)
        log_lesson(_base_lesson(summary="good lesson"), db_path=tmp_db)
        set_lesson_review(rid, -1, db_path=tmp_db)

        results = search_lessons(include_rejected=True, db_path=tmp_db)
        assert len(results) == 2

    def test_injection_resistant(self, tmp_db):
        self._seed(tmp_db)
        # FTS5 operators in user input must not break the query
        for bad_query in [
            'weekend" OR 1=1',
            "NOT ALL AND OR",
            "*",
            "(foo)",
            'term with "quotes"',
        ]:
            # Must not raise
            results = search_lessons(query=bad_query, db_path=tmp_db)
            assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Curation: set_lesson_review
# ---------------------------------------------------------------------------

class TestSetLessonReview:
    def test_approve(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        assert set_lesson_review(rid, 1, db_path=tmp_db) is True
        row = get_lesson(rid, db_path=tmp_db)
        assert row["reviewed_by_chris"] == 1

    def test_reject(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        assert set_lesson_review(rid, -1, db_path=tmp_db) is True
        row = get_lesson(rid, db_path=tmp_db)
        assert row["reviewed_by_chris"] == -1

    def test_unreview(self, tmp_db):
        rid = log_lesson(_base_lesson(reviewed_by_chris=1), db_path=tmp_db)
        assert set_lesson_review(rid, 0, db_path=tmp_db) is True
        row = get_lesson(rid, db_path=tmp_db)
        assert row["reviewed_by_chris"] == 0

    def test_missing_id_returns_false(self, tmp_db):
        # Create the table first
        log_lesson(_base_lesson(), db_path=tmp_db)
        assert set_lesson_review(999, 1, db_path=tmp_db) is False

    def test_invalid_status_raises(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        with pytest.raises(ValueError, match="status must be -1, 0, or 1"):
            set_lesson_review(rid, 2, db_path=tmp_db)


# ---------------------------------------------------------------------------
# Append-only trigger
# ---------------------------------------------------------------------------

class TestAppendOnly:
    def test_body_full_update_blocked(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        con = sqlite3.connect(tmp_db)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            con.execute("UPDATE lessons SET body_full = ? WHERE id = ?", ("tampered", rid))

    def test_summary_update_blocked(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        con = sqlite3.connect(tmp_db)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            con.execute("UPDATE lessons SET summary = ? WHERE id = ?", ("tampered", rid))

    def test_pnl_update_blocked(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        con = sqlite3.connect(tmp_db)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            con.execute("UPDATE lessons SET pnl_usd = ? WHERE id = ?", (999.0, rid))

    def test_outcome_update_blocked(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        con = sqlite3.connect(tmp_db)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            con.execute(
                "UPDATE lessons SET outcome = ? WHERE id = ?", ("breakeven", rid)
            )

    def test_market_update_blocked(self, tmp_db):
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        con = sqlite3.connect(tmp_db)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            con.execute("UPDATE lessons SET market = ? WHERE id = ?", ("FAKE", rid))

    def test_reviewed_by_chris_update_allowed(self, tmp_db):
        """The curation column must remain mutable."""
        rid = log_lesson(_base_lesson(), db_path=tmp_db)
        set_lesson_review(rid, 1, db_path=tmp_db)
        set_lesson_review(rid, -1, db_path=tmp_db)
        set_lesson_review(rid, 0, db_path=tmp_db)
        # No exception; and get_lesson sees the last value
        assert get_lesson(rid, db_path=tmp_db)["reviewed_by_chris"] == 0

    def test_tags_update_allowed(self, tmp_db):
        """Tags may be edited (curation). FTS5 must stay in sync."""
        rid = log_lesson(
            _base_lesson(summary="unique-summary-xyzzy", tags=["original-tag"]),
            db_path=tmp_db,
        )
        con = sqlite3.connect(tmp_db)
        con.execute(
            "UPDATE lessons SET tags = ? WHERE id = ?",
            (json.dumps(["new-tag", "another"]), rid),
        )
        con.commit()
        row = get_lesson(rid, db_path=tmp_db)
        assert json.loads(row["tags"]) == ["new-tag", "another"]
        # FTS5 finds it by the new tag
        results = search_lessons(query="new-tag", db_path=tmp_db)
        assert len(results) >= 1
        assert results[0]["id"] == rid


# ---------------------------------------------------------------------------
# FTS5 is kept in sync on insert
# ---------------------------------------------------------------------------

class TestFtsSync:
    def test_fts_populated_on_insert(self, tmp_db):
        log_lesson(
            _base_lesson(
                summary="unique-searchable-token-abc123",
                body_full="body content",
            ),
            db_path=tmp_db,
        )
        results = search_lessons(query="abc123", db_path=tmp_db)
        assert len(results) == 1
        assert "abc123" in results[0]["summary"]

    def test_fts_finds_body_content(self, tmp_db):
        log_lesson(
            _base_lesson(
                summary="generic summary",
                body_full="specific-body-keyword-zzztest in the body",
            ),
            db_path=tmp_db,
        )
        results = search_lessons(query="zzztest", db_path=tmp_db)
        assert len(results) == 1

    def test_fts_finds_tag_content(self, tmp_db):
        log_lesson(
            _base_lesson(tags=["exotic-tag-alpha", "other"]),
            db_path=tmp_db,
        )
        results = search_lessons(query="exotic-tag-alpha", db_path=tmp_db)
        assert len(results) == 1
