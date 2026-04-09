"""Trade Entry Critic — pure-logic signal gathering, grading, and formatting.

The Trade Entry Critic fires a deterministic review of every new position the
daemon observes. This module is the "brain": it gathers a signal stack from
the existing infrastructure (thesis, technicals, catalysts, funding, liquidity
heatmap, bot classifier, lessons), applies fixed grading rules, and formats
the result for Telegram + JSONL persistence.

It is NOT the iterator. The iterator (``cli/daemon/iterators/entry_critic.py``)
is the I/O wrapper that calls these functions. Keep this module pure so unit
tests can drive it with fixture dicts — no network, no sqlite, no filesystem
unless an input path is explicitly supplied.

Design rules
------------
1. **Deterministic.** No AI calls. No LLM. No stochasticity. The output is a
   pure function of the position + the data files on disk. This is the
   non-``ai`` version of the critic; the future ``/critiqueai`` path will
   live in a different module.
2. **Degrade gracefully.** Every signal gather is wrapped in try/except. A
   missing file (``data/heatmap/zones.jsonl`` not yet populated, no thesis
   for the market, no lessons table) returns ``None``/``[]`` and the
   grading rules skip that axis rather than crashing.
3. **Deterministic grading.** ``grade_entry`` produces a fixed set of axes:
   sizing, direction, catalyst_timing, liquidity, funding. Each axis maps
   to a string grade from a closed set. The overall summary is a count of
   pass/warn/fail across the five axes.
4. **Coin normalization.** The xyz clearinghouse prefixes coin names with
   ``xyz:`` (``xyz:BRENTOIL``), native perps do not (``BTC``). Every
   matcher here handles BOTH forms — see ``_coin_matches``. This is a
   recurring bug (CLAUDE.md "Coin name normalization").
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("modules.entry_critic")


# ── Defaults ─────────────────────────────────────────────────

DEFAULT_ZONES_PATH = "data/heatmap/zones.jsonl"
DEFAULT_CASCADES_PATH = "data/heatmap/cascades.jsonl"
DEFAULT_CATALYSTS_PATH = "data/news/catalysts.jsonl"
DEFAULT_BOT_PATTERNS_PATH = "data/research/bot_patterns.jsonl"

# Axis grade constants — closed sets so format functions can switch on them
SIZING_GREAT = "GREAT"
SIZING_OK = "OK"
SIZING_UNDERWEIGHT = "UNDERWEIGHT"
SIZING_OVERWEIGHT = "OVERWEIGHT"
SIZING_UNKNOWN = "UNKNOWN"

DIRECTION_ALIGNED = "ALIGNED"
DIRECTION_OPPOSED = "OPPOSED"
DIRECTION_NO_THESIS = "NO_THESIS"

CATALYST_LEAD = "LEAD"
CATALYST_NEUTRAL = "NEUTRAL"
CATALYST_LATE = "LATE"

LIQUIDITY_SAFE = "SAFE"
LIQUIDITY_CASCADE_RISK = "CASCADE_RISK"
LIQUIDITY_UNKNOWN = "UNKNOWN"

FUNDING_CHEAP = "CHEAP"
FUNDING_FAIR = "FAIR"
FUNDING_EXPENSIVE = "EXPENSIVE"
FUNDING_UNKNOWN = "UNKNOWN"

# Numeric thresholds (tuned conservatively; the main session can calibrate)
SIZING_GREAT_DELTA = 0.10    # within ±10% of target band → GREAT
SIZING_OK_DELTA = 0.30       # within ±30% of target band → OK (else OVER/UNDER)
CATALYST_LEAD_HOURS = 24.0   # major catalyst > 24h ahead = LEAD (positioning time)
CATALYST_LATE_HOURS = 1.0    # major catalyst ≤ 1h ahead = LATE (chasing)
CATALYST_SEVERITY_FLOOR = 3  # only sev≥3 catalysts count as "major"
LIQUIDITY_ZONE_MULT = 1.2    # wall within 1.2×ATR distance → risk
CASCADE_WINDOW_HOURS = 2.0   # cascade in last 2h against entry direction → risk
FUNDING_CHEAP_BPS = 5.0      # |annualized funding| ≤ 5 bps (longs pay ≤ 5bps)
FUNDING_EXPENSIVE_BPS = 30.0 # longs paying ≥ 30 bps annualized = EXPENSIVE


# ── Dataclasses ──────────────────────────────────────────────

@dataclass
class SignalStack:
    """Everything the critic knows about one entry at the moment of review.

    All fields are optional — missing inputs degrade to None/[] so the grader
    can skip axes cleanly. The stack is a flat bag of facts; grading logic
    lives in ``grade_entry``.
    """

    # Identity
    instrument: str
    direction: str                       # "long" | "short"
    entry_price: float
    entry_qty: float
    entry_ts_ms: int
    leverage: Optional[float] = None
    notional_usd: Optional[float] = None
    equity_usd: Optional[float] = None

    # Thesis / conviction
    thesis_direction: Optional[str] = None       # from ThesisState
    thesis_conviction: Optional[float] = None    # 0.0-1.0
    thesis_target_size_pct: Optional[float] = None  # fraction of equity
    thesis_take_profit: Optional[float] = None
    actual_size_pct: Optional[float] = None       # notional / equity

    # Technicals (from MarketSnapshot)
    atr_value: Optional[float] = None
    atr_pct: Optional[float] = None
    rsi: Optional[float] = None
    snapshot_flags: list[str] = field(default_factory=list)
    suggested_stop: Optional[float] = None
    suggested_tp: Optional[float] = None

    # Catalysts — list of dicts with event_date_ms, severity, category, direction
    upcoming_catalysts: list[dict] = field(default_factory=list)

    # Heatmap: resting liquidity walls near entry (from zones.jsonl)
    nearest_wall_bps: Optional[float] = None
    nearest_wall_side: Optional[str] = None       # "bid" | "ask"
    nearest_wall_notional: Optional[float] = None

    # Recent cascades within window in opposite direction
    recent_cascade_against: Optional[dict] = None

    # Bot classifier — latest pattern for this instrument
    bot_pattern: Optional[dict] = None

    # Funding rate (basis points annualized, positive = longs pay)
    funding_bps_annualized: Optional[float] = None

    # Liquidation cushion at entry leverage (fraction of entry price)
    liquidation_cushion_pct: Optional[float] = None

    # Top lessons (from search_lessons)
    lessons: list[dict] = field(default_factory=list)

    # Degraded gathers — axis name → reason. For debugging / JSONL row.
    degraded: dict[str, str] = field(default_factory=dict)


@dataclass
class EntryGrade:
    """Per-axis grades + overall summary. Closed-set strings only."""

    sizing: str = SIZING_UNKNOWN
    sizing_detail: str = ""

    direction: str = DIRECTION_NO_THESIS
    direction_detail: str = ""

    catalyst_timing: str = CATALYST_NEUTRAL
    catalyst_detail: str = ""

    liquidity: str = LIQUIDITY_UNKNOWN
    liquidity_detail: str = ""

    funding: str = FUNDING_UNKNOWN
    funding_detail: str = ""

    suggestions: list[str] = field(default_factory=list)

    # Overall: counts of pass / warn / fail
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    overall_label: str = "UNKNOWN"   # "GOOD ENTRY" | "MIXED ENTRY" | "BAD ENTRY"


# ── Signal gathering ─────────────────────────────────────────


def _coin_matches(a: str, b: str) -> bool:
    """Match two coin identifiers regardless of the ``xyz:`` prefix.

    The xyz clearinghouse returns names WITH the prefix (``xyz:BRENTOIL``);
    native clearinghouse does NOT (``BTC``). Thesis files, catalysts, and
    heatmap rows can use either form. Always compare both.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    a_bare = a[4:] if a.startswith("xyz:") else a
    b_bare = b[4:] if b.startswith("xyz:") else b
    return a_bare == b_bare


def _coin_variants(coin: str) -> set[str]:
    """Return {coin, with xyz prefix, without xyz prefix}."""
    if not coin:
        return set()
    out = {coin}
    if coin.startswith("xyz:"):
        out.add(coin[4:])
    else:
        out.add(f"xyz:{coin}")
    return out


def gather_signal_stack(
    position: dict,
    ctx: Any = None,
    *,
    zones_path: str = DEFAULT_ZONES_PATH,
    cascades_path: str = DEFAULT_CASCADES_PATH,
    catalysts_path: str = DEFAULT_CATALYSTS_PATH,
    bot_patterns_path: str = DEFAULT_BOT_PATTERNS_PATH,
    search_lessons_fn: Any = None,
    now_ms: Optional[int] = None,
) -> SignalStack:
    """Assemble the signal stack for one position entry.

    Parameters
    ----------
    position: dict with keys instrument, direction, entry_price, entry_qty,
              entry_ts_ms, and optionally leverage, notional_usd,
              liquidation_price, mark_price, equity_usd.
    ctx:      TickContext-like with .thesis_states, .market_snapshots. May be
              None in tests — all reads wrapped in try/except.
    zones_path / cascades_path / catalysts_path / bot_patterns_path:
              File overrides for hermetic testing.
    search_lessons_fn: injectable stand-in for ``common.memory.search_lessons``.
              If None, we try to import it lazily. If import fails, lessons=[].
    now_ms:   Override for "now" in milliseconds — lets tests pin time.

    Returns
    -------
    A fully-populated ``SignalStack``. Every gather is individually wrapped
    so one missing input cannot take down the whole critique.
    """
    instrument = str(position.get("instrument") or "")
    direction = str(position.get("direction") or "").lower()
    try:
        entry_price = float(position.get("entry_price") or 0.0)
    except (TypeError, ValueError):
        entry_price = 0.0
    try:
        entry_qty = float(position.get("entry_qty") or 0.0)
    except (TypeError, ValueError):
        entry_qty = 0.0
    try:
        entry_ts_ms = int(position.get("entry_ts_ms") or 0)
    except (TypeError, ValueError):
        entry_ts_ms = 0

    try:
        leverage = float(position.get("leverage")) if position.get("leverage") is not None else None
    except (TypeError, ValueError):
        leverage = None
    try:
        notional = float(position.get("notional_usd")) if position.get("notional_usd") is not None else None
    except (TypeError, ValueError):
        notional = None

    try:
        equity = float(position.get("equity_usd")) if position.get("equity_usd") is not None else None
    except (TypeError, ValueError):
        equity = None
    if equity is None and ctx is not None:
        try:
            total_eq = getattr(ctx, "total_equity", 0.0) or 0.0
            equity = float(total_eq) if total_eq else None
        except Exception as e:  # noqa: BLE001
            log.debug("entry_critic: ctx.total_equity unavailable: %s", e)

    if notional is None and entry_price and entry_qty:
        notional = abs(entry_price * entry_qty)

    stack = SignalStack(
        instrument=instrument,
        direction=direction,
        entry_price=entry_price,
        entry_qty=entry_qty,
        entry_ts_ms=entry_ts_ms,
        leverage=leverage,
        notional_usd=notional,
        equity_usd=equity,
    )

    if equity and notional:
        try:
            stack.actual_size_pct = abs(notional) / equity if equity > 0 else None
        except ZeroDivisionError:
            stack.actual_size_pct = None

    # Liquidation cushion at entry (if adapter reported both)
    try:
        liq_px = position.get("liquidation_price")
        mark_px = position.get("mark_price") or entry_price
        if liq_px and mark_px:
            liq_f = float(liq_px)
            mark_f = float(mark_px)
            if mark_f > 0 and liq_f > 0:
                if direction == "long":
                    stack.liquidation_cushion_pct = (mark_f - liq_f) / mark_f
                else:
                    stack.liquidation_cushion_pct = (liq_f - mark_f) / mark_f
    except (TypeError, ValueError, ZeroDivisionError) as e:
        stack.degraded["liquidation_cushion"] = f"compute-failed: {e}"

    # ── Thesis (from ctx.thesis_states) ─────────────────────
    try:
        if ctx is not None:
            thesis_states = getattr(ctx, "thesis_states", None) or {}
            state = None
            for key, val in thesis_states.items():
                if _coin_matches(key, instrument):
                    state = val
                    break
            if state is not None:
                # ThesisState attributes (common/thesis.py). Accept both
                # dataclass and dict forms for test flexibility.
                stack.thesis_direction = _get(state, "direction")
                conv = _get(state, "conviction")
                try:
                    stack.thesis_conviction = float(conv) if conv is not None else None
                except (TypeError, ValueError):
                    stack.thesis_conviction = None
                tp = _get(state, "take_profit_price")
                try:
                    stack.thesis_take_profit = float(tp) if tp is not None else None
                except (TypeError, ValueError):
                    stack.thesis_take_profit = None
                size_pct = _get(state, "recommended_size_pct")
                try:
                    stack.thesis_target_size_pct = float(size_pct) if size_pct is not None else None
                except (TypeError, ValueError):
                    stack.thesis_target_size_pct = None
            else:
                stack.degraded["thesis"] = "no-thesis-for-market"
    except Exception as e:  # noqa: BLE001
        stack.degraded["thesis"] = f"gather-failed: {e}"

    # ── Market snapshot (from ctx.market_snapshots) ─────────
    try:
        if ctx is not None:
            snaps = getattr(ctx, "market_snapshots", None) or {}
            snap = None
            for key, val in snaps.items():
                if _coin_matches(key, instrument):
                    snap = val
                    break
            if snap is not None:
                # Prefer 4h timeframe for ATR/RSI if available.
                tfs = _get(snap, "timeframes") or {}
                tf = None
                for interval in ("4h", "1h", "1d"):
                    if isinstance(tfs, dict) and interval in tfs:
                        tf = tfs[interval]
                        break
                if tf is not None:
                    atr_val = _get(tf, "atr_value")
                    if atr_val is not None:
                        try:
                            stack.atr_value = float(atr_val)
                        except (TypeError, ValueError):
                            pass
                    atr_p = _get(tf, "atr_pct")
                    if atr_p is not None:
                        try:
                            stack.atr_pct = float(atr_p)
                        except (TypeError, ValueError):
                            pass
                    trend = _get(tf, "trend")
                    if trend is not None:
                        rsi_v = _get(trend, "rsi")
                        try:
                            stack.rsi = float(rsi_v) if rsi_v is not None else None
                        except (TypeError, ValueError):
                            pass
                flags = _get(snap, "flags")
                if isinstance(flags, list):
                    stack.snapshot_flags = list(flags)
                sug_stop = _get(snap, "suggested_stop" if direction == "long" else "suggested_short_stop")
                if sug_stop is not None:
                    try:
                        stack.suggested_stop = float(sug_stop)
                    except (TypeError, ValueError):
                        pass
                sug_tp = _get(snap, "suggested_tp" if direction == "long" else "suggested_short_tp")
                if sug_tp is not None:
                    try:
                        stack.suggested_tp = float(sug_tp)
                    except (TypeError, ValueError):
                        pass
            else:
                stack.degraded["market_snapshot"] = "no-snapshot-for-market"
    except Exception as e:  # noqa: BLE001
        stack.degraded["market_snapshot"] = f"gather-failed: {e}"

    # ── Catalysts window (upcoming, next 48h) ────────────────
    stack.upcoming_catalysts = _load_upcoming_catalysts(
        catalysts_path=catalysts_path,
        instrument=instrument,
        now_ms=now_ms if now_ms is not None else _now_ms(),
        lookahead_hours=48,
        degraded=stack.degraded,
    )

    # ── Heatmap zones — nearest wall near entry ──────────────
    try:
        wall = _nearest_wall(
            zones_path=zones_path,
            instrument=instrument,
            entry_price=entry_price,
            direction=direction,
        )
        if wall:
            stack.nearest_wall_bps = wall.get("distance_bps")
            stack.nearest_wall_side = wall.get("side")
            stack.nearest_wall_notional = wall.get("notional_usd")
    except Exception as e:  # noqa: BLE001
        stack.degraded["heatmap_zones"] = f"gather-failed: {e}"

    # ── Recent cascade against direction ─────────────────────
    try:
        stack.recent_cascade_against = _recent_cascade_against(
            cascades_path=cascades_path,
            instrument=instrument,
            direction=direction,
            window_hours=CASCADE_WINDOW_HOURS,
            now_ms=now_ms if now_ms is not None else _now_ms(),
        )
    except Exception as e:  # noqa: BLE001
        stack.degraded["cascades"] = f"gather-failed: {e}"

    # ── Bot classifier — latest pattern ──────────────────────
    try:
        stack.bot_pattern = _latest_bot_pattern(
            bot_patterns_path=bot_patterns_path,
            instrument=instrument,
        )
    except Exception as e:  # noqa: BLE001
        stack.degraded["bot_pattern"] = f"gather-failed: {e}"

    # ── Funding (from position dict if caller pre-computed) ──
    try:
        if position.get("funding_bps_annualized") is not None:
            stack.funding_bps_annualized = float(position["funding_bps_annualized"])
    except (TypeError, ValueError):
        pass

    # ── Lessons — search_lessons ─────────────────────────────
    try:
        fn = search_lessons_fn
        if fn is None:
            try:
                from common.memory import search_lessons as _sl
                fn = _sl
            except Exception as e:  # noqa: BLE001
                stack.degraded["lessons"] = f"import-failed: {e}"
                fn = None
        if fn is not None:
            try:
                stack.lessons = list(fn(
                    market=instrument,
                    direction=direction,
                    limit=5,
                ) or [])
            except Exception as e:  # noqa: BLE001
                stack.degraded["lessons"] = f"call-failed: {e}"
                stack.lessons = []
    except Exception as e:  # noqa: BLE001
        stack.degraded["lessons"] = f"unexpected: {e}"

    return stack


# ── File readers (pure, wrapped in try/except by caller) ─────


def _load_upcoming_catalysts(
    *,
    catalysts_path: str,
    instrument: str,
    now_ms: int,
    lookahead_hours: float,
    degraded: dict[str, str],
) -> list[dict]:
    """Return catalysts with event_date in [now, now+lookahead] that touch
    ``instrument`` (handling the xyz: prefix on both sides), sorted by
    proximity (soonest first)."""
    path = Path(catalysts_path)
    if not path.exists():
        degraded["catalysts"] = "file-missing"
        return []
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        degraded["catalysts"] = f"read-failed: {e}"
        return []

    variants = _coin_variants(instrument)
    end_ms = now_ms + int(lookahead_hours * 3_600_000)
    hits: list[dict] = []

    from datetime import datetime, timezone

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue

        instruments = row.get("instruments") or []
        if not isinstance(instruments, list):
            continue
        if variants and not any(i in variants for i in instruments):
            continue

        ed = row.get("event_date")
        if not ed:
            continue
        try:
            dt = datetime.fromisoformat(ed)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ed_ms = int(dt.timestamp() * 1000)
        except (TypeError, ValueError):
            continue

        if now_ms <= ed_ms <= end_ms:
            row["_event_ms"] = ed_ms
            hits.append(row)

    hits.sort(key=lambda r: r["_event_ms"])
    return hits[:10]


def _nearest_wall(
    *,
    zones_path: str,
    instrument: str,
    entry_price: float,
    direction: str,
) -> Optional[dict]:
    """Return the nearest ASK wall (for longs — overhead resistance) or BID
    wall (for shorts — support below). Uses the most recent snapshot per
    instrument. Returns None on missing file / no matches."""
    path = Path(zones_path)
    if not path.exists():
        return None
    if entry_price <= 0:
        return None

    variants = _coin_variants(instrument)
    rows_by_instrument: dict[str, list[dict]] = {}

    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            inst = row.get("instrument")
            if inst not in variants:
                continue
            rows_by_instrument.setdefault(inst, []).append(row)
    except OSError:
        return None

    if not rows_by_instrument:
        return None

    # Latest snapshot per instrument
    all_latest: list[dict] = []
    for _inst, rows in rows_by_instrument.items():
        if not rows:
            continue
        latest_ts = max(r.get("snapshot_at", "") for r in rows)
        all_latest.extend([r for r in rows if r.get("snapshot_at", "") == latest_ts])

    if not all_latest:
        return None

    # Longs care about ASK walls above (overhead), shorts about BID below.
    wanted_side = "ask" if direction == "long" else "bid"
    candidates = [r for r in all_latest if r.get("side") == wanted_side]
    if not candidates:
        return None

    # Nearest by distance_bps (already computed in the zone rows)
    candidates.sort(key=lambda r: abs(float(r.get("distance_bps", 1e9))))
    return candidates[0]


def _recent_cascade_against(
    *,
    cascades_path: str,
    instrument: str,
    direction: str,
    window_hours: float,
    now_ms: int,
) -> Optional[dict]:
    """Return the most recent cascade within window that's on the OPPOSITE
    side of the entry (longs care about long-cascade liquidations beneath
    them, shorts care about short-cascade liquidations above). Returns None
    if no match / missing file."""
    path = Path(cascades_path)
    if not path.exists():
        return None

    variants = _coin_variants(instrument)
    cutoff_ms = now_ms - int(window_hours * 3_600_000)
    wanted_side = direction.lower()  # cascade.side records which side got liquidated

    from datetime import datetime, timezone

    latest: Optional[dict] = None
    latest_ts = -1
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("instrument") not in variants:
                continue
            if row.get("side") != wanted_side:
                continue
            ts = row.get("detected_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                row_ms = int(dt.timestamp() * 1000)
            except (TypeError, ValueError):
                continue
            if row_ms < cutoff_ms:
                continue
            if row_ms > latest_ts:
                latest_ts = row_ms
                latest = row
    except OSError:
        return None

    return latest


def _latest_bot_pattern(*, bot_patterns_path: str, instrument: str) -> Optional[dict]:
    """Return the most recent BotPattern row for the instrument, or None."""
    path = Path(bot_patterns_path)
    if not path.exists():
        return None
    variants = _coin_variants(instrument)
    latest: Optional[dict] = None
    latest_ts = ""
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("instrument") not in variants:
                continue
            ts = row.get("detected_at", "")
            if ts > latest_ts:
                latest_ts = ts
                latest = row
    except OSError:
        return None
    return latest


# ── Grading ──────────────────────────────────────────────────


def grade_entry(stack: SignalStack) -> EntryGrade:
    """Apply deterministic grading rules to the signal stack.

    Rules (closed set — tweak thresholds at the top of the module, not
    inside this function, so the rules stay auditable):

    SIZING
      - If ``actual_size_pct`` and ``thesis_target_size_pct`` both known:
          |actual - target| / target ≤ 10%  → GREAT
          |actual - target| / target ≤ 30%  → OK
          actual > target                    → OVERWEIGHT
          actual < target                    → UNDERWEIGHT
      - Otherwise UNKNOWN.

    DIRECTION
      - If no thesis: NO_THESIS.
      - If thesis.direction matches entry direction: ALIGNED.
      - Else: OPPOSED (the loudest failure).

    CATALYST_TIMING
      - If no upcoming catalyst above severity floor in next 48h: NEUTRAL.
      - If nearest major catalyst ≤ CATALYST_LATE_HOURS away: LATE.
      - If nearest major catalyst ≥ CATALYST_LEAD_HOURS away: LEAD.
      - Otherwise NEUTRAL (between 1h and 24h).

    LIQUIDITY
      - If no zones data: UNKNOWN.
      - If a recent opposing cascade exists: CASCADE_RISK (overrides).
      - If nearest wall within LIQUIDITY_ZONE_MULT × ATR%: CASCADE_RISK
        (actually "wall-close" but we fold into CASCADE_RISK for a
         single-axis output to keep the grid simple).
      - Otherwise SAFE.

    FUNDING
      - If unknown: UNKNOWN.
      - Longs: funding ≤ FUNDING_CHEAP_BPS → CHEAP; ≥ FUNDING_EXPENSIVE_BPS → EXPENSIVE; else FAIR.
      - Shorts: inverted (negative funding = longs pay = shorts collect = CHEAP for shorts).
    """
    grade = EntryGrade()

    _grade_sizing(stack, grade)
    _grade_direction(stack, grade)
    _grade_catalyst_timing(stack, grade)
    _grade_liquidity(stack, grade)
    _grade_funding(stack, grade)
    _compute_overall(grade)
    _collect_suggestions(stack, grade)

    return grade


def _grade_sizing(stack: SignalStack, grade: EntryGrade) -> None:
    actual = stack.actual_size_pct
    target = stack.thesis_target_size_pct
    if actual is None or target is None or target <= 0:
        grade.sizing = SIZING_UNKNOWN
        if actual is not None:
            grade.sizing_detail = f"actual={actual*100:.1f}% (no target)"
        elif target is not None:
            grade.sizing_detail = f"target={target*100:.1f}% (actual unknown)"
        return

    delta = (actual - target) / target
    grade.sizing_detail = (
        f"{actual*100:.1f}% of equity vs {target*100:.1f}% target "
        f"(delta={delta*100:+.1f}%)"
    )
    if abs(delta) <= SIZING_GREAT_DELTA:
        grade.sizing = SIZING_GREAT
    elif abs(delta) <= SIZING_OK_DELTA:
        grade.sizing = SIZING_OK
    elif delta > 0:
        grade.sizing = SIZING_OVERWEIGHT
    else:
        grade.sizing = SIZING_UNDERWEIGHT


def _grade_direction(stack: SignalStack, grade: EntryGrade) -> None:
    if not stack.thesis_direction:
        grade.direction = DIRECTION_NO_THESIS
        grade.direction_detail = "no thesis for this market"
        return
    t_dir = stack.thesis_direction.lower()
    e_dir = stack.direction.lower()
    conv = stack.thesis_conviction
    conv_str = f"conviction {conv:.2f}" if conv is not None else "conviction ?"
    if t_dir == e_dir:
        grade.direction = DIRECTION_ALIGNED
        grade.direction_detail = f"thesis {t_dir}, {conv_str}"
    elif t_dir == "flat":
        # Flat thesis is neither aligned nor opposed — call it no-thesis.
        grade.direction = DIRECTION_NO_THESIS
        grade.direction_detail = f"thesis flat, {conv_str}"
    else:
        grade.direction = DIRECTION_OPPOSED
        grade.direction_detail = f"thesis {t_dir} but entry {e_dir}, {conv_str}"


def _grade_catalyst_timing(stack: SignalStack, grade: EntryGrade) -> None:
    majors = [c for c in stack.upcoming_catalysts if isinstance(c, dict) and int(c.get("severity", 0)) >= CATALYST_SEVERITY_FLOOR]
    if not majors:
        grade.catalyst_timing = CATALYST_NEUTRAL
        grade.catalyst_detail = "no major catalyst in 48h window"
        return
    nearest = majors[0]  # gather sorts ascending by event time
    now_ms = stack.entry_ts_ms or _now_ms()
    try:
        ev_ms = int(nearest.get("_event_ms") or 0)
    except (TypeError, ValueError):
        ev_ms = 0
    hours_to = (ev_ms - now_ms) / 3_600_000.0 if ev_ms else 999.0
    cat = nearest.get("category", "?")
    sev = int(nearest.get("severity", 0))
    grade.catalyst_detail = f"{cat} sev={sev} in {hours_to:.1f}h"
    if hours_to <= CATALYST_LATE_HOURS:
        grade.catalyst_timing = CATALYST_LATE
    elif hours_to >= CATALYST_LEAD_HOURS:
        grade.catalyst_timing = CATALYST_LEAD
    else:
        grade.catalyst_timing = CATALYST_NEUTRAL


def _grade_liquidity(stack: SignalStack, grade: EntryGrade) -> None:
    # Cascade overrides wall-proximity
    if stack.recent_cascade_against:
        cas = stack.recent_cascade_against
        grade.liquidity = LIQUIDITY_CASCADE_RISK
        oi = cas.get("oi_delta_pct", 0)
        sev = cas.get("severity", "?")
        grade.liquidity_detail = (
            f"recent {stack.direction} cascade sev={sev} OI {oi:+.1f}%"
        )
        return

    # Wall proximity — needs both nearest wall and ATR% for a meaningful check
    if stack.nearest_wall_bps is not None and stack.atr_pct is not None:
        wall_pct_abs = abs(float(stack.nearest_wall_bps)) / 100.0  # bps → percent
        threshold_pct = float(stack.atr_pct) * LIQUIDITY_ZONE_MULT
        if wall_pct_abs <= threshold_pct:
            grade.liquidity = LIQUIDITY_CASCADE_RISK
            grade.liquidity_detail = (
                f"{stack.nearest_wall_side or '?'} wall {wall_pct_abs:.2f}% "
                f"away (threshold {threshold_pct:.2f}%)"
            )
            return
        grade.liquidity = LIQUIDITY_SAFE
        grade.liquidity_detail = (
            f"nearest {stack.nearest_wall_side or '?'} wall {wall_pct_abs:.2f}% "
            f"away (> {threshold_pct:.2f}% ATR×{LIQUIDITY_ZONE_MULT})"
        )
        return

    # No heatmap data — only return SAFE if we also have no signs of trouble
    if stack.nearest_wall_bps is None and stack.atr_pct is None:
        grade.liquidity = LIQUIDITY_UNKNOWN
        grade.liquidity_detail = "no heatmap/ATR data"
        return

    grade.liquidity = LIQUIDITY_SAFE
    grade.liquidity_detail = "no cascade-level risk detected"


def _grade_funding(stack: SignalStack, grade: EntryGrade) -> None:
    bps = stack.funding_bps_annualized
    if bps is None:
        grade.funding = FUNDING_UNKNOWN
        grade.funding_detail = "no funding data"
        return
    direction = stack.direction.lower()
    # Cost from the entry-holder's POV: positive bps = longs pay.
    cost_bps = bps if direction == "long" else -bps
    grade.funding_detail = f"{bps:+.1f} bps annualized ({'pay' if cost_bps > 0 else 'collect'} {abs(cost_bps):.1f})"
    if cost_bps <= FUNDING_CHEAP_BPS:
        grade.funding = FUNDING_CHEAP
    elif cost_bps >= FUNDING_EXPENSIVE_BPS:
        grade.funding = FUNDING_EXPENSIVE
    else:
        grade.funding = FUNDING_FAIR


def _compute_overall(grade: EntryGrade) -> None:
    """Count pass/warn/fail across axes. Pick an overall label."""
    pass_set = {SIZING_GREAT, SIZING_OK, DIRECTION_ALIGNED, CATALYST_LEAD, LIQUIDITY_SAFE, FUNDING_CHEAP, FUNDING_FAIR}
    warn_set = {SIZING_UNDERWEIGHT, CATALYST_NEUTRAL, DIRECTION_NO_THESIS, LIQUIDITY_UNKNOWN, FUNDING_UNKNOWN, SIZING_UNKNOWN}
    fail_set = {SIZING_OVERWEIGHT, DIRECTION_OPPOSED, CATALYST_LATE, LIQUIDITY_CASCADE_RISK, FUNDING_EXPENSIVE}

    axes = [grade.sizing, grade.direction, grade.catalyst_timing, grade.liquidity, grade.funding]
    p = sum(1 for a in axes if a in pass_set)
    w = sum(1 for a in axes if a in warn_set)
    f = sum(1 for a in axes if a in fail_set)
    grade.pass_count = p
    grade.warn_count = w
    grade.fail_count = f

    if f >= 2:
        grade.overall_label = "BAD ENTRY"
    elif f == 1:
        grade.overall_label = "MIXED ENTRY"
    elif p >= 3:
        grade.overall_label = "GOOD ENTRY"
    else:
        grade.overall_label = "MIXED ENTRY"


def _collect_suggestions(stack: SignalStack, grade: EntryGrade) -> None:
    """Generate actionable suggestions. Deterministic — no LLM."""
    s = grade.suggestions

    if grade.sizing == SIZING_OVERWEIGHT and stack.actual_size_pct and stack.thesis_target_size_pct:
        excess_pct = (stack.actual_size_pct - stack.thesis_target_size_pct) * 100
        s.append(
            f"Size is {excess_pct:.1f}% over thesis target — consider trimming back"
        )
    elif grade.sizing == SIZING_UNDERWEIGHT and stack.actual_size_pct and stack.thesis_target_size_pct:
        short_pct = (stack.thesis_target_size_pct - stack.actual_size_pct) * 100
        s.append(
            f"Under target by {short_pct:.1f}% — room to scale in per thesis"
        )

    if grade.direction == DIRECTION_OPPOSED:
        s.append(
            f"Entry direction opposes thesis — close and re-evaluate, or flip thesis"
        )

    if grade.catalyst_timing == CATALYST_LATE and stack.upcoming_catalysts:
        nearest = stack.upcoming_catalysts[0]
        if isinstance(nearest, dict):
            cat = nearest.get("category", "?")
        else:
            cat = "?"
        s.append(
            f"Major catalyst ({cat}) imminent — consider waiting for the print"
        )

    if grade.liquidity == LIQUIDITY_CASCADE_RISK:
        if stack.recent_cascade_against:
            s.append(
                "Recent cascade on your side of the book — expect follow-through before recovery"
            )
        else:
            s.append(
                "Resting wall within 1.2×ATR — expect a fight through the level"
            )

    if grade.funding == FUNDING_EXPENSIVE:
        s.append(
            f"Funding is expensive at {stack.funding_bps_annualized:+.1f} bps — watch holding cost"
        )

    # Stop placement hint
    if stack.suggested_stop and stack.atr_value:
        s.append(
            f"Technical suggests SL near ${stack.suggested_stop:.4g} (3×ATR {stack.atr_value:.4g})"
        )
    if stack.thesis_take_profit:
        s.append(
            f"Thesis TP: ${stack.thesis_take_profit:.4g}"
        )


# ── Formatters ───────────────────────────────────────────────


_ICON = {
    SIZING_GREAT: "GOOD",
    SIZING_OK: "OK",
    SIZING_UNKNOWN: "?",
    SIZING_UNDERWEIGHT: "WARN",
    SIZING_OVERWEIGHT: "FAIL",
    DIRECTION_ALIGNED: "GOOD",
    DIRECTION_NO_THESIS: "?",
    DIRECTION_OPPOSED: "FAIL",
    CATALYST_LEAD: "GOOD",
    CATALYST_NEUTRAL: "OK",
    CATALYST_LATE: "FAIL",
    LIQUIDITY_SAFE: "GOOD",
    LIQUIDITY_UNKNOWN: "?",
    LIQUIDITY_CASCADE_RISK: "FAIL",
    FUNDING_CHEAP: "GOOD",
    FUNDING_FAIR: "OK",
    FUNDING_UNKNOWN: "?",
    FUNDING_EXPENSIVE: "FAIL",
}


def format_critique_telegram(grade: EntryGrade, stack: SignalStack) -> str:
    """Produce a conversational Telegram message.

    No emojis used internally — the caller (iterator) can prepend an emoji
    when it posts. We keep this pure so tests can assert-on substrings.
    """
    direction_s = stack.direction.upper()
    qty_s = f"{stack.entry_qty:g}" if stack.entry_qty else "?"
    entry_s = f"${stack.entry_price:,.4g}" if stack.entry_price else "?"
    header = f"Entry Critique — {stack.instrument} {direction_s} {qty_s} @ {entry_s}"

    rows: list[str] = [header, ""]

    def _line(label: str, axis_value: str, detail: str) -> str:
        icon = _ICON.get(axis_value, "?")
        return f"[{icon}] {label}: {axis_value} ({detail})" if detail else f"[{icon}] {label}: {axis_value}"

    rows.append(_line("Sizing", grade.sizing, grade.sizing_detail))
    rows.append(_line("Direction", grade.direction, grade.direction_detail))
    rows.append(_line("Timing", grade.catalyst_timing, grade.catalyst_detail))
    rows.append(_line("Liquidity", grade.liquidity, grade.liquidity_detail))
    rows.append(_line("Funding", grade.funding, grade.funding_detail))

    # Lessons
    if stack.lessons:
        rows.append("")
        rows.append(f"Top lessons ({len(stack.lessons)}):")
        for lesson in stack.lessons[:5]:
            lid = lesson.get("id") or lesson.get("lesson_id") or "?"
            summary = (lesson.get("summary") or "").strip()
            if len(summary) > 80:
                summary = summary[:77] + "..."
            rows.append(f"  #{lid} {summary}")

    rows.append("")
    rows.append(
        f"OVERALL: {grade.overall_label} "
        f"({grade.pass_count} pass / {grade.warn_count} warn / {grade.fail_count} fail)"
    )

    if grade.suggestions:
        rows.append("")
        rows.append("Suggestions:")
        for sug in grade.suggestions:
            rows.append(f"  - {sug}")

    return "\n".join(rows)


def format_critique_jsonl(grade: EntryGrade, stack: SignalStack) -> dict:
    """Produce the JSONL row for ``data/research/entry_critiques.jsonl``."""
    return {
        "schema_version": 1,
        "kind": "entry_critique",
        "created_at": _now_iso(),
        "instrument": stack.instrument,
        "direction": stack.direction,
        "entry_price": stack.entry_price,
        "entry_qty": stack.entry_qty,
        "entry_ts_ms": stack.entry_ts_ms,
        "leverage": stack.leverage,
        "notional_usd": stack.notional_usd,
        "equity_usd": stack.equity_usd,
        "actual_size_pct": stack.actual_size_pct,
        "grade": {
            "sizing": grade.sizing,
            "sizing_detail": grade.sizing_detail,
            "direction": grade.direction,
            "direction_detail": grade.direction_detail,
            "catalyst_timing": grade.catalyst_timing,
            "catalyst_detail": grade.catalyst_detail,
            "liquidity": grade.liquidity,
            "liquidity_detail": grade.liquidity_detail,
            "funding": grade.funding,
            "funding_detail": grade.funding_detail,
            "pass_count": grade.pass_count,
            "warn_count": grade.warn_count,
            "fail_count": grade.fail_count,
            "overall_label": grade.overall_label,
            "suggestions": list(grade.suggestions),
        },
        "signals": {
            "thesis_direction": stack.thesis_direction,
            "thesis_conviction": stack.thesis_conviction,
            "thesis_target_size_pct": stack.thesis_target_size_pct,
            "thesis_take_profit": stack.thesis_take_profit,
            "atr_value": stack.atr_value,
            "atr_pct": stack.atr_pct,
            "rsi": stack.rsi,
            "snapshot_flags": list(stack.snapshot_flags),
            "upcoming_catalysts": _sanitize_catalysts(stack.upcoming_catalysts),
            "nearest_wall_bps": stack.nearest_wall_bps,
            "nearest_wall_side": stack.nearest_wall_side,
            "nearest_wall_notional": stack.nearest_wall_notional,
            "recent_cascade_against": stack.recent_cascade_against,
            "bot_pattern": stack.bot_pattern,
            "funding_bps_annualized": stack.funding_bps_annualized,
            "liquidation_cushion_pct": stack.liquidation_cushion_pct,
            "lesson_ids": [l.get("id") for l in stack.lessons if l.get("id") is not None],
        },
        "degraded": dict(stack.degraded),
    }


def _sanitize_catalysts(rows: list[dict]) -> list[dict]:
    """Drop the internal _event_ms cache key from the JSONL output."""
    out: list[dict] = []
    for r in rows[:10]:
        if not isinstance(r, dict):
            continue
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        out.append(clean)
    return out


# ── Helpers ──────────────────────────────────────────────────


def _get(obj: Any, name: str) -> Any:
    """Attribute-or-key access: works for dataclasses and dicts."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
