"""Tests for the H7 dual-write backup in save_working_state.

Closes the SPOF flagged in data-stores.md and the verification ledger:
working_state.json had no dual-write backup, so a single corrupt or
deleted file destroyed heartbeat escalation state, ATR cache, and
per-position last_add tracking.

Now save_working_state writes the canonical file AND a best-effort
{path}.bak in the same directory. Both writes are atomic (.tmp →
rename) and the backup is wrapped in try/except.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from trading.heartbeat_state import (
    WorkingState,
    load_working_state,
    save_working_state,
)


def _make_state() -> WorkingState:
    return WorkingState(
        last_updated_ms=1234567890,
        session_peak_equity=50_000.0,
        session_peak_reset_date="2026-04-07",
        positions={"BTC": {"size": 0.5, "entry": 100.0}},
        escalation_level="L1",
        heartbeat_consecutive_failures=0,
        atr_cache={"BTC": {"atr": 1500.0, "ts": 1234567890}},
        last_prices={"BTC": 105.0},
    )


# ---------------------------------------------------------------------------
# Backup write tests
# ---------------------------------------------------------------------------


class TestWorkingStateBackupWrite:
    def test_save_creates_primary_and_bak(self, tmp_path):
        """save_working_state writes both the primary file and the .bak sibling."""
        path = str(tmp_path / "working_state.json")
        state = _make_state()

        save_working_state(state, path=path)

        primary = Path(path)
        bak = Path(path + ".bak")
        assert primary.exists()
        assert bak.exists()

    def test_backup_content_matches_primary(self, tmp_path):
        """Primary and .bak are byte-identical."""
        path = str(tmp_path / "working_state.json")
        state = _make_state()

        save_working_state(state, path=path)

        primary_bytes = Path(path).read_bytes()
        bak_bytes = Path(path + ".bak").read_bytes()
        assert primary_bytes == bak_bytes

    def test_backup_round_trips_via_load(self, tmp_path):
        """A WorkingState loaded from the .bak file matches the original."""
        path = str(tmp_path / "working_state.json")
        bak_path = path + ".bak"
        original = _make_state()

        save_working_state(original, path=path)

        loaded = load_working_state(path=bak_path)
        assert loaded.last_updated_ms == original.last_updated_ms
        assert loaded.escalation_level == original.escalation_level
        assert loaded.session_peak_equity == original.session_peak_equity
        assert loaded.atr_cache == original.atr_cache
        assert loaded.last_prices == original.last_prices

    def test_save_overwrites_existing_bak(self, tmp_path):
        """A second save() updates both primary and .bak."""
        path = str(tmp_path / "working_state.json")

        v1 = _make_state()
        v1.escalation_level = "L0"
        save_working_state(v1, path=path)

        v2 = _make_state()
        v2.escalation_level = "L3"
        save_working_state(v2, path=path)

        bak_data = json.loads(Path(path + ".bak").read_text())
        assert bak_data["escalation_level"] == "L3"

    def test_backup_failure_does_not_break_primary_write(self, tmp_path, caplog):
        """If the .bak write raises, the primary file still exists."""
        path = str(tmp_path / "working_state.json")
        state = _make_state()

        # Patch os.replace to fail only when target ends with .bak
        from trading import heartbeat_state as hb_mod
        original_replace = hb_mod.os.replace

        def flaky_replace(src, dst, *args, **kwargs):
            if str(dst).endswith(".bak"):
                raise OSError("simulated .bak rename failure")
            return original_replace(src, dst, *args, **kwargs)

        with patch.object(hb_mod.os, "replace", side_effect=flaky_replace):
            with caplog.at_level("WARNING", logger="heartbeat.state"):
                save_working_state(state, path=path)

        # Primary file exists and has the data
        assert Path(path).exists()
        primary_data = json.loads(Path(path).read_text())
        assert primary_data["escalation_level"] == "L1"

        # Backup is missing
        assert not Path(path + ".bak").exists()

        # WARNING was emitted
        assert any("backup write failed" in rec.message for rec in caplog.records)

    def test_uses_atomic_tmp_rename_for_backup(self, tmp_path):
        """No leftover .bak.tmp files after a successful save."""
        path = str(tmp_path / "working_state.json")
        state = _make_state()

        save_working_state(state, path=path)

        # No .bak.tmp leftovers
        leftover = list(tmp_path.glob("*.bak.tmp"))
        assert leftover == []
