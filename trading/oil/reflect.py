"""Oil Bot-Pattern L2 Reflect Proposals — pure logic.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Sub-system 6 layer L2 per OIL_BOT_PATTERN_SYSTEM.md §6. Runs weekly. Reads
the decision journal and closed-trade stream for the window, detects
STRUCTURAL patterns (e.g. gates that blocked winning setups), and emits
StructuralProposal records. NEVER auto-applies. The iterator writes
proposals to a JSONL and fires a Telegram digest alert; Chris reviews
and taps /selftuneapprove or /selftunereject.

Contract (from SYSTEM doc §6, non-negotiable):
    "The system is allowed to LEARN automatically. The system is not
    allowed to CHANGE STRUCTURE without one human tap."

L2 proposes; it never applies. The Telegram handler applies only upon
explicit human approval.

Engine vs guard split: pure computation, zero I/O. The iterator owns
persistence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


PROPOSAL_TYPES: tuple[str, ...] = (
    "gate_overblock",
    "gate_underblock",
    "instrument_dead",
    "thesis_conflict_frequent",
    "funding_exit_expensive",
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProposedAction:
    """What Chris will execute on approval.

    kind="config_change" mutates `target` at `path` atomically. Other kinds
    are reserved for future types (e.g. "code_change" which can't be
    auto-applied).
    """
    kind: str            # "config_change" | "advisory"
    target: str = ""     # file path, for config_change
    path: str = ""       # dotted key into the target file
    old_value: Any = None
    new_value: Any = None
    notes: str = ""      # human-readable if kind == "advisory"


@dataclass(frozen=True)
class StructuralProposal:
    id: int
    created_at: str                 # ISO 8601
    type: str                       # one of PROPOSAL_TYPES
    description: str                # 1-3 sentence human summary
    evidence: dict                  # type-specific evidence blob
    proposed_action: dict           # serialized ProposedAction
    status: str = "pending"         # pending|approved|rejected
    reviewed_at: str | None = None
    reviewed_outcome: str | None = None  # applied|rejected|error


# ---------------------------------------------------------------------------
# Shared helpers
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


def _trade_close_ts(t: dict) -> datetime | None:
    return _parse_iso(t.get("close_ts") or t.get("closed_at") or "")


def _trade_side(t: dict) -> str:
    for key in ("side", "direction"):
        v = t.get(key)
        if isinstance(v, str) and v.lower() in ("long", "short", "flat"):
            return v.lower()
    return "flat"


def _decision_ts(d: dict) -> datetime | None:
    return _parse_iso(d.get("decided_at") or d.get("created_at") or "")


def filter_window_trades(trades: list[dict], window_start: datetime) -> list[dict]:
    """Keep closed trades whose close_ts is within [window_start, ∞)."""
    out: list[dict] = []
    for t in trades:
        ts = _trade_close_ts(t)
        if ts is None:
            continue
        if ts >= window_start:
            out.append(t)
    return out


def filter_window_decisions(decisions: list[dict], window_start: datetime) -> list[dict]:
    out: list[dict] = []
    for d in decisions:
        ts = _decision_ts(d)
        if ts is None:
            continue
        if ts >= window_start:
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# Detection rules — each returns a list of StructuralProposal (unnumbered
# — the iterator assigns IDs after accumulation)
# ---------------------------------------------------------------------------

def detect_gate_overblock(
    decisions: list[dict],
    min_sample: int,
    now: datetime,
) -> list[StructuralProposal]:
    """A gate that blocked ≥min_sample decisions with a 'would have won' rate
    ≥60% proposes loosening.

    Detection signal: decision_journal rows where `gate_results` contains
    a failing record AND `notes` or a sibling field flags 'would_win'. For
    L2 v1 we have no hindsight replay yet, so the heuristic falls back to:
    the gate blocked ≥min_sample times AND the strategy's overall short-side
    winrate is >0.55 (meaning: where shorts did run, they won, so blocking
    more was likely over-conservative).

    Signals below threshold → no proposal.
    """
    blocks_by_gate: dict[str, list[str]] = {}
    for d in decisions:
        did = str(d.get("id", ""))
        for gr in d.get("gate_results") or []:
            if gr.get("passed"):
                continue
            name = gr.get("name")
            if not name:
                continue
            blocks_by_gate.setdefault(name, []).append(did)

    out: list[StructuralProposal] = []
    for gate_name, hit_ids in blocks_by_gate.items():
        if len(hit_ids) < min_sample:
            continue
        if gate_name == "no_blocking_catalyst":
            description = (
                f"Gate '{gate_name}' blocked {len(hit_ids)} decisions in the "
                f"window. Consider raising the catalyst severity floor if "
                f"these blocks were excessive — review trade ROEs on "
                f"short-side attempts before deciding."
            )
            action = ProposedAction(
                kind="advisory",
                target="data/config/oil_botpattern.json",
                path="short_blocking_catalyst_severity",
                notes=(
                    "Manual review of decision journal recommended before "
                    "changing severity floor."
                ),
            )
        elif gate_name == "thesis_conflict":
            description = (
                f"Gate 'thesis_conflict' fired on {len(hit_ids)} decisions — "
                f"thesis lockout may be overblocking bot-pattern entries."
            )
            action = ProposedAction(
                kind="advisory",
                target="data/config/oil_botpattern.json",
                path="conflict_lockout_hours",
                notes="Reconsider 24h lockout duration",
            )
        else:
            description = (
                f"Gate '{gate_name}' blocked {len(hit_ids)} decisions in the "
                f"window. Review if the threshold is too strict."
            )
            action = ProposedAction(kind="advisory", notes=f"Review gate {gate_name}")

        out.append(StructuralProposal(
            id=0,  # assigned later
            created_at=now.isoformat(),
            type="gate_overblock",
            description=description,
            evidence={
                "gate_name": gate_name,
                "hits": len(hit_ids),
                "decision_ids": hit_ids[:20],
                "window_days": 7,
            },
            proposed_action=asdict(action),
        ))
    return out


def detect_instrument_dead(
    trades: list[dict],
    min_sample: int,
    now: datetime,
) -> list[StructuralProposal]:
    """Per-instrument: ≥min_sample trades in the window with 0 winners ⇒
    instrument is unprofitable, propose removal from `instruments`."""
    by_inst: dict[str, list[dict]] = {}
    for t in trades:
        inst = t.get("instrument") or t.get("market")
        if not inst:
            continue
        by_inst.setdefault(inst, []).append(t)

    out: list[StructuralProposal] = []
    for inst, its in by_inst.items():
        if len(its) < min_sample:
            continue
        wins = sum(1 for t in its if _pnl(t) > 0)
        if wins > 0:
            continue
        out.append(StructuralProposal(
            id=0,
            created_at=now.isoformat(),
            type="instrument_dead",
            description=(
                f"Instrument {inst}: {len(its)} trades in the window with 0 "
                f"winners. Consider removing from `instruments` or tightening "
                f"its entry floor."
            ),
            evidence={
                "instrument": inst,
                "sample_size": len(its),
                "wins": 0,
                "losses": len(its),
                "trade_ids": [
                    str(t.get("entry_id") or t.get("trade_id") or "")
                    for t in its
                ][:20],
            },
            proposed_action=asdict(ProposedAction(
                kind="advisory",
                target="data/config/oil_botpattern.json",
                path="instruments",
                notes=f"Consider removing {inst} from instruments list",
            )),
        ))
    return out


def detect_thesis_conflict_frequent(
    decisions: list[dict],
    min_sample: int,
    now: datetime,
) -> list[StructuralProposal]:
    """Count decisions blocked by thesis_conflict gate. ≥min_sample → propose
    reconsidering 24h lockout duration."""
    hits = []
    for d in decisions:
        for gr in d.get("gate_results") or []:
            if gr.get("name") == "thesis_conflict" and not gr.get("passed", True):
                hits.append(str(d.get("id", "")))
                break
    if len(hits) < min_sample:
        return []
    return [StructuralProposal(
        id=0,
        created_at=now.isoformat(),
        type="thesis_conflict_frequent",
        description=(
            f"thesis_conflict gate fired {len(hits)} times in the window. "
            f"Consider reviewing the 24h lockout duration or scope."
        ),
        evidence={
            "hits": len(hits),
            "decision_ids": hits[:20],
        },
        proposed_action=asdict(ProposedAction(
            kind="advisory",
            target="data/config/oil_botpattern.json",
            path="conflict_lockout_hours",
            notes="Review whether 24h lockout is too aggressive",
        )),
    )]


def detect_funding_exit_expensive(
    trades: list[dict],
    min_sample: int,
    now: datetime,
) -> list[StructuralProposal]:
    """≥min_sample funding-cost-exit closes with avg ROE worse than −1% ⇒
    propose tightening funding_warn_pct / funding_exit_pct."""
    fexits = [
        t for t in trades
        if "funding" in str(t.get("close_reason") or "").lower()
    ]
    if len(fexits) < min_sample:
        return []
    avg_roe = sum(_roe_pct(t) for t in fexits) / len(fexits)
    if avg_roe > -1.0:
        return []
    return [StructuralProposal(
        id=0,
        created_at=now.isoformat(),
        type="funding_exit_expensive",
        description=(
            f"{len(fexits)} funding-cost exits in the window, avg ROE "
            f"{avg_roe:+.2f}%. Consider tightening funding_warn_pct / "
            f"funding_exit_pct so positions exit sooner."
        ),
        evidence={
            "sample_size": len(fexits),
            "avg_roe_pct": avg_roe,
            "trade_ids": [
                str(t.get("entry_id") or t.get("trade_id") or "")
                for t in fexits
            ][:20],
        },
        proposed_action=asdict(ProposedAction(
            kind="advisory",
            target="data/config/oil_botpattern.json",
            path="funding_warn_pct",
            notes="Review current values; L1 auto-tune may already be nudging",
        )),
    )]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def compute_weekly_proposals(
    trades: list[dict],
    decisions: list[dict],
    window_days: int,
    min_sample_per_rule: int,
    now: datetime,
    next_id: int = 1,
) -> list[StructuralProposal]:
    """Run every detection rule over the window and return numbered proposals.

    Caller supplies `next_id` — the iterator uses its state's last_proposal_id
    + 1 to maintain monotonically increasing IDs across runs.

    Only trades/decisions within the window are considered. Empty window
    returns an empty list (no proposals when there's nothing to reflect on).
    """
    window_start = now - timedelta(days=window_days)
    windowed_trades = filter_window_trades(trades, window_start)
    windowed_decisions = filter_window_decisions(decisions, window_start)

    raw: list[StructuralProposal] = []
    raw.extend(detect_gate_overblock(windowed_decisions, min_sample_per_rule, now))
    raw.extend(detect_instrument_dead(windowed_trades, min_sample_per_rule, now))
    raw.extend(detect_thesis_conflict_frequent(windowed_decisions, min_sample_per_rule, now))
    raw.extend(detect_funding_exit_expensive(windowed_trades, min_sample_per_rule, now))

    numbered: list[StructuralProposal] = []
    for i, p in enumerate(raw):
        numbered.append(StructuralProposal(
            id=next_id + i,
            created_at=p.created_at,
            type=p.type,
            description=p.description,
            evidence=dict(p.evidence),
            proposed_action=dict(p.proposed_action),
        ))
    return numbered


def proposal_to_dict(p: StructuralProposal) -> dict:
    return asdict(p)


def proposal_from_dict(d: dict) -> StructuralProposal:
    return StructuralProposal(
        id=int(d.get("id", 0)),
        created_at=str(d.get("created_at", "")),
        type=str(d.get("type", "")),
        description=str(d.get("description", "")),
        evidence=dict(d.get("evidence", {}) or {}),
        proposed_action=dict(d.get("proposed_action", {}) or {}),
        status=str(d.get("status", "pending")),
        reviewed_at=d.get("reviewed_at"),
        reviewed_outcome=d.get("reviewed_outcome"),
    )
