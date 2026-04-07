"""Tests for the H8 dual-write backup in FundingTracker._save.

Closes the SPOF flagged in data-stores.md and the verification ledger:
state/funding.json had no dual-write backup. Funding history is not
regenerable from the exchange (HyperLiquid does not expose cumulative
paid funding by position), so loss of this file = loss of cumulative
funding cost tracking forever.

Now FundingTracker._save writes the canonical file AND a best-effort
{filepath}.bak in the same directory. Both writes are atomic and the
backup is wrapped in try/except.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from common.funding_tracker import FundingTracker


def _make_tracker(tmp_path) -> FundingTracker:
    return FundingTracker(state_dir=tmp_path / "state")


# ---------------------------------------------------------------------------
# Backup write tests
# ---------------------------------------------------------------------------


class TestFundingBackupWrite:
    def test_record_creates_primary_and_bak(self, tmp_path):
        """Recording a funding event writes both the primary and the .bak file."""
        t = _make_tracker(tmp_path)
        t.record("BRENTOIL", funding_rate=0.0001, position_notional=1000.0)

        primary = t.filepath
        bak = Path(str(t.filepath) + ".bak")
        assert primary.exists()
        assert bak.exists()

    def test_backup_content_matches_primary(self, tmp_path):
        """The .bak file is byte-identical to the primary."""
        t = _make_tracker(tmp_path)
        t.record("BTC", funding_rate=0.000125, position_notional=5000.0)

        primary_bytes = t.filepath.read_bytes()
        bak_bytes = Path(str(t.filepath) + ".bak").read_bytes()
        assert primary_bytes == bak_bytes

    def test_backup_round_trips_via_load(self, tmp_path):
        """A FundingTracker constructed against the .bak path loads the same state."""
        t = _make_tracker(tmp_path)
        t.record("BRENTOIL", funding_rate=0.0001, position_notional=1000.0)

        # Manually swap primary and .bak: delete primary, restore from .bak
        t.filepath.unlink()
        bak = Path(str(t.filepath) + ".bak")
        bak.rename(t.filepath)

        # Construct a new tracker pointing at the same dir → should load the data
        t2 = FundingTracker(state_dir=tmp_path / "state")
        pf = t2.get("BRENTOIL")
        assert pf is not None
        assert pf.hours_tracked == 1
        assert pf.total_paid_usd == pytest.approx(0.1, abs=1e-6)

    def test_multiple_records_keep_bak_in_sync(self, tmp_path):
        """Each record() call rewrites both primary and .bak with current state."""
        t = _make_tracker(tmp_path)
        t.record("BTC", funding_rate=0.0001, position_notional=1000.0)
        t.record("BTC", funding_rate=0.0001, position_notional=1000.0)
        t.record("BTC", funding_rate=0.0001, position_notional=1000.0)

        bak_data = json.loads(Path(str(t.filepath) + ".bak").read_text())
        assert bak_data["BTC"]["hours_tracked"] == 3

    def test_clear_keeps_bak_in_sync(self, tmp_path):
        """clear() also goes through _save, so the .bak reflects the cleared state."""
        t = _make_tracker(tmp_path)
        t.record("BTC", funding_rate=0.0001, position_notional=1000.0)
        t.record("ETH", funding_rate=0.0001, position_notional=500.0)

        t.clear("BTC")

        bak_data = json.loads(Path(str(t.filepath) + ".bak").read_text())
        assert "BTC" not in bak_data
        assert "ETH" in bak_data

    def test_backup_failure_does_not_break_primary_write(self, tmp_path, caplog):
        """If the .bak write raises, the primary file still exists with the new data."""
        t = _make_tracker(tmp_path)

        # Patch os.replace to fail only on .bak rename
        from common import funding_tracker as ft_mod
        original_replace = ft_mod.os.replace

        def flaky_replace(src, dst, *args, **kwargs):
            if str(dst).endswith(".bak"):
                raise OSError("simulated .bak rename failure")
            return original_replace(src, dst, *args, **kwargs)

        with patch.object(ft_mod.os, "replace", side_effect=flaky_replace):
            with caplog.at_level("WARNING", logger="funding_tracker"):
                t.record("BTC", funding_rate=0.0001, position_notional=1000.0)

        # Primary file exists and has the data
        assert t.filepath.exists()
        primary_data = json.loads(t.filepath.read_text())
        assert "BTC" in primary_data
        assert primary_data["BTC"]["hours_tracked"] == 1

        # Backup is missing
        assert not Path(str(t.filepath) + ".bak").exists()

        # WARNING was emitted
        assert any("backup write failed" in rec.message for rec in caplog.records)

    def test_uses_atomic_tmp_rename_for_backup(self, tmp_path):
        """No leftover .bak.tmp files after a successful save."""
        t = _make_tracker(tmp_path)
        t.record("BTC", funding_rate=0.0001, position_notional=1000.0)

        leftover = list((tmp_path / "state").glob("*.bak.tmp"))
        assert leftover == []
