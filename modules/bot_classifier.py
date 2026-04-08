"""Bot-Pattern Classifier — pure logic.

Spec: docs/plans/OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md

Sub-system 4 of the Oil Bot-Pattern Strategy. Read-only, heuristic-only.
NO ML, NO LLM. Layer L5 (ML overlay) is deferred per SYSTEM doc §6.

🔮 DEFERRED: ML overlay + LLM assistance — see the "DEFERRED ENHANCEMENT"
section at the bottom of OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md for the
plan to revisit this once ≥100 closed trades exist in the journal.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


CLASSIFICATIONS = (
    "bot_driven_overextension",
    "informed_move",
    "mixed",
    "unclear",
)


@dataclass(frozen=True)
class BotPattern:
    id: str
    instrument: str
    detected_at: datetime
    lookback_minutes: int
    classification: str  # one of CLASSIFICATIONS
    confidence: float    # 0..1
    direction: str       # "up" | "down" | "flat"
    price_at_detection: float
    price_change_pct: float
    signals: list[str] = field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# JSONL I/O
# ---------------------------------------------------------------------------

def _to_dict(p: BotPattern) -> dict:
    out = asdict(p)
    out["detected_at"] = p.detected_at.isoformat()
    return out


def _from_dict(raw: dict) -> BotPattern:
    return BotPattern(
        id=raw["id"],
        instrument=raw["instrument"],
        detected_at=datetime.fromisoformat(raw["detected_at"]),
        lookback_minutes=int(raw["lookback_minutes"]),
        classification=raw["classification"],
        confidence=float(raw["confidence"]),
        direction=raw["direction"],
        price_at_detection=float(raw["price_at_detection"]),
        price_change_pct=float(raw["price_change_pct"]),
        signals=list(raw.get("signals", [])),
        notes=raw.get("notes", ""),
    )


def append_pattern(jsonl_path: str, p: BotPattern) -> None:
    path = Path(jsonl_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(_to_dict(p)) + "\n")


def read_patterns(jsonl_path: str) -> list[BotPattern]:
    path = Path(jsonl_path)
    if not path.exists():
        return []
    out: list[BotPattern] = []
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(_from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# Classifier — pure function
# ---------------------------------------------------------------------------

def classify_pattern(
    *,
    instrument: str,
    detected_at: datetime,
    price_at_detection: float,
    price_change_pct: float,
    atr: float,
    recent_cascades: list[dict],
    recent_catalysts: list[dict],
    supply_state: dict | None,
    cascade_window_min: int = 30,
    catalyst_floor: int = 4,
    supply_freshness_hours: int = 72,
    atr_mult_for_big_move: float = 1.5,
    lookback_minutes: int = 60,
    min_price_move_pct: float = 0.5,
) -> BotPattern:
    """Classify a recent move as bot-driven, informed, mixed, or unclear.

    Inputs are plain dicts so the function stays testable without dragging
    in the daemon iterator types.

    `recent_cascades` items: dicts with keys side ("long"|"short"),
    severity (1..4), oi_delta_pct (float), detected_at (iso str or
    datetime), funding_jump_bps (float).

    `recent_catalysts` items: dicts with keys severity (int), direction
    (optional, "up"|"down"|"neutral"), published_at (iso str or datetime),
    instruments (list), category (str).

    `supply_state`: dict with keys computed_at (iso str or datetime),
    active_disruption_count (int), active_chokepoints (list[str]).
    """
    direction = "up" if price_change_pct > 0 else "down" if price_change_pct < 0 else "flat"
    abs_move = abs(price_change_pct)

    # Floor: don't classify noise
    if abs_move < min_price_move_pct:
        return _make_pattern(
            instrument, detected_at, lookback_minutes,
            "unclear", 0.5, direction, price_at_detection, price_change_pct,
            ["price_move_below_classification_floor"],
            "move below min_price_move_pct — no classification",
        )

    bot_signals: list[str] = []
    informed_signals: list[str] = []

    # ----------------------------------------------------------------
    # Bot-driven signals
    # ----------------------------------------------------------------
    cascade_window = timedelta(minutes=cascade_window_min)
    matching_cascade = _find_matching_cascade(
        recent_cascades, detected_at, cascade_window, direction
    )
    if matching_cascade is not None:
        side = matching_cascade.get("side", "?")
        sev = int(matching_cascade.get("severity", 1))
        oi_delta = float(matching_cascade.get("oi_delta_pct", 0))
        bot_signals.append(
            f"cascade_{side}_sev{sev} (OI {oi_delta:+.1f}%)"
        )

    high_sev_catalyst_24h = _find_high_sev_catalyst(
        recent_catalysts, detected_at, hours=24, floor=catalyst_floor
    )
    if high_sev_catalyst_24h is None:
        bot_signals.append("no_high_sev_catalyst_in_24h")

    fresh_supply_upgrade = _supply_is_fresh(
        supply_state, detected_at, supply_freshness_hours
    )
    if not fresh_supply_upgrade:
        bot_signals.append("no_fresh_supply_upgrade_72h")

    if atr > 0 and abs_move >= (atr * atr_mult_for_big_move):
        bot_signals.append(
            f"price_move_{abs_move:.2f}%_exceeds_{atr_mult_for_big_move}x_atr"
        )

    # ----------------------------------------------------------------
    # Informed-move signals
    # ----------------------------------------------------------------
    if high_sev_catalyst_24h is not None:
        cat_dir = (high_sev_catalyst_24h.get("direction") or "").lower()
        cat_sev = int(high_sev_catalyst_24h.get("severity", 0))
        if cat_dir == direction or cat_dir in ("", "neutral"):
            informed_signals.append(
                f"catalyst_sev{cat_sev}_within_24h ({high_sev_catalyst_24h.get('category', '?')})"
            )

    if fresh_supply_upgrade and supply_state:
        active = int(supply_state.get("active_disruption_count", 0))
        # A fresh upgrade is a bullish-on-oil signal: more disruptions
        # → tighter physical supply → up-side. Match against direction.
        if direction == "up" and active > 0:
            informed_signals.append(
                f"fresh_supply_upgrade ({active} active disruptions)"
            )

    chokepoints = (supply_state or {}).get("active_chokepoints") or []
    if chokepoints and direction == "up":
        informed_signals.append(
            f"active_chokepoint:{','.join(chokepoints[:2])}"
        )

    # ----------------------------------------------------------------
    # Score + resolve
    # ----------------------------------------------------------------
    bot_score = min(0.9, 0.5 + 0.1 * len(bot_signals))
    informed_score = min(0.9, 0.5 + 0.1 * len(informed_signals))

    classification, confidence = _resolve(bot_score, informed_score)

    notes_parts = []
    if classification == "bot_driven_overextension":
        notes_parts.append(f"{len(bot_signals)} bot signals dominate")
    elif classification == "informed_move":
        notes_parts.append(f"{len(informed_signals)} informed signals dominate")
    elif classification == "mixed":
        notes_parts.append(
            f"both sides present (bot={bot_score:.2f}, informed={informed_score:.2f})"
        )
    else:
        notes_parts.append("insufficient signal separation")
    notes_parts.append(f"direction={direction} move={price_change_pct:+.2f}%")

    return _make_pattern(
        instrument, detected_at, lookback_minutes,
        classification, confidence, direction,
        price_at_detection, price_change_pct,
        bot_signals + informed_signals,
        " | ".join(notes_parts),
    )


def _resolve(bot_score: float, informed_score: float) -> tuple[str, float]:
    if bot_score >= 0.65 and informed_score >= 0.65 and abs(bot_score - informed_score) <= 0.1:
        return ("mixed", min(0.65, min(bot_score, informed_score)))
    if bot_score > informed_score + 0.1:
        return ("bot_driven_overextension", round(bot_score, 2))
    if informed_score > bot_score + 0.1:
        return ("informed_move", round(informed_score, 2))
    return ("unclear", 0.5)


def _make_pattern(
    instrument: str,
    detected_at: datetime,
    lookback_minutes: int,
    classification: str,
    confidence: float,
    direction: str,
    price_at_detection: float,
    price_change_pct: float,
    signals: list[str],
    notes: str,
) -> BotPattern:
    return BotPattern(
        id=f"{instrument}_{detected_at.isoformat()}",
        instrument=instrument,
        detected_at=detected_at,
        lookback_minutes=lookback_minutes,
        classification=classification,
        confidence=confidence,
        direction=direction,
        price_at_detection=price_at_detection,
        price_change_pct=price_change_pct,
        signals=signals,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------

def _coerce_dt(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _find_matching_cascade(
    cascades: list[dict],
    detected_at: datetime,
    window: timedelta,
    direction: str,
) -> dict | None:
    """Return the most recent cascade within the window whose side matches.

    A long cascade (longs liquidated) corresponds to a falling-price move
    (direction "down"). A short cascade corresponds to a rising-price move.
    """
    expected_side = "long" if direction == "down" else "short" if direction == "up" else None
    cutoff = detected_at - window
    best: tuple[datetime, dict] | None = None
    for c in cascades:
        ts = _coerce_dt(c.get("detected_at"))
        if ts is None or ts < cutoff or ts > detected_at:
            continue
        if expected_side and c.get("side") != expected_side:
            continue
        if best is None or ts > best[0]:
            best = (ts, c)
    return best[1] if best else None


def _find_high_sev_catalyst(
    catalysts: list[dict],
    detected_at: datetime,
    hours: int,
    floor: int,
) -> dict | None:
    cutoff = detected_at - timedelta(hours=hours)
    best: tuple[datetime, dict] | None = None
    for c in catalysts:
        try:
            sev = int(c.get("severity", 0))
        except (TypeError, ValueError):
            continue
        if sev < floor:
            continue
        ts = _coerce_dt(c.get("published_at") or c.get("scheduled_at"))
        if ts is None or ts < cutoff or ts > detected_at:
            continue
        if best is None or sev > int(best[1].get("severity", 0)):
            best = (ts, c)
    return best[1] if best else None


def _supply_is_fresh(
    supply_state: dict | None,
    detected_at: datetime,
    hours: int,
) -> bool:
    if not supply_state:
        return False
    ts = _coerce_dt(supply_state.get("computed_at"))
    if ts is None:
        return False
    return (detected_at - ts) <= timedelta(hours=hours)
