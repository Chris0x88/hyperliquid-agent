#!/usr/bin/env python3
"""Reset the high-water mark (HWM) to the current live equity.

Usage:
    .venv/bin/python scripts/reset_hwm.py [--reason "stale snapshot after equity formula revert"]

Safety:
    - Reads current equity from fetch_registered_account_state().
    - Backs up the existing hwm.json to hwm.json.pre-reset-<ts>.json before overwriting.
    - Writes new hwm.json with {hwm, ts, reset_at, reset_reason}.

This script is intended for use after a bad equity formula taints the HWM
(e.g. the 2026-04-17 revert that briefly reported equity as ~$21 instead of ~$631,
causing HWM to be stuck at $600 and drawdown to show -85%).

Run from agent-cli/ directory.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure agent-cli root is on sys.path so common.* imports resolve
_agent_cli = Path(__file__).resolve().parent.parent
if str(_agent_cli) not in sys.path:
    sys.path.insert(0, str(_agent_cli))

from common.account_state import fetch_registered_account_state

HWM_PATH = _agent_cli / "data" / "snapshots" / "hwm.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset HWM to current live equity.")
    parser.add_argument(
        "--reason",
        default="manual reset via reset_hwm.py",
        help="Human-readable reason for the reset (stored in the JSON file)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen but don't write anything",
    )
    args = parser.parse_args()

    print("Fetching current equity from HL API…")
    bundle = fetch_registered_account_state()
    if not bundle.get("accounts"):
        print("ERROR: No wallet configured or API error — aborting.", file=sys.stderr)
        sys.exit(1)

    acct = bundle.get("account", {})
    try:
        current_equity = round(float(acct.get("total_equity") or 0), 6)
    except (TypeError, ValueError):
        current_equity = 0.0

    if current_equity <= 0:
        print("ERROR: Could not fetch positive equity — aborting.", file=sys.stderr)
        sys.exit(1)

    # Read existing HWM for display + backup
    pre_reset: dict = {}
    if HWM_PATH.exists():
        try:
            pre_reset = json.loads(HWM_PATH.read_text())
        except Exception as e:
            print(f"WARN: Could not read existing hwm.json: {e}")

    old_hwm = pre_reset.get("hwm")
    print(f"Current equity : ${current_equity:.4f}")
    print(f"Existing HWM   : ${old_hwm:.4f}" if old_hwm else "Existing HWM   : (none)")
    print(f"Reason         : {args.reason}")

    if args.dry_run:
        print("\n[dry-run] Would write new HWM and backup — no files changed.")
        return

    now_ts = int(time.time())
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    # Backup before overwrite
    backup_path = HWM_PATH.parent / f"hwm.json.pre-reset-{now_ts}.json"
    if pre_reset:
        backup_path.write_text(
            json.dumps(
                {**pre_reset, "backed_up_at": now_iso, "backup_reason": args.reason},
                indent=2,
            )
        )
        print(f"\nBacked up old HWM → {backup_path}")

    # Write new HWM
    new_hwm = {
        "hwm": current_equity,
        "ts": now_ts,
        "reset_at": now_iso,
        "reset_reason": args.reason,
    }
    HWM_PATH.write_text(json.dumps(new_hwm, indent=2))

    print(f"Wrote new HWM  : ${current_equity:.4f}  →  {HWM_PATH}")
    print("Drawdown is now 0.0% — dashboard will reflect on next refresh.")


if __name__ == "__main__":
    main()
