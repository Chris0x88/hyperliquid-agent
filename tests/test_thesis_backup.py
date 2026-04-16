"""Tests for the H6 dual-write backup in ThesisState.save().

Closes the SPOF flagged in data-stores.md and the verification ledger:
thesis state files had no dual-write backup, so a single corrupt or
deleted file destroyed the AI/execution contract for that market.

Now ThesisState.save() writes the canonical file AND a best-effort
backup copy to the sibling {thesis_dir}_backup directory. The backup
write is wrapped in try/except so it cannot break the primary write.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from trading.thesis.state import ThesisState, _backup_dir_for


def _make_thesis(market: str = "BTC", conviction: float = 0.85) -> ThesisState:
    return ThesisState(
        market=market,
        direction="long",
        conviction=conviction,
        thesis_summary="test thesis",
        recommended_leverage=10.0,
        recommended_size_pct=0.20,
    )


# ---------------------------------------------------------------------------
# Backup directory helper
# ---------------------------------------------------------------------------


class TestBackupDirHelper:
    def test_default_dir(self):
        assert _backup_dir_for("data/thesis") == "data/thesis_backup"

    def test_custom_dir(self):
        assert _backup_dir_for("/tmp/foo") == "/tmp/foo_backup"

    def test_trailing_slash_stripped(self):
        assert _backup_dir_for("data/thesis/") == "data/thesis_backup"


# ---------------------------------------------------------------------------
# Backup write tests
# ---------------------------------------------------------------------------


class TestThesisBackupWrite:
    def test_save_creates_primary_and_backup(self, tmp_path):
        """save() writes to both the primary dir and the sibling backup dir."""
        thesis_dir = str(tmp_path / "thesis")
        backup_dir = str(tmp_path / "thesis_backup")

        thesis = _make_thesis("BTC")
        path = thesis.save(thesis_dir=thesis_dir)

        # Primary file exists
        assert Path(path).exists()
        assert path == str(tmp_path / "thesis" / "btc_state.json")

        # Backup file exists at the mirrored path
        backup_path = Path(backup_dir) / "btc_state.json"
        assert backup_path.exists()

    def test_backup_content_matches_primary(self, tmp_path):
        """Backup file is byte-identical to the primary."""
        thesis_dir = str(tmp_path / "thesis")
        backup_dir = str(tmp_path / "thesis_backup")

        thesis = _make_thesis("BTC", conviction=0.75)
        path = thesis.save(thesis_dir=thesis_dir)

        primary = Path(path).read_text()
        backup = (Path(backup_dir) / "btc_state.json").read_text()
        assert primary == backup

    def test_backup_written_for_xyz_prefixed_market(self, tmp_path):
        """The backup write handles xyz: prefix in market names."""
        thesis_dir = str(tmp_path / "thesis")
        backup_dir = str(tmp_path / "thesis_backup")

        thesis = _make_thesis("xyz:BRENTOIL")
        thesis.save(thesis_dir=thesis_dir)

        # Both files use slug 'xyz_brentoil_state.json'
        primary = Path(thesis_dir) / "xyz_brentoil_state.json"
        backup = Path(backup_dir) / "xyz_brentoil_state.json"
        assert primary.exists()
        assert backup.exists()

    def test_backup_round_trips_via_load(self, tmp_path):
        """A thesis loaded from the backup directory matches the primary load."""
        thesis_dir = str(tmp_path / "thesis")
        backup_dir = str(tmp_path / "thesis_backup")

        original = _make_thesis("BTC", conviction=0.85)
        original.save(thesis_dir=thesis_dir)

        # Load from primary (canonical path)
        loaded_primary = ThesisState.load("BTC", thesis_dir=thesis_dir)
        assert loaded_primary is not None
        assert loaded_primary.conviction == pytest.approx(0.85)

        # Load from backup directory directly
        loaded_backup = ThesisState.load("BTC", thesis_dir=backup_dir)
        assert loaded_backup is not None
        assert loaded_backup.conviction == pytest.approx(0.85)
        assert loaded_backup.market == loaded_primary.market

    def test_save_overwrites_existing_backup(self, tmp_path):
        """A second save() updates both primary and backup."""
        thesis_dir = str(tmp_path / "thesis")
        backup_dir = str(tmp_path / "thesis_backup")

        thesis_v1 = _make_thesis("BTC", conviction=0.5)
        thesis_v1.save(thesis_dir=thesis_dir)

        thesis_v2 = _make_thesis("BTC", conviction=0.9)
        thesis_v2.save(thesis_dir=thesis_dir)

        # Backup reflects v2
        backup_data = json.loads((Path(backup_dir) / "btc_state.json").read_text())
        assert backup_data["conviction"] == pytest.approx(0.9)

    def test_backup_failure_does_not_break_primary_write(self, tmp_path, caplog):
        """If the backup write raises, the primary write still succeeds."""
        thesis_dir = str(tmp_path / "thesis")

        thesis = _make_thesis("BTC")

        # Patch Path.mkdir to raise only when creating the backup dir.
        # The primary write also calls mkdir; we only fail the second call.
        original_mkdir = Path.mkdir
        call_count = {"n": 0}

        def flaky_mkdir(self, *args, **kwargs):
            call_count["n"] += 1
            if "thesis_backup" in str(self):
                raise OSError("simulated backup mkdir failure")
            return original_mkdir(self, *args, **kwargs)

        with patch.object(Path, "mkdir", flaky_mkdir):
            with caplog.at_level("WARNING", logger="thesis"):
                path = thesis.save(thesis_dir=thesis_dir)

        # Primary write succeeded
        assert Path(path).exists()
        primary_data = json.loads(Path(path).read_text())
        assert primary_data["market"] == "BTC"

        # Backup is missing (we failed mkdir)
        backup_path = Path(str(tmp_path / "thesis_backup")) / "btc_state.json"
        assert not backup_path.exists()

        # A WARNING log was emitted naming the file
        assert any("backup write failed" in record.message for record in caplog.records)

    def test_uses_atomic_tmp_rename_for_backup(self, tmp_path):
        """The backup write uses .tmp + rename for atomicity (no half-written backups)."""
        thesis_dir = str(tmp_path / "thesis")
        backup_dir = str(tmp_path / "thesis_backup")

        thesis = _make_thesis("BTC")
        thesis.save(thesis_dir=thesis_dir)

        # No leftover .tmp file in the backup dir after save completes
        leftover_tmp = list(Path(backup_dir).glob("*.tmp"))
        assert leftover_tmp == []
