"""Tests for modules/oil_botpattern_patternlib.py — sub-system 6 L3 pure logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.oil_botpattern_patternlib import (
    PatternCandidate,
    PatternSignature,
    candidate_from_dict,
    candidate_to_dict,
    compute_confidence_band,
    compute_signals_sig,
    compute_signature,
    detect_novel_signatures,
    extract_candidate_keys,
    filter_window,
    promote_to_catalog,
)


UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 0, tzinfo=UTC)


def _in_window_ts(days_ago: float) -> str:
    return (_now() - timedelta(days=days_ago)).isoformat()


def _row(**overrides) -> dict:
    base = {
        "id": "r1",
        "instrument": "BRENTOIL",
        "detected_at": _in_window_ts(1),
        "classification": "bot_driven_overextension",
        "direction": "down",
        "confidence": 0.72,
        "signals": ["overextended_move", "oi_divergence"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# compute_confidence_band
# ---------------------------------------------------------------------------

def test_confidence_band_rounds_to_precision():
    assert compute_confidence_band(0.73, 0.1) == 0.7
    assert compute_confidence_band(0.77, 0.1) == 0.8
    assert compute_confidence_band(0.50, 0.1) == 0.5


def test_confidence_band_clamps():
    assert compute_confidence_band(-0.1, 0.1) == 0.0
    assert compute_confidence_band(1.5, 0.1) == 1.0


def test_confidence_band_zero_precision_keeps_value():
    assert compute_confidence_band(0.7345, 0.0) == 0.7345


# ---------------------------------------------------------------------------
# compute_signals_sig
# ---------------------------------------------------------------------------

def test_signals_sig_empty():
    assert compute_signals_sig(None) == "∅"
    assert compute_signals_sig([]) == "∅"
    assert compute_signals_sig(["", "  "]) == "∅"


def test_signals_sig_sorted_and_dedup():
    assert compute_signals_sig(["b", "a", "a"]) == "a|b"
    assert compute_signals_sig(["x"]) == "x"


def test_signals_sig_ignores_order():
    a = compute_signals_sig(["overext", "oi_div"])
    b = compute_signals_sig(["oi_div", "overext"])
    assert a == b


# ---------------------------------------------------------------------------
# compute_signature
# ---------------------------------------------------------------------------

def test_signature_from_row_keys_are_deterministic():
    sig1 = compute_signature(_row(), precision=0.1)
    sig2 = compute_signature(_row(), precision=0.1)
    assert sig1.as_key() == sig2.as_key()


def test_signature_banding_collapses_near_duplicates():
    sig1 = compute_signature(_row(confidence=0.71), precision=0.1)
    sig2 = compute_signature(_row(confidence=0.73), precision=0.1)
    assert sig1.as_key() == sig2.as_key()  # both 0.70


def test_signature_different_classification_different_key():
    sig1 = compute_signature(_row(classification="bot_driven_overextension"), precision=0.1)
    sig2 = compute_signature(_row(classification="informed_flow"), precision=0.1)
    assert sig1.as_key() != sig2.as_key()


# ---------------------------------------------------------------------------
# filter_window
# ---------------------------------------------------------------------------

def test_filter_window_drops_old():
    rows = [
        _row(detected_at=_in_window_ts(1)),
        _row(detected_at=_in_window_ts(40)),  # outside 30d
    ]
    kept = filter_window(rows, _now() - timedelta(days=30))
    assert len(kept) == 1


def test_filter_window_tolerates_missing_ts():
    rows = [{"classification": "x"}]
    kept = filter_window(rows, _now() - timedelta(days=30))
    assert kept == []


# ---------------------------------------------------------------------------
# detect_novel_signatures
# ---------------------------------------------------------------------------

def test_detect_fires_above_min_occurrences():
    rows = [_row() for _ in range(3)]
    candidates = detect_novel_signatures(
        rows=rows, catalog={}, min_occurrences=3, precision=0.1,
        now=_now(), window_days=30,
    )
    assert len(candidates) == 1
    assert candidates[0].occurrences == 3
    assert candidates[0].id == 1
    assert "bot_driven_overextension" in candidates[0].signature_key


def test_detect_below_threshold_emits_nothing():
    rows = [_row() for _ in range(2)]
    candidates = detect_novel_signatures(
        rows=rows, catalog={}, min_occurrences=3, precision=0.1,
        now=_now(), window_days=30,
    )
    assert candidates == []


def test_detect_skips_signatures_already_in_catalog():
    sig = compute_signature(_row(), precision=0.1)
    catalog = {sig.as_key(): {"classification": "x"}}
    rows = [_row() for _ in range(5)]
    candidates = detect_novel_signatures(
        rows=rows, catalog=catalog, min_occurrences=3, precision=0.1,
        now=_now(), window_days=30,
    )
    assert candidates == []


def test_detect_skips_signatures_already_in_candidates():
    sig = compute_signature(_row(), precision=0.1)
    rows = [_row() for _ in range(5)]
    candidates = detect_novel_signatures(
        rows=rows, catalog={}, min_occurrences=3, precision=0.1,
        now=_now(), window_days=30,
        existing_candidate_keys={sig.as_key()},
    )
    assert candidates == []


def test_detect_drops_rows_outside_window():
    rows = [_row(detected_at=_in_window_ts(40)) for _ in range(5)]
    candidates = detect_novel_signatures(
        rows=rows, catalog={}, min_occurrences=3, precision=0.1,
        now=_now(), window_days=30,
    )
    assert candidates == []


def test_detect_assigns_monotonic_ids_from_next_id():
    rows = (
        [_row(signals=["a"]) for _ in range(3)]
        + [_row(signals=["b"]) for _ in range(3)]
        + [_row(signals=["c"]) for _ in range(3)]
    )
    candidates = detect_novel_signatures(
        rows=rows, catalog={}, min_occurrences=3, precision=0.1,
        now=_now(), window_days=30, next_id=50,
    )
    assert len(candidates) == 3
    assert [c.id for c in candidates] == [50, 51, 52]
    assert len({c.id for c in candidates}) == 3


def test_detect_captures_instruments_up_to_five():
    rows = [
        _row(instrument=f"INST{i}")
        for i in range(7)
    ]
    candidates = detect_novel_signatures(
        rows=rows, catalog={}, min_occurrences=3, precision=0.1,
        now=_now(), window_days=30,
    )
    assert len(candidates) == 1
    assert len(candidates[0].example_instruments) == 5  # capped


def test_detect_tracks_first_and_last_seen():
    rows = [
        _row(detected_at=_in_window_ts(5)),
        _row(detected_at=_in_window_ts(1)),
        _row(detected_at=_in_window_ts(3)),
    ]
    candidates = detect_novel_signatures(
        rows=rows, catalog={}, min_occurrences=3, precision=0.1,
        now=_now(), window_days=30,
    )
    assert len(candidates) == 1
    # first_seen should be oldest (~5d ago), last_seen newest (~1d ago)
    assert candidates[0].first_seen_at < candidates[0].last_seen_at


# ---------------------------------------------------------------------------
# promote_to_catalog
# ---------------------------------------------------------------------------

def test_promote_adds_new_entry():
    catalog = {}
    candidate = {
        "signature_key": "test|up|0.70|a|b",
        "classification": "test",
        "direction": "up",
        "confidence_band": 0.70,
        "signals": ["a", "b"],
        "occurrences": 5,
        "first_seen_at": "2026-04-01T00:00:00+00:00",
    }
    new_cat = promote_to_catalog(catalog, candidate, "2026-04-09T10:00:00+00:00")
    assert "test|up|0.70|a|b" in new_cat
    assert new_cat["test|up|0.70|a|b"]["occurrences_at_promotion"] == 5
    assert catalog == {}  # original untouched


def test_promote_idempotent():
    catalog = {"k": {"classification": "old"}}
    candidate = {"signature_key": "k", "classification": "new"}
    new_cat = promote_to_catalog(catalog, candidate, "now")
    assert new_cat["k"]["classification"] == "old"  # unchanged


def test_promote_missing_key_is_noop():
    catalog = {}
    new_cat = promote_to_catalog(catalog, {}, "now")
    assert new_cat == {}


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def test_candidate_roundtrip():
    c = PatternCandidate(
        id=7, created_at="2026-04-09T10:00:00+00:00",
        signature_key="k", classification="x", direction="up",
        confidence_band=0.7, signals=["a", "b"], occurrences=5,
        first_seen_at="2026-04-01", last_seen_at="2026-04-08",
        example_instruments=["BRENTOIL"],
    )
    back = candidate_from_dict(candidate_to_dict(c))
    assert back.id == 7
    assert back.signals == ["a", "b"]
    assert back.occurrences == 5
    assert back.status == "pending"


def test_extract_candidate_keys():
    candidates = [
        {"signature_key": "k1"},
        {"signature_key": "k2"},
        {},  # no key — skipped
    ]
    keys = extract_candidate_keys(candidates)
    assert keys == {"k1", "k2"}
