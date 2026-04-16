"""Regression tests for JournalIterator exit-price resolution.

BUG-FIX 2026-04-08 (journal-exit-zero): the iterator's original close-detection
path read ``ctx.prices.get(prev.instrument, ZERO)`` and then logged trades
with ``exit_price=$0`` whenever ``ctx.prices`` had been cleared (positions
drop out of ``ctx.positions`` the tick they close, and the connector only
fetches mark prices for currently-open positions). The resulting PnL
calculations produced giant fake numbers — e.g.
``SHORT xyz:CL entry=$94.54 exit=$0.00 PnL=+$2840.95 (+100.0%)`` on a
sub-$1000 account — and polluted the journal JSONL that feeds the
AI agent's reflection loop.

These tests lock in the 4-step resolution cascade: ctx.prices → xyz-stripped
ctx.prices → prev.current_price → HL API → skip (no record).
"""
from __future__ import annotations

import json
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import List

import pytest

from daemon.context import TickContext
from daemon.iterators.journal import JournalIterator, _TrackedPosition
from exchange.position_tracker import Position


def _make_iterator(tmp: Path) -> JournalIterator:
    it = JournalIterator(data_dir=str(tmp))
    it._journal_dir = tmp / "journal"
    it._trades_dir = tmp / "trades"
    it._journal_jsonl = tmp / "journal.jsonl"
    it._journal_dir.mkdir(parents=True, exist_ok=True)
    it._trades_dir.mkdir(parents=True, exist_ok=True)
    return it


def _seed_prev_position(
    it: JournalIterator,
    instrument: str,
    net_qty: float,
    entry_price: float,
    last_mark: float,
) -> None:
    """Prime the iterator as if it had seen an open position on the prior tick."""
    key = instrument.replace("xyz:", "").upper()
    it._prev_positions[key] = _TrackedPosition(
        instrument=instrument,
        net_qty=net_qty,
        avg_entry_price=entry_price,
        leverage=20.0,
        liquidation_price=entry_price * 0.95 if net_qty > 0 else entry_price * 1.05,
        current_price=last_mark,
        timestamp=int(time.time() * 1000),
    )


class TestExitPriceResolutionCascade:

    def test_exit_price_from_ctx_prices_is_used_first(self, tmp_path):
        """Happy path — ctx.prices has the mark, use it directly."""
        it = _make_iterator(tmp_path)
        _seed_prev_position(it, "xyz:CL", net_qty=2.0, entry_price=94.54, last_mark=94.50)

        ctx = TickContext(timestamp=int(time.time() * 1000))
        ctx.positions = []  # position closed this tick
        ctx.prices[Decimal] = None  # noqa — dummy to defeat lint; we set real key below
        ctx.prices.pop(Decimal, None)
        ctx.prices["xyz:CL"] = Decimal("90.12")

        # Pre-create current dict as tick does
        it._detect_position_changes(ctx)

        # A record should have been written with exit_price = 90.12
        journal_entries = list((tmp_path / "trades").glob("*.json"))
        assert len(journal_entries) == 1
        rec = json.loads(journal_entries[0].read_text())
        assert rec["exit_price"] == pytest.approx(90.12, abs=0.001)
        # SHORT would be... wait this is LONG (net_qty=2.0 > 0)
        # PnL = (exit - entry) * size = (90.12 - 94.54) * 2 = -8.84
        assert rec["pnl"] == pytest.approx(-8.84, abs=0.01)
        assert rec["direction"] == "LONG"

    def test_exit_price_xyz_prefix_fallback(self, tmp_path):
        """ctx.prices is keyed under the bare coin — strip xyz: and match."""
        it = _make_iterator(tmp_path)
        _seed_prev_position(it, "xyz:CL", net_qty=2.0, entry_price=94.54, last_mark=94.50)

        ctx = TickContext(timestamp=int(time.time() * 1000))
        ctx.positions = []
        ctx.prices["CL"] = Decimal("91.00")  # bare key, not xyz:CL

        it._detect_position_changes(ctx)

        rec = json.loads(list((tmp_path / "trades").glob("*.json"))[0].read_text())
        assert rec["exit_price"] == pytest.approx(91.00, abs=0.001)

    def test_exit_price_falls_back_to_prev_current_price(self, tmp_path):
        """ctx.prices has nothing for this instrument — use the cached prev mark.

        This is the exact scenario that caused Trade closed exit=$0.00 in prod:
        the connector iterator only fetches prices for currently-open positions,
        so the moment a position closes ctx.prices is missing its entry.
        """
        it = _make_iterator(tmp_path)
        _seed_prev_position(
            it, "xyz:CL", net_qty=-3.0, entry_price=94.54, last_mark=90.25,
        )

        ctx = TickContext(timestamp=int(time.time() * 1000))
        ctx.positions = []
        # Intentionally leave ctx.prices empty — the connector didn't refetch
        # because the position dropped off ctx.positions this tick.

        it._detect_position_changes(ctx)

        trade_files = list((tmp_path / "trades").glob("*.json"))
        assert len(trade_files) == 1, (
            "a record MUST be written from the cached prev.current_price fallback"
        )
        rec = json.loads(trade_files[0].read_text())
        # exit_price should be the prev tick's mark (90.25), NOT 0
        assert rec["exit_price"] == pytest.approx(90.25, abs=0.001), (
            f"exit_price must come from prev.current_price fallback, got {rec['exit_price']}"
        )
        # SHORT PnL = (entry - exit) * size = (94.54 - 90.25) * 3 = 12.87
        assert rec["pnl"] == pytest.approx(12.87, abs=0.01)
        assert rec["direction"] == "SHORT"
        # Critically: this is NOT the bogus +$2840.95-style number that the
        # exit=$0 bug used to produce.
        assert abs(rec["pnl"]) < 100, (
            "PnL must be within reason, not the inflated exit=0 garbage number"
        )

    def test_exit_price_falls_back_to_api_when_everything_else_empty(
        self, tmp_path, monkeypatch,
    ):
        """ctx.prices empty AND prev.current_price is 0 — API fetch must run."""
        it = _make_iterator(tmp_path)
        _seed_prev_position(
            it, "xyz:CL", net_qty=2.0, entry_price=94.54, last_mark=0.0,
        )

        ctx = TickContext(timestamp=int(time.time() * 1000))
        ctx.positions = []

        # Patch the API fallback so we don't actually hit the network
        monkeypatch.setattr(
            JournalIterator, "_fetch_mark_price_fallback",
            staticmethod(lambda instrument: 92.50),
        )

        it._detect_position_changes(ctx)

        trade_files = list((tmp_path / "trades").glob("*.json"))
        assert len(trade_files) == 1
        rec = json.loads(trade_files[0].read_text())
        assert rec["exit_price"] == pytest.approx(92.50, abs=0.001)

    def test_skip_record_when_all_sources_return_zero(self, tmp_path, monkeypatch):
        """All 4 sources yield 0 — no trade record written, no alert emitted.

        Better to lose the record than corrupt the journal with exit=$0.
        The operator can reconstruct the trade from exchange fill history.
        """
        it = _make_iterator(tmp_path)
        _seed_prev_position(
            it, "xyz:CL", net_qty=2.0, entry_price=94.54, last_mark=0.0,
        )

        ctx = TickContext(timestamp=int(time.time() * 1000))
        ctx.positions = []

        # API fallback also fails (returns 0)
        monkeypatch.setattr(
            JournalIterator, "_fetch_mark_price_fallback",
            staticmethod(lambda instrument: 0.0),
        )

        it._detect_position_changes(ctx)

        # No trade file, no JSONL append, no alert
        assert list((tmp_path / "trades").glob("*.json")) == []
        assert not (tmp_path / "journal.jsonl").exists() or \
               (tmp_path / "journal.jsonl").read_text() == ""
        assert len(ctx.alerts) == 0

    def test_bogus_exit_zero_scenario_from_production_logs(self, tmp_path, monkeypatch):
        """Reproduces the exact 2026-04-08 10:21 prod incident.

        Before fix: logged ``SHORT xyz:CL entry=$94.54 exit=$0.00 PnL=+$2840.95
        (+100.0%)``. After fix: either uses the fallback mark (prev tick's
        price) OR skips the record — never writes exit=$0 with inflated PnL.
        """
        it = _make_iterator(tmp_path)
        _seed_prev_position(
            it,
            instrument="xyz:CL",
            net_qty=-30.06,           # SHORT ~30 contracts (matches prod scale)
            entry_price=94.54,
            last_mark=94.50,           # real mark from prev tick
        )

        ctx = TickContext(timestamp=int(time.time() * 1000))
        ctx.positions = []
        # Deliberately empty — this is the bug condition

        # Block the API fallback so we know the prev.current_price path was taken
        api_calls: List[str] = []
        def _record_call(instrument):
            api_calls.append(instrument)
            return 0.0
        monkeypatch.setattr(
            JournalIterator, "_fetch_mark_price_fallback",
            staticmethod(_record_call),
        )

        it._detect_position_changes(ctx)

        trade_files = list((tmp_path / "trades").glob("*.json"))
        assert len(trade_files) == 1
        rec = json.loads(trade_files[0].read_text())

        # The prev.current_price fallback must have kicked in — API was NOT called
        assert api_calls == [], "prev.current_price should have resolved first"
        # Exit is the cached mark, NOT 0
        assert rec["exit_price"] == pytest.approx(94.50, abs=0.001)
        # PnL = (94.54 - 94.50) * 30.06 ≈ 1.20, NOT +$2840.95
        assert abs(rec["pnl"]) < 10, (
            f"PnL must be reasonable, got {rec['pnl']} — the old bug would "
            f"have produced ~+$2841 here"
        )
