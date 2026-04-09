"""Tests for chat history persistence — writer append-only guarantee,
market_context enrichment, degradation paths, rotation absence, and
backwards compatibility.

Context: Chris told us in April 2026 that chat history is a historical
oracle — "never delete, always preserve, correlate with market state".
These tests codify that contract so a future refactor cannot silently
introduce rotation or block the chat write on a broken enrichment.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def patched_history(tmp_path, monkeypatch):
    """Redirect _HISTORY_FILE to a temp path so every test runs isolated."""
    from cli import telegram_agent
    hist = tmp_path / "chat_history.jsonl"
    monkeypatch.setattr(telegram_agent, "_HISTORY_FILE", hist)
    # Also redirect _PROJECT_ROOT so the snapshot reader looks at tmp_path,
    # not the real project. Tests that want a real snapshot provide one.
    monkeypatch.setattr(telegram_agent, "_PROJECT_ROOT", tmp_path)
    return hist


# ---------------------------------------------------------------------------
# Writer append-only guarantee
# ---------------------------------------------------------------------------

class TestWriterAppendOnly:
    def test_empty_file_is_created_on_first_write(self, patched_history):
        from cli.telegram_agent import _log_chat
        assert not patched_history.exists()
        _log_chat("user", "hello")
        assert patched_history.exists()
        assert len(_read_rows(patched_history)) == 1

    def test_multiple_writes_append(self, patched_history):
        from cli.telegram_agent import _log_chat
        _log_chat("user", "msg one")
        _log_chat("assistant", "msg two")
        _log_chat("user", "msg three")
        rows = _read_rows(patched_history)
        assert len(rows) == 3
        assert rows[0]["text"] == "msg one"
        assert rows[1]["text"] == "msg two"
        assert rows[2]["text"] == "msg three"

    def test_writer_never_truncates_existing_rows(self, patched_history):
        """Regression guard: writer must NEVER overwrite the file. If this
        test fails, someone has added rotation/truncation and violated
        the 'historical oracle' contract."""
        from cli.telegram_agent import _log_chat
        for i in range(50):
            _log_chat("user", f"msg {i}")
        assert len(_read_rows(patched_history)) == 50
        # Write 50 more
        for i in range(50, 100):
            _log_chat("user", f"msg {i}")
        rows = _read_rows(patched_history)
        assert len(rows) == 100, "writer truncated existing rows"
        assert rows[0]["text"] == "msg 0", "oldest row disappeared"
        assert rows[-1]["text"] == "msg 99"

    def test_row_contains_required_fields(self, patched_history):
        from cli.telegram_agent import _log_chat
        _log_chat("user", "hello", user_name="chris")
        row = _read_rows(patched_history)[0]
        assert row["role"] == "user"
        assert row["text"] == "hello"
        assert row["user"] == "chris"
        assert isinstance(row["ts"], int)
        assert row["ts"] > 0


# ---------------------------------------------------------------------------
# Rotation is disabled (regression guard)
# ---------------------------------------------------------------------------

class TestRotationDisabled:
    def test_no_rotation_code_in_writer(self):
        """The writer module must not import shutil/move/rename/rotate APIs
        that could be used to truncate the live file. If someone adds them
        later, this test fails and forces a conversation."""
        import cli.telegram_agent as ta
        src = Path(ta.__file__).read_text()
        # Sanity: the word 'chat_history' MUST appear
        assert "chat_history" in src
        # Forbidden patterns in the writer module: nothing should be
        # renaming, moving, or unlinking the history file.
        forbidden = [
            "chat_history.jsonl.rename",
            "chat_history.jsonl.unlink",
            "shutil.move(",
            "_HISTORY_FILE.unlink",
            "_HISTORY_FILE.rename",
            '_HISTORY_FILE.write_text(',  # would destroy rows
        ]
        for pat in forbidden:
            assert pat not in src, f"forbidden rotation pattern found: {pat}"

    def test_writer_uses_append_mode(self):
        """The writer must open the history file in append mode."""
        import cli.telegram_agent as ta
        src = Path(ta.__file__).read_text()
        # The canonical append-mode open() call
        assert 'open(_HISTORY_FILE, "a")' in src or "open(_HISTORY_FILE, 'a')" in src


# ---------------------------------------------------------------------------
# Market-context enrichment
# ---------------------------------------------------------------------------

class TestMarketContext:
    def _write_snapshot(self, tmp_path: Path, payload: dict) -> Path:
        snap_dir = tmp_path / "data" / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        # account_collector glob: "????????_??????.json"
        f = snap_dir / "20260409_010000.json"
        f.write_text(json.dumps(payload))
        return f

    def test_market_context_added_when_snapshot_present(self, patched_history, tmp_path):
        from cli.telegram_agent import _log_chat
        self._write_snapshot(tmp_path, {
            "total_equity": 50234.12,
            "account_value": 50234.12,
            "positions_xyz": [
                {
                    "type": "oneWay",
                    "position": {
                        "coin": "xyz:BRENTOIL",
                        "szi": "10.5",
                        "positionValue": "785.40",
                    },
                }
            ],
            "positions_native": [
                {
                    "type": "oneWay",
                    "position": {
                        "coin": "BTC",
                        "szi": "-0.05",
                        "positionValue": "4250.00",
                    },
                }
            ],
        })
        _log_chat("user", "/status")
        row = _read_rows(patched_history)[0]
        assert "market_context" in row
        mc = row["market_context"]
        assert mc["equity_usd"] == pytest.approx(50234.12)
        # Positions list present with both native and xyz (prefix stripped)
        symbols = {p["instrument"] for p in mc["positions"]}
        assert "BRENTOIL" in symbols, "xyz: prefix should be stripped"
        assert "BTC" in symbols
        # Side inference
        brent = [p for p in mc["positions"] if p["instrument"] == "BRENTOIL"][0]
        btc = [p for p in mc["positions"] if p["instrument"] == "BTC"][0]
        assert brent["side"] == "long"
        assert btc["side"] == "short"
        assert brent["notional_usd"] == pytest.approx(785.40)
        assert btc["notional_usd"] == pytest.approx(4250.00)

    def test_market_context_null_when_no_snapshot(self, patched_history, tmp_path):
        """When snapshot dir is empty, market_context degrades gracefully
        and the row STILL writes — enrichment must not be a gate."""
        from cli.telegram_agent import _log_chat
        # No snapshot written
        _log_chat("user", "/status")
        rows = _read_rows(patched_history)
        assert len(rows) == 1, "row must write even without snapshot"
        row = rows[0]
        # Either market_context is missing OR all fields are None — both
        # count as "degraded gracefully".
        mc = row.get("market_context")
        if mc is not None:
            assert mc.get("equity_usd") is None
            assert mc.get("positions") in (None, [])

    def test_market_context_snapshot_exception_is_swallowed(self, patched_history, tmp_path):
        """Even if the snapshot loader raises, the chat write must succeed."""
        from cli import telegram_agent
        from cli.telegram_agent import _log_chat

        class _Explode:
            @staticmethod
            def get_latest(_dir):
                raise RuntimeError("simulated snapshot read failure")

        with patch.object(telegram_agent, "_build_market_context_snapshot",
                          side_effect=RuntimeError("boom")):
            _log_chat("user", "hi")

        rows = _read_rows(patched_history)
        assert len(rows) == 1, "chat write must be bulletproof"
        assert rows[0]["text"] == "hi"

    def test_positions_list_empty_when_no_positions(self, patched_history, tmp_path):
        from cli.telegram_agent import _log_chat
        self._write_snapshot(tmp_path, {
            "total_equity": 100.00,
            "positions_native": [],
            "positions_xyz": [],
        })
        _log_chat("user", "flat")
        row = _read_rows(patched_history)[0]
        mc = row["market_context"]
        assert mc["equity_usd"] == pytest.approx(100.00)
        assert mc["positions"] == []


# ---------------------------------------------------------------------------
# Backwards compatibility — readers must tolerate old-schema rows
# ---------------------------------------------------------------------------

class TestBackwardsCompatibility:
    def test_old_schema_row_loads_fine(self, patched_history):
        """A row written before market_context existed must load with the
        existing _load_chat_history reader."""
        from cli.telegram_agent import _load_chat_history
        # Write an old-schema row by hand
        patched_history.parent.mkdir(parents=True, exist_ok=True)
        old_row = {"ts": 1775104419, "role": "user", "text": "old message"}
        patched_history.write_text(json.dumps(old_row) + "\n")

        loaded = _load_chat_history(10)
        assert len(loaded) == 1
        assert loaded[0]["role"] == "user"
        assert loaded[0]["text"] == "old message"
        # market_context missing is fine
        assert "market_context" not in loaded[0] or loaded[0]["market_context"] is None

    def test_mixed_old_and_new_rows_load(self, patched_history):
        from cli.telegram_agent import _load_chat_history
        patched_history.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"ts": 1, "role": "user", "text": "old1"},
            {"ts": 2, "role": "assistant", "text": "old2"},
            {"ts": 3, "role": "user", "text": "new1",
             "market_context": {"equity_usd": 1000.0, "positions": [], "prices": None}},
        ]
        patched_history.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        loaded = _load_chat_history(10)
        assert len(loaded) == 3
        assert loaded[0]["text"] == "old1"
        assert loaded[-1]["text"] == "new1"
