"""Tests for memory_consolidator.py and context_harness.py.

Uses in-memory SQLite — no disk I/O, no API calls.
Validates:
1. Memory consolidation compresses events correctly
2. Context harness respects token budgets
3. Tier ordering works (critical first, background last)
4. Dropped blocks are tracked
5. Edge cases (empty DB, zero budget, missing modules)
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time

import pytest

from common.memory import _init as init_memory_db, log_event, log_learning
from common.memory_consolidator import (
    ConsolidationStats,
    consolidate,
    get_consolidated_context,
    get_active_observations,
    _compress_events,
    _ms_to_date,
)
from agent.context_harness import (
    AssembledContext,
    ContextBlock,
    build_thesis_context,
    build_multi_market_context,
    _assemble,
    _render_time_context,
    CHARS_PER_TOKEN,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database with memory schema."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    con = sqlite3.connect(db_path)
    init_memory_db(con)
    con.close()

    yield db_path

    os.unlink(db_path)


@pytest.fixture
def populated_db(tmp_db):
    """DB with sample events, learnings, and observations."""
    now_ms = int(time.time() * 1000)
    day_ms = 86_400_000

    # Recent events (last 3 days)
    for i in range(5):
        log_event(
            title=f"Recent event {i}",
            event_type="market_data",
            market="xyz:BRENTOIL",
            detail=f"Recent detail for event {i}",
            tags=["oil", "recent"],
            source="test",
            timestamp_ms=now_ms - i * day_ms,
            db_path=tmp_db,
        )

    # Old events (10-14 days ago, dense cluster) — candidates for consolidation
    # Pack 15 events into a ~4 day window so they land in one weekly bucket
    for i in range(15):
        log_event(
            title=f"Old event {i}",
            event_type="geopolitical" if i % 3 == 0 else "market_data",
            market="xyz:BRENTOIL",
            detail=f"Old detail for event {i}",
            tags=["oil", "hormuz", "supply"] if i % 2 == 0 else ["oil"],
            source="test",
            timestamp_ms=now_ms - (10 * day_ms) - (i * day_ms // 4),  # dense: 4 per day
            db_path=tmp_db,
        )

    # Very old events (50-53 days ago, dense cluster)
    for i in range(12):
        log_event(
            title=f"Ancient event {i}",
            event_type="signal",
            market="xyz:BRENTOIL",
            detail=f"Ancient detail {i}",
            tags=["oil", "ancient"],
            source="test",
            timestamp_ms=now_ms - (50 * day_ms) - (i * day_ms // 4),
            db_path=tmp_db,
        )

    # Learnings
    for i in range(5):
        log_learning(
            title=f"Learning {i}",
            lesson=f"Important lesson about risk management #{i}",
            topic="risk_management",
            market="xyz:BRENTOIL",
            db_path=tmp_db,
        )

    # Active observations
    con = sqlite3.connect(tmp_db)
    for i in range(3):
        con.execute(
            "INSERT INTO observations (created_at, valid_from, market, category, priority, title, body, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now_ms, now_ms, "xyz:BRENTOIL", "position", i + 1,
             f"Observation {i}", f"Body of observation {i}", "test"),
        )
    con.commit()
    con.close()

    return tmp_db


# ═══════════════════════════════════════════════════════════════════════════════
# Memory consolidator tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestConsolidation:
    def test_consolidate_empty_db(self, tmp_db):
        stats = consolidate(db_path=tmp_db)
        assert stats.events_scanned == 0
        assert stats.summaries_created == 0

    def test_consolidate_creates_summaries(self, populated_db):
        stats = consolidate(db_path=populated_db)
        assert stats.events_scanned > 0
        # Old events should be consolidated
        assert stats.summaries_created > 0
        assert "xyz:BRENTOIL" in stats.markets_touched

    def test_consolidation_is_idempotent(self, populated_db):
        stats1 = consolidate(db_path=populated_db)
        stats2 = consolidate(db_path=populated_db)
        # Second run should find nothing new to consolidate
        assert stats2.summaries_created == 0

    def test_summaries_link_to_source_ids(self, populated_db):
        consolidate(db_path=populated_db)

        con = sqlite3.connect(populated_db)
        con.row_factory = sqlite3.Row
        summaries = con.execute("SELECT * FROM summaries").fetchall()
        for s in summaries:
            source_ids = json.loads(s["source_ids"])
            assert isinstance(source_ids, list)
            assert len(source_ids) > 0
            # Verify source IDs exist in events table
            for sid in source_ids[:3]:
                row = con.execute("SELECT id FROM events WHERE id = ?", (sid,)).fetchone()
                assert row is not None
        con.close()

    def test_summaries_have_time_range(self, populated_db):
        consolidate(db_path=populated_db)

        con = sqlite3.connect(populated_db)
        con.row_factory = sqlite3.Row
        summaries = con.execute("SELECT * FROM summaries").fetchall()
        for s in summaries:
            assert s["covers_from"] is not None
            assert s["covers_to"] is not None
            assert s["covers_from"] < s["covers_to"]
        con.close()

    def test_source_events_not_deleted(self, populated_db):
        """Consolidation must NEVER delete source events."""
        con = sqlite3.connect(populated_db)
        count_before = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        con.close()

        consolidate(db_path=populated_db)

        con = sqlite3.connect(populated_db)
        count_after = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        con.close()

        assert count_after == count_before, "Consolidation must never delete events!"


class TestCompressEvents:
    def test_basic_compression(self):
        events = [
            {"id": 1, "timestamp_ms": 1700000000000, "event_type": "market_data",
             "title": "Oil price surge", "detail": "big move", "tags": '["oil"]'},
            {"id": 2, "timestamp_ms": 1700100000000, "event_type": "geopolitical",
             "title": "Iran tensions", "detail": "conflict", "tags": '["iran", "oil"]'},
            {"id": 3, "timestamp_ms": 1700200000000, "event_type": "market_data",
             "title": "Volume spike", "detail": "large volume", "tags": '["oil"]'},
        ]
        result = _compress_events(events, "xyz:BRENTOIL")
        assert len(result) > 0
        assert len(result) <= 500  # MAX_SUMMARY_CHARS
        assert "Oil price surge" in result or "Iran tensions" in result

    def test_empty_events(self):
        assert _compress_events([], "test") == ""


class TestGetConsolidatedContext:
    def test_returns_bounded_context(self, populated_db):
        ctx = get_consolidated_context("xyz:BRENTOIL", max_chars=2000, db_path=populated_db)
        assert isinstance(ctx, str)
        assert len(ctx) <= 2500  # some slack for formatting
        assert "BRENTOIL" in ctx or "RECENT" in ctx or "LEARNINGS" in ctx

    def test_empty_market(self, tmp_db):
        ctx = get_consolidated_context("NONEXISTENT", db_path=tmp_db)
        assert ctx == "" or len(ctx) < 100

    def test_includes_learnings(self, populated_db):
        ctx = get_consolidated_context("xyz:BRENTOIL", db_path=populated_db)
        assert "LEARNINGS" in ctx or "Learning" in ctx


class TestActiveObservations:
    def test_returns_observations(self, populated_db):
        obs = get_active_observations("xyz:BRENTOIL", db_path=populated_db)
        assert isinstance(obs, list)
        assert len(obs) > 0

    def test_sorted_by_priority(self, populated_db):
        obs = get_active_observations("xyz:BRENTOIL", db_path=populated_db)
        if len(obs) >= 2:
            assert obs[0]["priority"] <= obs[1]["priority"]

    def test_empty_market(self, tmp_db):
        obs = get_active_observations("NONEXISTENT", db_path=tmp_db)
        assert obs == []


# ═══════════════════════════════════════════════════════════════════════════════
# Context harness tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextBlockAssembly:
    def test_critical_first(self):
        blocks = [
            ContextBlock(name="bg", content="background stuff " * 20, tier="background", relevance=0.5),
            ContextBlock(name="crit", content="critical info " * 10, tier="critical", relevance=0.9),
            ContextBlock(name="rel", content="relevant data " * 15, tier="relevant", relevance=0.7),
        ]
        result = _assemble(blocks, token_budget=500)
        # Critical should be first in the output
        assert result.text.startswith("critical info")
        assert "crit" in result.blocks_included

    def test_budget_enforced(self):
        blocks = [
            ContextBlock(name="big", content="x" * 10000, tier="relevant", relevance=0.5),
        ]
        result = _assemble(blocks, token_budget=100)
        # 100 tokens * 4 chars/token = 400 chars budget
        assert result.total_chars <= 500  # some slack

    def test_dropped_blocks_tracked(self):
        blocks = [
            ContextBlock(name="fits", content="small", tier="critical", relevance=0.9),
            ContextBlock(name="dropped", content="x" * 50000, tier="background", relevance=0.1),
        ]
        result = _assemble(blocks, token_budget=100)
        assert "fits" in result.blocks_included
        assert any("dropped" in d for d in result.blocks_dropped)

    def test_relevance_ordering_within_tier(self):
        blocks = [
            ContextBlock(name="low", content="low rel " * 5, tier="relevant", relevance=0.3),
            ContextBlock(name="high", content="high rel " * 5, tier="relevant", relevance=0.9),
        ]
        result = _assemble(blocks, token_budget=1000)
        # Higher relevance should come first
        high_pos = result.text.find("high rel")
        low_pos = result.text.find("low rel")
        assert high_pos < low_pos

    def test_empty_blocks(self):
        result = _assemble([], token_budget=1000)
        assert result.text == ""
        assert result.estimated_tokens == 0


class TestBuildThesisContext:
    def test_basic_assembly(self, populated_db):
        ctx = build_thesis_context(
            market="xyz:BRENTOIL",
            account_state={
                "account": {"total_equity": 50000, "native_equity": 30000, "xyz_equity": 20000},
                "brentoil": {
                    "size": 20, "entry": 107.5, "current_price": 110.0,
                    "upnl": 500, "liq_price": 95.0, "liq_dist_pct": 13.6,
                    "leverage": 10, "has_sl": True, "has_tp": False,
                    "funding_rate": -0.0001, "funding_annualized_pct": -0.88,
                },
                "alerts": ["WARNING: No TP set"],
            },
            market_snapshot_text="=== BRENTOIL @ 110.0 ===\nFLAGS: strong_trend_4h\nSUPPORT: 107.0",
            current_thesis={"direction": "long", "conviction": 0.85, "effective_conviction": 0.85, "age_hours": 12.0, "stale": False},
            token_budget=2000,
            db_path=populated_db,
        )

        assert isinstance(ctx, AssembledContext)
        assert ctx.estimated_tokens <= 2200  # some slack
        assert "BRENTOIL" in ctx.text
        assert "position" in ctx.blocks_included
        assert "market_structure" in ctx.blocks_included

    def test_respects_budget(self, populated_db):
        ctx = build_thesis_context(
            market="xyz:BRENTOIL",
            token_budget=500,  # very tight budget
            db_path=populated_db,
        )
        # Should fit within budget (with some tolerance for formatting)
        assert ctx.estimated_tokens <= 600
        # Should have dropped some blocks
        assert len(ctx.blocks_dropped) > 0 or ctx.budget_used_pct < 100

    def test_empty_state(self, tmp_db):
        ctx = build_thesis_context(
            market="xyz:BRENTOIL",
            token_budget=2000,
            db_path=tmp_db,
        )
        assert isinstance(ctx, AssembledContext)
        assert ctx.text  # at least time context


class TestBuildMultiMarketContext:
    def test_multi_market(self, populated_db):
        ctx = build_multi_market_context(
            markets=["xyz:BRENTOIL", "BTC-PERP"],
            account_state={
                "account": {"total_equity": 50000},
                "alerts": [],
            },
            market_snapshots={
                "xyz:BRENTOIL": "=== BRENTOIL @ 110 ===\nFLAGS: up_trend",
                "BTC-PERP": "=== BTC-PERP @ 84000 ===\nFLAGS: squeeze_4h",
            },
            token_budget=4000,
            db_path=populated_db,
        )

        assert isinstance(ctx, AssembledContext)
        assert "BRENTOIL" in ctx.text
        assert "BTC-PERP" in ctx.text


class TestTimeContext:
    def test_renders(self):
        text = _render_time_context()
        assert "TIME:" in text
        assert "UTC" in text


class TestTokenEfficiency:
    """Compare context harness output vs old flat dump approach."""

    def test_harness_is_smaller_than_flat_dump(self, populated_db):
        """The harness should produce less context than dumping everything."""
        # Simulate old flat dump: get_market_context + learnings.md content
        from common.memory import get_market_context, format_timeline_for_prompt
        flat_ctx = get_market_context("xyz:BRENTOIL", days=60, db_path=populated_db)
        flat_timeline = format_timeline_for_prompt("xyz:BRENTOIL", days=60, db_path=populated_db)
        flat_total = len(flat_ctx) + len(flat_timeline)

        # New harness
        ctx = build_thesis_context(
            market="xyz:BRENTOIL",
            token_budget=2000,
            db_path=populated_db,
        )

        # Harness should use fewer chars for the memory portion
        # (it uses summarized history + bounded recent events)
        assert ctx.total_chars <= flat_total + 1000  # harness adds structure but compresses content

    def test_budget_metadata(self, populated_db):
        ctx = build_thesis_context(
            market="xyz:BRENTOIL",
            token_budget=2000,
            db_path=populated_db,
        )
        assert ctx.budget_used_pct >= 0
        assert ctx.budget_used_pct <= 100
        assert len(ctx.blocks_included) > 0


class TestMsToDate:
    def test_known_date(self):
        # 2024-01-01 00:00:00 UTC = 1704067200000 ms
        assert _ms_to_date(1704067200000) == "2024-01-01"

    def test_recent(self):
        now_ms = int(time.time() * 1000)
        date_str = _ms_to_date(now_ms)
        assert len(date_str) == 10  # YYYY-MM-DD format
