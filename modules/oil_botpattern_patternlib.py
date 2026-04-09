"""Oil Bot-Pattern L3 Pattern Library Growth — pure logic.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Sub-system 6 layer L3 per OIL_BOT_PATTERN_SYSTEM.md §6. Reads
data/research/bot_patterns.jsonl (written by sub-system 4), detects
SIGNATURES that are not in the live catalog, counts occurrences in a
rolling window, and emits PatternCandidate records once a signature
crosses min_occurrences.

The classifier in sub-system 4 is NOT modified by this wedge. L3 is
purely observational — it maintains a catalog of observed signatures
that Chris reviews and promotes with `/patternpromote <id>`. A future
wedge can teach sub-system 4 to gate classifications on the promoted
live catalog.

Contract (SYSTEM doc §6):
    "The classifier auto-adds new bot-pattern signatures to versioned
    catalog. Catalog grows freely; live signal set requires one tap to
    promote."

Signature definition: `(classification, direction, confidence_band,
signals_sig)` where confidence_band rounds confidence to a fixed
precision (default 0.1) and signals_sig is the sorted tuple of signals
joined with "|". Two bot_patterns with the same signature are
"equivalent" for library-growth purposes.

Engine vs guard: pure computation, zero I/O. The iterator owns
persistence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PatternSignature:
    """Canonical identity for a bot-pattern signal shape.

    confidence is bucketed by the band precision to collapse noisy
    near-duplicates. signals is the sorted |-joined list so ordering
    doesn't matter.
    """
    classification: str
    direction: str
    confidence_band: float
    signals_sig: str

    def as_key(self) -> str:
        """Stable string key for catalog lookups + candidate IDs."""
        return (
            f"{self.classification}|{self.direction}|"
            f"{self.confidence_band:.2f}|{self.signals_sig}"
        )


@dataclass(frozen=True)
class PatternCandidate:
    """A signature seen >= min_occurrences times that is NOT yet in the
    live catalog. Written to bot_pattern_candidates.jsonl for Chris to
    promote (`/patternpromote <id>`) or reject."""
    id: int                     # assigned monotonically per-iterator state
    created_at: str             # ISO 8601
    signature_key: str          # PatternSignature.as_key()
    classification: str
    direction: str
    confidence_band: float
    signals: list[str]
    occurrences: int
    first_seen_at: str
    last_seen_at: str
    example_instruments: list[str]
    status: str = "pending"     # pending | promoted | rejected
    reviewed_at: str | None = None


# ---------------------------------------------------------------------------
# Signature computation
# ---------------------------------------------------------------------------

def compute_confidence_band(confidence: float, precision: float) -> float:
    """Round confidence to the nearest `precision` (default 0.1).

    0.73 → 0.70, 0.77 → 0.80. Never exceeds 1.0 or drops below 0.0.
    """
    if precision <= 0:
        return round(confidence, 4)
    banded = round(confidence / precision) * precision
    return max(0.0, min(1.0, round(banded, 4)))


def compute_signals_sig(signals: list[str] | None) -> str:
    """Canonicalize a signals list into a stable signature string.

    Empty/None → "∅". Duplicates collapsed. Order ignored.
    """
    if not signals:
        return "∅"
    uniq = sorted(set(s.strip() for s in signals if s and s.strip()))
    return "|".join(uniq) if uniq else "∅"


def compute_signature(row: dict, precision: float) -> PatternSignature:
    """Build a PatternSignature from a bot_patterns.jsonl row."""
    return PatternSignature(
        classification=str(row.get("classification", "unclear")),
        direction=str(row.get("direction", "flat")),
        confidence_band=compute_confidence_band(
            float(row.get("confidence", 0.0) or 0.0),
            precision,
        ),
        signals_sig=compute_signals_sig(row.get("signals")),
    )


# ---------------------------------------------------------------------------
# Window filter
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def filter_window(rows: list[dict], window_start: datetime) -> list[dict]:
    """Keep rows whose detected_at is within [window_start, ∞)."""
    out: list[dict] = []
    for r in rows:
        ts = _parse_iso(r.get("detected_at") or "")
        if ts is None:
            continue
        if ts >= window_start:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_novel_signatures(
    rows: list[dict],
    catalog: dict,
    min_occurrences: int,
    precision: float,
    now: datetime,
    window_days: int,
    next_id: int = 1,
    existing_candidate_keys: set[str] | None = None,
) -> list[PatternCandidate]:
    """Return a list of new PatternCandidate records for signatures in
    `rows` that:

    - are not already in the live `catalog`
    - are not already in `existing_candidate_keys` (to prevent duplicate
      candidate emission across iterator ticks)
    - have been observed at least `min_occurrences` times within
      `window_days` of `now`

    IDs are assigned starting from `next_id`.
    """
    window_start = now - timedelta(days=window_days)
    windowed = filter_window(rows, window_start)

    existing_keys = set(existing_candidate_keys or set())
    live_keys = set(catalog.keys()) if catalog else set()

    # Tally signature occurrences
    tallies: dict[str, dict] = {}
    for r in windowed:
        sig = compute_signature(r, precision)
        key = sig.as_key()
        if key in live_keys or key in existing_keys:
            continue
        entry = tallies.get(key)
        if entry is None:
            entry = {
                "signature": sig,
                "count": 0,
                "first_seen_at": r.get("detected_at", ""),
                "last_seen_at": r.get("detected_at", ""),
                "instruments": [],
            }
            tallies[key] = entry
        entry["count"] += 1
        ts = r.get("detected_at", "")
        if ts and (not entry["first_seen_at"] or ts < entry["first_seen_at"]):
            entry["first_seen_at"] = ts
        if ts and (not entry["last_seen_at"] or ts > entry["last_seen_at"]):
            entry["last_seen_at"] = ts
        inst = r.get("instrument")
        if inst and inst not in entry["instruments"]:
            entry["instruments"].append(inst)

    # Threshold + emit in deterministic key order
    candidates: list[PatternCandidate] = []
    for key in sorted(tallies.keys()):
        entry = tallies[key]
        if entry["count"] < min_occurrences:
            continue
        sig: PatternSignature = entry["signature"]
        cid = next_id + len(candidates)
        signals_list = (
            sig.signals_sig.split("|") if sig.signals_sig != "∅" else []
        )
        candidates.append(PatternCandidate(
            id=cid,
            created_at=now.isoformat(),
            signature_key=key,
            classification=sig.classification,
            direction=sig.direction,
            confidence_band=sig.confidence_band,
            signals=signals_list,
            occurrences=entry["count"],
            first_seen_at=entry["first_seen_at"],
            last_seen_at=entry["last_seen_at"],
            example_instruments=entry["instruments"][:5],
        ))
    return candidates


# ---------------------------------------------------------------------------
# Catalog mutation (pure dict-in dict-out)
# ---------------------------------------------------------------------------

def promote_to_catalog(
    catalog: dict,
    candidate: dict,
    promoted_at: str,
) -> dict:
    """Return a new catalog dict with the candidate's signature added.

    The catalog shape is `{signature_key: {classification, direction,
    confidence_band, signals, promoted_at, first_seen_at, occurrences}}`.
    Idempotent: promoting a key that already exists is a no-op.
    """
    new_catalog = dict(catalog)
    key = candidate.get("signature_key")
    if not key or key in new_catalog:
        return new_catalog
    new_catalog[key] = {
        "classification": candidate.get("classification"),
        "direction": candidate.get("direction"),
        "confidence_band": candidate.get("confidence_band"),
        "signals": list(candidate.get("signals") or []),
        "promoted_at": promoted_at,
        "first_seen_at": candidate.get("first_seen_at"),
        "occurrences_at_promotion": candidate.get("occurrences", 0),
    }
    return new_catalog


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def candidate_to_dict(c: PatternCandidate) -> dict:
    return asdict(c)


def candidate_from_dict(d: dict) -> PatternCandidate:
    return PatternCandidate(
        id=int(d.get("id", 0)),
        created_at=str(d.get("created_at", "")),
        signature_key=str(d.get("signature_key", "")),
        classification=str(d.get("classification", "")),
        direction=str(d.get("direction", "")),
        confidence_band=float(d.get("confidence_band", 0.0) or 0.0),
        signals=list(d.get("signals") or []),
        occurrences=int(d.get("occurrences", 0)),
        first_seen_at=str(d.get("first_seen_at", "")),
        last_seen_at=str(d.get("last_seen_at", "")),
        example_instruments=list(d.get("example_instruments") or []),
        status=str(d.get("status", "pending")),
        reviewed_at=d.get("reviewed_at"),
    )


def extract_candidate_keys(candidates: list[dict]) -> set[str]:
    """Set of signature_keys from an existing candidates list (any status)."""
    out: set[str] = set()
    for c in candidates:
        key = c.get("signature_key")
        if key:
            out.add(key)
    return out
