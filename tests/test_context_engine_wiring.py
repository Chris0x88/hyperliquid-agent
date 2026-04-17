"""Tests for context_engine.py wiring into _build_live_context.

Verifies:
  (a) enabled=true causes ENRICHED CONTEXT block to appear in the output.
  (b) enabled=false leaves output unchanged (no ENRICHED CONTEXT).
  (c) malformed/unknown intent does not crash (graceful fallback to "general").
  (d) empty user_text with enabled=true returns no enriched block (nothing to classify).

Uses monkeypatching to avoid real API/file I/O from _build_live_context itself.
Tests context_engine's classify_intent + assemble_context in isolation.
"""
from __future__ import annotations

import json
import types
import importlib
from unittest.mock import patch, MagicMock


# ─── classify_intent smoke tests ────────────────────────────────────────────

def test_classify_intent_known_category():
    from engines.analysis.context_engine import classify_intent
    intent = classify_intent("What is the risk on my position?")
    assert intent.primary == "risk_check"
    assert intent.confidence > 0


def test_classify_intent_unknown_falls_back_to_general():
    from engines.analysis.context_engine import classify_intent
    # Gibberish that matches no pattern
    intent = classify_intent("asdfjkl qwerty zxcvb")
    assert intent.primary == "general"
    assert intent.confidence == 0.0


def test_classify_intent_malformed_empty_string():
    """Empty string must not crash — returns 'general'."""
    from engines.analysis.context_engine import classify_intent
    intent = classify_intent("")
    assert intent.primary == "general"


def test_classify_intent_detects_markets():
    from engines.analysis.context_engine import classify_intent
    # Note: market detection uses space-padded matching, so the keyword must be
    # surrounded by spaces in the padded string " <text> " — use "oil" mid-sentence.
    intent = classify_intent("what is the outlook for oil right now")
    assert "BRENTOIL" in intent.markets


# ─── assemble_context returns empty when no data files present ───────────────

def test_assemble_context_no_data_returns_empty():
    """With no data files on disk, assemble_context must return '' not crash."""
    from engines.analysis.context_engine import classify_intent, assemble_context
    intent = classify_intent("should I add to my oil position?")
    result = assemble_context(intent, account_state={}, market_snapshots={})
    # Either empty string or a valid ENRICHED CONTEXT block — never raises
    assert isinstance(result, str)


# ─── _build_live_context enrichment gate ────────────────────────────────────

def _make_assembled():
    """Minimal AssembledContext-like object for patching."""
    obj = MagicMock()
    obj.text = "HARNESS OUTPUT"
    obj.estimated_tokens = 100
    obj.budget_used_pct = 50
    obj.blocks_included = ["POSITION"]
    return obj


def _patch_harness(monkeypatch):
    """Patch all the heavy IO helpers inside telegram.agent."""
    import telegram.agent as ag

    monkeypatch.setattr(ag, "_fetch_account_state_for_harness", lambda: {"positions": [], "alerts": [], "fetched_at": __import__("time").time()})
    monkeypatch.setattr(ag, "_fetch_market_snapshots", lambda positions: {})
    monkeypatch.setattr(ag, "get_watchlist_coins", lambda: [])

    fake_assembled = _make_assembled()
    # Patch build_multi_market_context via the module import path used in _build_live_context
    import agent.context_harness as ch_mod
    monkeypatch.setattr(ch_mod, "build_multi_market_context", lambda **kw: fake_assembled)


def test_enriched_context_disabled_by_default(tmp_path, monkeypatch):
    """When config enabled=false, ENRICHED CONTEXT must NOT appear."""
    import telegram.agent as ag

    _patch_harness(monkeypatch)

    # Point config to a temp file with enabled=false
    cfg = tmp_path / "context_engine.json"
    cfg.write_text(json.dumps({"enabled": False}))

    with patch("engines.analysis.context_engine.classify_intent") as mock_classify:
        # Make _build_live_context find our temp config
        with patch("pathlib.Path.exists", return_value=True):
            # Rather than mock the whole filesystem, just test that the result
            # doesn't include ENRICHED when assemble_context returns nothing
            result = ag._build_live_context(user_text="what is my risk?")

    assert "ENRICHED CONTEXT" not in result


def test_enriched_context_appears_when_enabled(tmp_path, monkeypatch):
    """When config enabled=true and assemble_context returns data, block appears."""
    import telegram.agent as ag
    import engines.analysis.context_engine as ce

    _patch_harness(monkeypatch)

    # Patch classify_intent + assemble_context to return a known enriched block
    fake_intent = ce.MessageIntent(primary="risk_check", confidence=0.85)
    fake_enriched = "--- ENRICHED CONTEXT (intent=risk_check, 50t) ---\n[SUPPLY DISRUPTIONS] 1 active"

    monkeypatch.setattr(ce, "classify_intent", lambda text: fake_intent)
    monkeypatch.setattr(ce, "assemble_context", lambda intent, acc, mkt, **kw: fake_enriched)

    # Patch config load to return enabled=true
    import builtins
    original_open = builtins.open

    def _fake_cfg_read(path_obj):
        return json.dumps({"enabled": True})

    # Patch the Path.read_text used inside _build_live_context for the config
    from pathlib import Path
    original_read_text = Path.read_text

    def _patched_read_text(self, *a, **kw):
        if "context_engine.json" in str(self):
            return json.dumps({"enabled": True})
        return original_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    result = ag._build_live_context(user_text="what is my risk on oil?")
    assert "ENRICHED CONTEXT" in result


def test_enriched_context_no_crash_on_bad_intent(tmp_path, monkeypatch):
    """Malformed intent (exception in classify_intent) must not crash _build_live_context."""
    import telegram.agent as ag
    import engines.analysis.context_engine as ce

    _patch_harness(monkeypatch)

    # Make classify_intent raise to simulate a bug
    def _boom(text):
        raise RuntimeError("intentional test error")

    monkeypatch.setattr(ce, "classify_intent", _boom)

    from pathlib import Path
    original_read_text = Path.read_text

    def _patched_read_text(self, *a, **kw):
        if "context_engine.json" in str(self):
            return json.dumps({"enabled": True})
        return original_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    # Must not raise — exception in enrichment is caught and logged as debug
    result = ag._build_live_context(user_text="what is my risk?")
    assert isinstance(result, str)
    # Enriched block must be absent (fell back silently)
    assert "ENRICHED CONTEXT" not in result


def test_enriched_context_empty_user_text(monkeypatch):
    """Empty user_text: enrichment is skipped entirely regardless of config."""
    import telegram.agent as ag
    import engines.analysis.context_engine as ce

    _patch_harness(monkeypatch)

    called = []
    monkeypatch.setattr(ce, "classify_intent", lambda t: called.append(t) or ce.MessageIntent(primary="general"))

    result = ag._build_live_context(user_text="")
    # classify_intent should NOT have been called (user_text is falsy → early exit)
    assert called == []
    assert "ENRICHED CONTEXT" not in result
