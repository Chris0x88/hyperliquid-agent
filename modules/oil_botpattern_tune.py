"""Oil Bot-Pattern L1 Bounded Auto-Tune — pure logic.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Sub-system 6 layer L1 per OIL_BOT_PATTERN_SYSTEM.md §6. Reads closed
oil_botpattern trades plus the per-decision journal, computes bounded
nudges to a small whitelist of params in oil_botpattern.json, and returns
structured TuneProposal records. Persistence lives in the daemon iterator
(cli/daemon/iterators/oil_botpattern_tune.py).

Contract (non-negotiable, copied from SYSTEM doc §6):
    "The system is allowed to LEARN automatically. The system is not
    allowed to CHANGE STRUCTURE without one human tap."

This module nudges VALUES within hard bounds. It never adds, removes, or
renames params. Any proposed value is clamped to [bound.min, bound.max]
before it is returned — violations are not possible by construction.

Engine vs guard split: this module follows the modules/CLAUDE.md rule
that engines are pure computation. Zero I/O. The iterator does all file
reads and writes.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Constants — the L1 tunable whitelist. Anything outside this set is
# structural and must be changed by a human (or via L2 reflect proposals).
# ---------------------------------------------------------------------------

TUNABLE_PARAMS: tuple[str, ...] = (
    "long_min_edge",
    "short_min_edge",
    "funding_warn_pct",
    "funding_exit_pct",
    "short_blocking_catalyst_severity",
)

# Params that are integers (step is always ±1, not rel_step_max). Anything
# not listed here is treated as float.
INTEGER_PARAMS: frozenset[str] = frozenset({
    "short_blocking_catalyst_severity",
})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamBound:
    """Hard min/max for a tunable parameter."""
    name: str
    min: float
    max: float
    type: str  # "float" | "int"

    def __post_init__(self) -> None:
        if self.min > self.max:
            raise ValueError(
                f"ParamBound {self.name}: min ({self.min}) > max ({self.max})"
            )
        if self.type not in ("float", "int"):
            raise ValueError(
                f"ParamBound {self.name}: type must be 'float' or 'int', got {self.type!r}"
            )

    def clamp(self, value: float) -> float:
        """Clamp a raw value into [min, max], preserving integer type if needed."""
        clamped = max(self.min, min(self.max, value))
        if self.type == "int":
            return int(round(clamped))
        return float(clamped)


@dataclass(frozen=True)
class OutcomeStats:
    """Aggregate outcome statistics over a trade window, per direction.

    Consumed by nudge heuristics. All fields are zero-safe: an empty window
    returns zeros, not NaNs.
    """
    sample_size: int = 0
    winrate: float = 0.0
    avg_roe_pct: float = 0.0
    long_sample: int = 0
    long_winrate: float = 0.0
    long_avg_roe_pct: float = 0.0
    long_funding_exit_rate: float = 0.0
    long_avg_funding_exit_roe_pct: float = 0.0
    long_avg_hold_hours: float = 0.0
    short_sample: int = 0
    short_winrate: float = 0.0
    short_avg_roe_pct: float = 0.0


@dataclass(frozen=True)
class TuneProposal:
    """A single bounded nudge for one parameter.

    A TuneProposal is emitted only when all gates pass: sufficient sample,
    nudge direction is non-zero, rate limit clear, and the clamped proposed
    value differs from the current value.
    """
    param: str
    old_value: float
    new_value: float
    reason: str
    stats_sample_size: int
    stats_snapshot: dict = field(default_factory=dict)
    trade_ids_considered: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TuneAuditRecord:
    """Audit record for one applied nudge. Append-only to audit_jsonl."""
    applied_at: str         # ISO 8601 UTC
    param: str
    old_value: float
    new_value: float
    reason: str
    stats_sample_size: int
    stats_snapshot: dict = field(default_factory=dict)
    trade_ids_considered: list[str] = field(default_factory=list)
    source: str = "l1_auto_tune"  # override to "reflect_approved" from L2


# ---------------------------------------------------------------------------
# Bounds parsing
# ---------------------------------------------------------------------------

def parse_bounds(bounds_cfg: dict) -> dict[str, ParamBound]:
    """Parse the `bounds` block of oil_botpattern_tune.json into ParamBound records.

    Unknown params (not in TUNABLE_PARAMS) are silently dropped with a
    warning left to the caller. Malformed entries raise ValueError.
    """
    out: dict[str, ParamBound] = {}
    for name, spec in (bounds_cfg or {}).items():
        if name not in TUNABLE_PARAMS:
            # Silently drop unknown params — L1 is whitelist-only.
            continue
        if not isinstance(spec, dict):
            raise ValueError(f"bounds[{name}] must be an object, got {type(spec).__name__}")
        try:
            bmin = float(spec["min"])
            bmax = float(spec["max"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"bounds[{name}] missing/invalid min/max: {e}") from e
        btype = str(spec.get("type", "float")).lower()
        out[name] = ParamBound(name=name, min=bmin, max=bmax, type=btype)
    return out


# ---------------------------------------------------------------------------
# Outcome aggregation over the closed-trade window
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


def _pnl(trade: dict) -> float:
    """Pull realised PnL from a closed-trade row, being generous about keys."""
    for key in ("realised_pnl_usd", "realized_pnl_usd", "pnl", "pnl_usd"):
        v = trade.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _roe_pct(trade: dict) -> float:
    for key in ("roe_pct", "realised_roe_pct", "realized_roe_pct"):
        v = trade.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _side(trade: dict) -> str:
    """Return 'long', 'short', or 'flat' for a closed trade row."""
    for key in ("side", "direction"):
        v = trade.get(key)
        if isinstance(v, str) and v.lower() in ("long", "short", "flat"):
            return v.lower()
    # Fallback: infer from signed size if present
    size = trade.get("size")
    try:
        s = float(size)
        if s > 0:
            return "long"
        if s < 0:
            return "short"
    except (TypeError, ValueError):
        pass
    return "flat"


def _is_funding_exit(trade: dict) -> bool:
    reason = str(trade.get("close_reason") or "").lower()
    return "funding" in reason


def _hold_hours(trade: dict) -> float:
    """Best-effort entry→close hours from the trade row."""
    holding_ms = trade.get("holding_ms")
    if holding_ms is not None:
        try:
            return float(holding_ms) / 1000.0 / 3600.0
        except (TypeError, ValueError):
            pass
    entry = _parse_iso(trade.get("entry_ts") or trade.get("opened_at") or "")
    close = _parse_iso(trade.get("close_ts") or trade.get("closed_at") or "")
    if entry and close:
        delta = close - entry
        return max(0.0, delta.total_seconds() / 3600.0)
    return 0.0


def compute_outcome_stats(trades: list[dict]) -> OutcomeStats:
    """Aggregate a list of closed oil_botpattern trades into OutcomeStats.

    The iterator filters to `strategy_id="oil_botpattern"` and
    `status="closed"` before calling this — this function does no filtering
    of its own beyond direction split.
    """
    n = len(trades)
    if n == 0:
        return OutcomeStats()

    total_wins = 0
    total_roe = 0.0
    longs: list[dict] = []
    shorts: list[dict] = []
    for t in trades:
        pnl = _pnl(t)
        roe = _roe_pct(t)
        if pnl > 0:
            total_wins += 1
        total_roe += roe
        side = _side(t)
        if side == "long":
            longs.append(t)
        elif side == "short":
            shorts.append(t)

    long_n = len(longs)
    short_n = len(shorts)

    long_winrate = 0.0
    long_avg_roe = 0.0
    long_funding_exit_rate = 0.0
    long_avg_funding_exit_roe = 0.0
    long_avg_hold = 0.0
    if long_n:
        long_wins = sum(1 for t in longs if _pnl(t) > 0)
        long_winrate = long_wins / long_n
        long_avg_roe = sum(_roe_pct(t) for t in longs) / long_n
        long_funding_exits = [t for t in longs if _is_funding_exit(t)]
        if long_funding_exits:
            long_funding_exit_rate = len(long_funding_exits) / long_n
            long_avg_funding_exit_roe = (
                sum(_roe_pct(t) for t in long_funding_exits) / len(long_funding_exits)
            )
        long_avg_hold = sum(_hold_hours(t) for t in longs) / long_n

    short_winrate = 0.0
    short_avg_roe = 0.0
    if short_n:
        short_wins = sum(1 for t in shorts if _pnl(t) > 0)
        short_winrate = short_wins / short_n
        short_avg_roe = sum(_roe_pct(t) for t in shorts) / short_n

    return OutcomeStats(
        sample_size=n,
        winrate=total_wins / n,
        avg_roe_pct=total_roe / n,
        long_sample=long_n,
        long_winrate=long_winrate,
        long_avg_roe_pct=long_avg_roe,
        long_funding_exit_rate=long_funding_exit_rate,
        long_avg_funding_exit_roe_pct=long_avg_funding_exit_roe,
        long_avg_hold_hours=long_avg_hold,
        short_sample=short_n,
        short_winrate=short_winrate,
        short_avg_roe_pct=short_avg_roe,
    )


# ---------------------------------------------------------------------------
# Decision-journal aggregation (gate-block analysis for short severity param)
# ---------------------------------------------------------------------------

def count_gate_blocks(
    decisions: list[dict],
    gate_name: str,
    direction: str | None = None,
) -> int:
    """Count decisions whose gate_results include a failing record for gate_name.

    If direction is provided, restrict to decisions with matching direction.
    Tolerant of missing/short gate_results lists — a missing gate is not a
    failure, just a skip.
    """
    hits = 0
    for d in decisions:
        if direction is not None and d.get("direction") != direction:
            continue
        for gr in d.get("gate_results") or []:
            if gr.get("name") == gate_name and not gr.get("passed", True):
                hits += 1
                break
    return hits


# ---------------------------------------------------------------------------
# Per-param nudge heuristics. Each returns a signed nudge direction
# (+1, -1, 0) given the outcome stats. The magnitude is chosen later.
# ---------------------------------------------------------------------------

def nudge_direction_long_min_edge(stats: OutcomeStats, min_sample: int) -> int:
    """Tighten (raise) when longs lose often; loosen (lower) when longs print."""
    if stats.long_sample < min_sample:
        return 0
    if stats.long_winrate > 0.60:
        return -1  # lower the floor → more entries
    if stats.long_winrate < 0.40:
        return +1  # raise the floor → fewer entries
    return 0


def nudge_direction_short_min_edge(stats: OutcomeStats, min_sample: int) -> int:
    if stats.short_sample < min_sample:
        return 0
    if stats.short_winrate > 0.60:
        return -1
    if stats.short_winrate < 0.40:
        return +1
    return 0


def nudge_direction_funding_warn_pct(stats: OutcomeStats, min_sample: int) -> int:
    """Tighten when too many longs exit on funding for a loss; loosen when no
    funding exits happen despite long holds."""
    if stats.long_sample < min_sample:
        return 0
    # Too many money-losing funding exits → tighten warn (lower warn_pct)
    if (
        stats.long_funding_exit_rate >= 0.30
        and stats.long_avg_funding_exit_roe_pct < 0
    ):
        return -1
    # No funding exits but longs held > 7 days on average → loosen warn
    if stats.long_funding_exit_rate == 0.0 and stats.long_avg_hold_hours >= 7 * 24:
        return +1
    return 0


def nudge_direction_funding_exit_pct(stats: OutcomeStats, min_sample: int) -> int:
    """Same logic shape as warn, but one step more conservative: only tighten
    (auto-exit sooner) on clear funding-grind losses, only loosen if no
    funding exits AND long holds are very long."""
    if stats.long_sample < min_sample:
        return 0
    if (
        stats.long_funding_exit_rate >= 0.30
        and stats.long_avg_funding_exit_roe_pct < 0
    ):
        return -1
    if stats.long_funding_exit_rate == 0.0 and stats.long_avg_hold_hours >= 14 * 24:
        return +1
    return 0


def nudge_direction_short_catalyst_sev(
    stats: OutcomeStats,
    decisions: list[dict],
    min_sample: int,
) -> int:
    """Tighten (raise severity floor) if too few would-have-been-winning
    shorts were blocked by this gate. Loosen (lower severity floor) if the
    gate blocked many winners.

    In L1 v1 we do NOT have access to would-have-been-winning analysis —
    that requires a replay loop over decision journal entries with price
    lookups. For this wedge the heuristic falls back to: if the short
    layer has lost money overall in the window, AND the gate has NOT been
    blocking much → tighten. If the short layer is profitable AND the
    gate has been blocking ≥3 shorts → loosen.
    """
    if stats.short_sample < min_sample:
        return 0
    blocks = count_gate_blocks(decisions, "no_blocking_catalyst", "short")
    if stats.short_avg_roe_pct < 0 and blocks < 2:
        return +1
    if stats.short_avg_roe_pct > 0 and blocks >= 3:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Core nudge driver
# ---------------------------------------------------------------------------

def _step_for(param: str, current: float, rel_step_max: float) -> float:
    """Compute the nudge step magnitude for a param.

    Integer params step by exactly 1. Float params step by
    max(rel_step_max * |current|, 1e-6). The minimum is a safety net
    against zero-current edge cases (current=0 would produce zero step
    and never move off the floor).
    """
    if param in INTEGER_PARAMS:
        return 1.0
    rel = rel_step_max * abs(current)
    return max(rel, 1e-6)


def _last_nudge_ts_for(
    audit_index: dict[str, str],
    param: str,
) -> datetime | None:
    ts_str = audit_index.get(param)
    if not ts_str:
        return None
    return _parse_iso(ts_str)


def _reason_for(param: str, direction: int, stats: OutcomeStats) -> str:
    """Human-readable reason string for the audit log."""
    if param == "long_min_edge":
        return (
            f"long winrate {stats.long_winrate:.2%} over {stats.long_sample} trades"
            f" → {'loosen' if direction < 0 else 'tighten'} entry floor"
        )
    if param == "short_min_edge":
        return (
            f"short winrate {stats.short_winrate:.2%} over {stats.short_sample} trades"
            f" → {'loosen' if direction < 0 else 'tighten'} entry floor"
        )
    if param == "funding_warn_pct":
        return (
            f"long funding-exit rate {stats.long_funding_exit_rate:.0%}"
            f" (avg ROE {stats.long_avg_funding_exit_roe_pct:+.2f}%),"
            f" avg hold {stats.long_avg_hold_hours:.1f}h"
            f" → {'tighten' if direction < 0 else 'loosen'} warn"
        )
    if param == "funding_exit_pct":
        return (
            f"long funding-exit rate {stats.long_funding_exit_rate:.0%}"
            f" (avg ROE {stats.long_avg_funding_exit_roe_pct:+.2f}%),"
            f" avg hold {stats.long_avg_hold_hours:.1f}h"
            f" → {'tighten' if direction < 0 else 'loosen'} exit"
        )
    if param == "short_blocking_catalyst_severity":
        return (
            f"short avg ROE {stats.short_avg_roe_pct:+.2f}% over {stats.short_sample} trades"
            f" → {'tighten (raise floor)' if direction > 0 else 'loosen (lower floor)'}"
        )
    return f"nudge direction {direction} over sample {stats.sample_size}"


def compute_proposals(
    current_config: dict,
    bounds: dict[str, ParamBound],
    trades: list[dict],
    decisions: list[dict],
    audit_index: dict[str, str],
    now: datetime,
    min_sample: int,
    rel_step_max: float,
    rate_limit_hours: int,
) -> list[TuneProposal]:
    """Compute all valid TuneProposals for this tick.

    This is the core deterministic function the iterator calls. Zero I/O.

    :param current_config: loaded oil_botpattern.json as a dict
    :param bounds: parsed ParamBound records keyed by param name
    :param trades: closed oil_botpattern trades within the window
    :param decisions: decision-journal rows within the window (gate-block input)
    :param audit_index: {param_name → iso_ts of last nudge}. Empty means
                        "never nudged". Used for rate limiting.
    :param now: current tick time (UTC)
    :param min_sample: minimum per-direction sample for a nudge
    :param rel_step_max: max step as a fraction of current float value
    :param rate_limit_hours: minimum hours between nudges for a single param
    """
    stats = compute_outcome_stats(trades)
    proposals: list[TuneProposal] = []

    trade_ids = [str(t.get("entry_id") or t.get("trade_id") or t.get("id") or "")
                 for t in trades]
    trade_ids = [tid for tid in trade_ids if tid]

    rate_cutoff = now - timedelta(hours=rate_limit_hours)

    for param in TUNABLE_PARAMS:
        bound = bounds.get(param)
        if bound is None:
            continue
        current = current_config.get(param)
        if current is None:
            continue
        try:
            current_f = float(current)
        except (TypeError, ValueError):
            continue

        if param == "long_min_edge":
            direction = nudge_direction_long_min_edge(stats, min_sample)
        elif param == "short_min_edge":
            direction = nudge_direction_short_min_edge(stats, min_sample)
        elif param == "funding_warn_pct":
            direction = nudge_direction_funding_warn_pct(stats, min_sample)
        elif param == "funding_exit_pct":
            direction = nudge_direction_funding_exit_pct(stats, min_sample)
        elif param == "short_blocking_catalyst_severity":
            direction = nudge_direction_short_catalyst_sev(stats, decisions, min_sample)
        else:
            direction = 0

        if direction == 0:
            continue

        # Rate limit
        last = _last_nudge_ts_for(audit_index, param)
        if last is not None and last > rate_cutoff:
            continue

        step = _step_for(param, current_f, rel_step_max)
        proposed_raw = current_f + direction * step
        proposed = bound.clamp(proposed_raw)

        # funding_exit_pct must stay ≥ funding_warn_pct + 0.5 — invariant
        # between the two params, keeps the exit strictly above the warn.
        if param == "funding_exit_pct":
            warn_val = current_config.get("funding_warn_pct", 0.0)
            try:
                warn_f = float(warn_val)
            except (TypeError, ValueError):
                warn_f = 0.0
            if proposed < warn_f + 0.5:
                proposed = bound.clamp(warn_f + 0.5)
        if param == "funding_warn_pct":
            exit_val = current_config.get("funding_exit_pct", 9999.0)
            try:
                exit_f = float(exit_val)
            except (TypeError, ValueError):
                exit_f = 9999.0
            if proposed > exit_f - 0.5:
                proposed = bound.clamp(exit_f - 0.5)

        if _approx_equal(proposed, current_f, bound.type):
            continue

        proposals.append(TuneProposal(
            param=param,
            old_value=current_f if bound.type == "float" else int(round(current_f)),
            new_value=proposed,
            reason=_reason_for(param, direction, stats),
            stats_sample_size=stats.sample_size,
            stats_snapshot=asdict(stats),
            trade_ids_considered=list(trade_ids),
        ))

    return proposals


def _approx_equal(a: float, b: float, ptype: str) -> bool:
    if ptype == "int":
        return int(round(a)) == int(round(b))
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Config mutation — pure dict-in dict-out
# ---------------------------------------------------------------------------

def apply_proposals(
    current_config: dict,
    proposals: list[TuneProposal],
) -> tuple[dict, list[TuneAuditRecord]]:
    """Return (new_config, audit_records) after applying every proposal.

    The input dict is shallow-copied; nested structures are NOT deep-copied
    because the tunable whitelist is all top-level scalars. Audit records
    carry `applied_at` = now().
    """
    new_config = dict(current_config)
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    audits: list[TuneAuditRecord] = []
    for p in proposals:
        if p.param not in TUNABLE_PARAMS:
            continue
        # Integer storage for integer params
        if p.param in INTEGER_PARAMS:
            new_config[p.param] = int(round(p.new_value))
        else:
            new_config[p.param] = float(p.new_value)
        audits.append(TuneAuditRecord(
            applied_at=now_iso,
            param=p.param,
            old_value=p.old_value,
            new_value=new_config[p.param],
            reason=p.reason,
            stats_sample_size=p.stats_sample_size,
            stats_snapshot=dict(p.stats_snapshot),
            trade_ids_considered=list(p.trade_ids_considered),
            source="l1_auto_tune",
        ))
    return new_config, audits


# ---------------------------------------------------------------------------
# Audit serialization helpers
# ---------------------------------------------------------------------------

def audit_to_dict(record: TuneAuditRecord) -> dict:
    return asdict(record)


def build_audit_index(audit_rows: list[dict]) -> dict[str, str]:
    """Build {param → latest applied_at iso} from an audit JSONL stream.

    Used for rate limiting. Tolerant of rows missing keys — they are
    ignored silently.
    """
    idx: dict[str, str] = {}
    for row in audit_rows:
        param = row.get("param")
        ts = row.get("applied_at")
        if not param or not ts:
            continue
        prev = idx.get(param)
        if prev is None or ts > prev:
            idx[param] = ts
    return idx
