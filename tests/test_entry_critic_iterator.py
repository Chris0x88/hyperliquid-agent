"""Tests for cli/daemon/iterators/entry_critic.py — Trade Entry Critic I/O wrapper.

The iterator is a thin I/O layer on top of the pure-logic module (see
test_entry_critic_module.py for the grading rules). These tests cover:

- kill switch → no-op
- no positions → no-op
- new position → critique fired (alert + JSONL row)
- repeat tick same positions → no duplicate critique
- state file persistence across iterator instances
- missing input files → graceful degradation (no crash)
- malformed Position → skipped without taking down the tick
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from daemon.iterators.entry_critic import EntryCriticIterator


# ───────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────


@dataclass
class _FakePos:
    """Duck-typed Position for tests — mirrors parent.position_tracker.Position."""
    instrument: str = "xyz:BRENTOIL"
    net_qty: Decimal = Decimal("10")
    avg_entry_price: Decimal = Decimal("89.5")
    liquidation_price: Decimal = Decimal("82.0")
    leverage: Decimal = Decimal("5")


@dataclass
class _FakeCtx:
    positions: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    thesis_states: dict = field(default_factory=dict)
    market_snapshots: dict = field(default_factory=dict)
    total_equity: float = 10_000.0
    timestamp: int = 0
    tick_number: int = 0


@pytest.fixture
def workdir(tmp_path):
    """Hermetic workdir with builder + stub context."""
    config = tmp_path / "data" / "config" / "entry_critic.json"
    state = tmp_path / "data" / "daemon" / "entry_critic_state.json"
    critiques = tmp_path / "data" / "research" / "entry_critiques.jsonl"
    zones = tmp_path / "data" / "heatmap" / "zones.jsonl"
    cascades = tmp_path / "data" / "heatmap" / "cascades.jsonl"
    catalysts = tmp_path / "data" / "news" / "catalysts.jsonl"
    bot_patterns = tmp_path / "data" / "research" / "bot_patterns.jsonl"

    def make(**overrides) -> EntryCriticIterator:
        return EntryCriticIterator(
            config_path=str(overrides.get("config", config)),
            state_path=str(overrides.get("state", state)),
            critiques_path=str(overrides.get("critiques", critiques)),
            zones_path=str(overrides.get("zones", zones)),
            cascades_path=str(overrides.get("cascades", cascades)),
            catalysts_path=str(overrides.get("catalysts", catalysts)),
            bot_patterns_path=str(overrides.get("bot_patterns", bot_patterns)),
            search_lessons_fn=overrides.get("search_lessons_fn", _stub_lessons()),
        )

    return {
        "tmp": tmp_path,
        "config": config,
        "state": state,
        "critiques": critiques,
        "zones": zones,
        "cascades": cascades,
        "catalysts": catalysts,
        "bot_patterns": bot_patterns,
        "make": make,
    }


def _stub_lessons(*rows):
    def fn(**kwargs):
        return list(rows)
    return fn


# ───────────────────────────────────────────────────────────
# Lifecycle
# ───────────────────────────────────────────────────────────


class TestLifecycle:
    def test_on_start_default_enabled(self, workdir):
        it = workdir["make"]()
        ctx = _FakeCtx()
        it.on_start(ctx)
        assert it._enabled is True
        assert it._fingerprints == []

    def test_kill_switch_disables(self, workdir):
        workdir["config"].parent.mkdir(parents=True, exist_ok=True)
        workdir["config"].write_text(json.dumps({"enabled": False}))

        it = workdir["make"]()
        ctx = _FakeCtx(positions=[_FakePos()])
        it.on_start(ctx)
        it.tick(ctx)

        assert it._enabled is False
        assert ctx.alerts == []
        assert not workdir["critiques"].exists()

    def test_corrupt_config_defaults_to_enabled(self, workdir):
        workdir["config"].parent.mkdir(parents=True, exist_ok=True)
        workdir["config"].write_text("not valid json")
        it = workdir["make"]()
        it.on_start(_FakeCtx())
        assert it._enabled is True

    def test_corrupt_state_resets(self, workdir):
        workdir["state"].parent.mkdir(parents=True, exist_ok=True)
        workdir["state"].write_text("not valid")
        it = workdir["make"]()
        it.on_start(_FakeCtx())
        assert it._fingerprints == []


# ───────────────────────────────────────────────────────────
# Tick behavior
# ───────────────────────────────────────────────────────────


class TestTick:
    def test_no_positions_is_noop(self, workdir):
        it = workdir["make"]()
        ctx = _FakeCtx(positions=[])
        it.on_start(ctx)
        it.tick(ctx)
        assert ctx.alerts == []
        assert not workdir["critiques"].exists()

    def test_new_position_fires_critique(self, workdir):
        it = workdir["make"]()
        ctx = _FakeCtx(positions=[_FakePos()])
        it.on_start(ctx)
        it.tick(ctx)

        assert len(ctx.alerts) == 1
        alert = ctx.alerts[0]
        assert alert.source == "entry_critic"
        assert "Entry Critique" in alert.message
        assert "xyz:BRENTOIL" in alert.message
        assert workdir["critiques"].exists()
        lines = workdir["critiques"].read_text().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["kind"] == "entry_critique"
        assert row["instrument"] == "xyz:BRENTOIL"

    def test_zero_qty_position_is_skipped(self, workdir):
        it = workdir["make"]()
        flat = _FakePos(net_qty=Decimal("0"))
        ctx = _FakeCtx(positions=[flat])
        it.on_start(ctx)
        it.tick(ctx)
        assert ctx.alerts == []

    def test_short_position_direction(self, workdir):
        it = workdir["make"]()
        short = _FakePos(net_qty=Decimal("-5"), liquidation_price=Decimal("95"))
        ctx = _FakeCtx(positions=[short])
        it.on_start(ctx)
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert "SHORT" in ctx.alerts[0].message

    def test_repeat_tick_no_duplicate(self, workdir):
        it = workdir["make"]()
        ctx = _FakeCtx(positions=[_FakePos()])
        it.on_start(ctx)
        it.tick(ctx)
        it.tick(ctx)
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert len(workdir["critiques"].read_text().splitlines()) == 1

    def test_multiple_positions_one_alert_each(self, workdir):
        it = workdir["make"]()
        ctx = _FakeCtx(positions=[
            _FakePos(instrument="xyz:BRENTOIL"),
            _FakePos(instrument="BTC", avg_entry_price=Decimal("94250"), net_qty=Decimal("0.005")),
        ])
        it.on_start(ctx)
        it.tick(ctx)
        assert len(ctx.alerts) == 2
        instruments = {a.data["instrument"] for a in ctx.alerts}
        assert instruments == {"xyz:BRENTOIL", "BTC"}

    def test_second_entry_after_close_fires_new_critique(self, workdir):
        it = workdir["make"]()
        ctx1 = _FakeCtx(positions=[_FakePos()])
        it.on_start(ctx1)
        it.tick(ctx1)

        # Position closes, new entry at different price
        ctx2 = _FakeCtx(positions=[_FakePos(avg_entry_price=Decimal("91.0"))])
        it.tick(ctx2)
        # Two critiques total
        assert len(workdir["critiques"].read_text().splitlines()) == 2

    def test_malformed_position_does_not_crash_tick(self, workdir):
        """A broken position in the list must not break subsequent ones."""
        it = workdir["make"]()

        class Broken:
            @property
            def net_qty(self):
                raise RuntimeError("boom")

        ctx = _FakeCtx(positions=[Broken(), _FakePos()])
        it.on_start(ctx)
        it.tick(ctx)

        # Good position still got critiqued
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].data["instrument"] == "xyz:BRENTOIL"


# ───────────────────────────────────────────────────────────
# State persistence across restarts
# ───────────────────────────────────────────────────────────


class TestStatePersistence:
    def test_fingerprint_persisted_across_restart(self, workdir):
        it1 = workdir["make"]()
        ctx1 = _FakeCtx(positions=[_FakePos()])
        it1.on_start(ctx1)
        it1.tick(ctx1)
        it1.on_stop()

        # Second daemon run — same fingerprint, must NOT re-critique
        it2 = workdir["make"]()
        ctx2 = _FakeCtx(positions=[_FakePos()])
        it2.on_start(ctx2)
        assert len(it2._fingerprints) >= 1
        it2.tick(ctx2)
        assert ctx2.alerts == []
        # JSONL still only has the original one row
        assert len(workdir["critiques"].read_text().splitlines()) == 1

    def test_state_file_atomically_written(self, workdir):
        it = workdir["make"]()
        ctx = _FakeCtx(positions=[_FakePos()])
        it.on_start(ctx)
        it.tick(ctx)
        assert workdir["state"].exists()
        state = json.loads(workdir["state"].read_text())
        assert "fingerprints" in state
        assert len(state["fingerprints"]) == 1


# ───────────────────────────────────────────────────────────
# Graceful degradation — missing input files
# ───────────────────────────────────────────────────────────


class TestGracefulDegradation:
    def test_missing_zones_and_catalysts_still_critiques(self, workdir):
        """No heatmap, no catalysts, no cascades — critique still fires."""
        # Ensure no input files exist
        assert not workdir["zones"].exists()
        assert not workdir["catalysts"].exists()

        it = workdir["make"]()
        ctx = _FakeCtx(positions=[_FakePos()])
        it.on_start(ctx)
        it.tick(ctx)

        assert len(ctx.alerts) == 1
        row = json.loads(workdir["critiques"].read_text().splitlines()[0])
        # Grade defaults fill in for missing inputs
        assert row["grade"]["sizing"] in {"UNKNOWN", "GREAT", "OK", "UNDERWEIGHT", "OVERWEIGHT"}
        assert row["grade"]["liquidity"] in {"UNKNOWN", "SAFE", "CASCADE_RISK"}
        # Degraded map should mention the missing catalysts file
        assert "catalysts" in row["degraded"]

    def test_missing_lessons_callable_is_safe(self, workdir):
        """If search_lessons_fn raises, iterator doesn't crash."""
        def bad_fn(**kwargs):
            raise RuntimeError("lesson store unavailable")
        it = workdir["make"](search_lessons_fn=bad_fn)
        ctx = _FakeCtx(positions=[_FakePos()])
        it.on_start(ctx)
        it.tick(ctx)
        assert len(ctx.alerts) == 1

    def test_unwritable_state_dir_does_not_crash(self, workdir, monkeypatch):
        """If state write fails, tick still succeeds — we just warn."""
        it = workdir["make"]()
        ctx = _FakeCtx(positions=[_FakePos()])
        it.on_start(ctx)

        # Monkeypatch Path.replace to simulate failure
        import os
        real_replace = Path.replace

        def broken_replace(self, target):
            raise OSError("read-only fs")

        monkeypatch.setattr(Path, "replace", broken_replace)
        try:
            it.tick(ctx)
        finally:
            monkeypatch.setattr(Path, "replace", real_replace)
        # Alert still got emitted even though state save failed
        assert len(ctx.alerts) == 1
