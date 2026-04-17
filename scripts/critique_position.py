#!/usr/bin/env python3
"""One-shot trade entry critic — runs the same grading the daemon iterator
does, on demand, for any open position. Persists the critique row to
data/research/entry_critiques.jsonl exactly like the iterator would.

Why this exists:
  - The daemon iterator (`daemon/iterators/entry_critic.py`) only sees
    positions it sees in `ctx.positions`. If the daemon hasn't restarted
    since the multi-wallet account_state fix, it's still consuming a
    main-only position list — so vault positions (the BTC vault long, in
    particular) never get critiqued.
  - This script reads positions from the SAME source the dashboard uses
    (`fetch_registered_account_state`) so it sees ALL wallets correctly.
  - Output is identical to the iterator's: same grade, same JSONL row,
    same Telegram-style summary.

Usage:
  scripts/critique_position.py                # critique every open position
  scripts/critique_position.py --coin BTC     # critique just BTC
  scripts/critique_position.py --coin SILVER  # critique just SILVER
  scripts/critique_position.py --dry-run      # print but don't persist

The fingerprint dedup that the iterator uses is also honoured — running
twice on the same entry won't write duplicate rows.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Resolve project root so common.* imports work
_AGENT = Path(__file__).resolve().parent.parent
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from common.account_state import fetch_registered_account_state  # noqa: E402
from engines.protection.entry_critic import (  # noqa: E402
    SignalStack,
    format_critique_jsonl,
    format_critique_telegram,
    gather_signal_stack,
    grade_entry,
)

CRITIQUES_JSONL = _AGENT / "data" / "research" / "entry_critiques.jsonl"
STATE_PATH = _AGENT / "data" / "daemon" / "entry_critic_state.json"


def _load_fingerprints() -> set:
    if not STATE_PATH.exists():
        return set()
    try:
        return set(json.loads(STATE_PATH.read_text()).get("fingerprints", []))
    except Exception:
        return set()


def _save_fingerprints(fps: set) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"fingerprints": sorted(fps)}, indent=2))


def _fingerprint(p: dict) -> str:
    """Match daemon iterator fingerprint shape: instrument | direction |
    rounded entry | rounded entry_ts_sec."""
    return "|".join([
        str(p.get("instrument", "")),
        str(p.get("direction", "")),
        f"{round(float(p.get('entry_price', 0)), 2)}",
        f"{int(float(p.get('entry_ts_ms', 0))) // 1000}",
    ])


def _bundle_position_to_critic_dict(p: dict, equity: float) -> dict:
    """Map common.account_state position dict → entry_critic input shape."""
    size = float(p.get("size") or 0)
    direction = "long" if size > 0 else "short"
    entry = float(p.get("entry") or 0)
    qty = abs(size)
    notional = entry * qty
    leverage_raw = p.get("leverage")
    try:
        leverage = float(leverage_raw) if leverage_raw not in (None, "?") else None
    except (TypeError, ValueError):
        leverage = None
    liq = p.get("liq")
    try:
        liq_price = float(liq) if liq is not None else None
    except (TypeError, ValueError):
        liq_price = None
    return {
        "instrument": p["coin"],
        "direction": direction,
        "entry_price": entry,
        "entry_qty": qty,
        # The bundle doesn't carry an entry_ts — we don't have it from the HL
        # API on a per-position basis. Use 0 here; the gather path tolerates
        # missing entry_ts (catalyst window will return empty list).
        "entry_ts_ms": 0,
        "leverage": leverage,
        "notional_usd": notional,
        "liquidation_price": liq_price,
        "equity_usd": equity,
    }


def _persist_jsonl(row: dict) -> None:
    CRITIQUES_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with CRITIQUES_JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def critique_one(p: dict, equity: float, *, dry_run: bool = False, force: bool = False) -> None:
    """Run the full critic on one position dict (already in critic shape)."""
    fp = _fingerprint(p)
    seen = _load_fingerprints()
    if fp in seen and not force:
        print(f"\n[SKIP] {p['instrument']} {p['direction']} — already critiqued (fingerprint dedup). Use --force to re-run.")
        return

    print(f"\n══════ CRITIQUE: {p['instrument']} {p['direction'].upper()} ══════")
    stack: SignalStack = gather_signal_stack(p)
    grade = grade_entry(stack)

    # Telegram-formatted summary (the same one the daemon would have sent)
    print(format_critique_telegram(grade, stack))

    if dry_run:
        print("\n[DRY-RUN] not persisting to entry_critiques.jsonl")
        return

    row = format_critique_jsonl(grade, stack)
    _persist_jsonl(row)
    seen.add(fp)
    _save_fingerprints(seen)
    print(f"\n[OK] critique persisted to {CRITIQUES_JSONL.relative_to(_AGENT)} (1 row)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--coin", help="Critique only this coin (matches with or without xyz: prefix)")
    ap.add_argument("--dry-run", action="store_true", help="Print but don't persist")
    ap.add_argument("--force", action="store_true", help="Re-run even if fingerprint already in state")
    args = ap.parse_args()

    bundle = fetch_registered_account_state()
    positions = bundle.get("positions", [])
    if not positions:
        print("No open positions found.")
        return 0

    equity = float(bundle.get("account", {}).get("total_equity") or 0)

    target_coin = (args.coin or "").upper().replace("XYZ:", "")
    targets = []
    for p in positions:
        coin_norm = p["coin"].upper().replace("XYZ:", "")
        if not target_coin or coin_norm == target_coin:
            targets.append(p)

    if not targets:
        print(f"No open position matched coin filter: {args.coin}")
        return 1

    print(f"Found {len(targets)} position(s) to critique. Account total_equity: ${equity:,.2f}")
    for p in targets:
        critic_input = _bundle_position_to_critic_dict(p, equity)
        critique_one(critic_input, equity, dry_run=args.dry_run, force=args.force)

    return 0


if __name__ == "__main__":
    sys.exit(main())
