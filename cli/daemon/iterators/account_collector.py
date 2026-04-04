"""AccountCollectorIterator — timestamped account snapshots with HWM + drawdown tracking.

Every 5 minutes: fetch both native HL + xyz dex positions, compute high water mark and
current drawdown, write a JSON snapshot to data/snapshots/. Injects snapshot_ref,
account_drawdown_pct, and high_water_mark into TickContext.

The scheduled task loads the latest snapshot via AccountCollectorIterator.get_latest()
so every AI evaluation is grounded in current state, not stale notes.
"""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.account_collector")

SNAPSHOT_INTERVAL_S = 300       # 5 minutes
HWM_FILE = "data/snapshots/hwm.json"
SNAPSHOT_DIR = "data/snapshots"
ZERO = Decimal("0")


class AccountCollectorIterator:
    """Collects timestamped account snapshots and tracks high water mark + drawdown."""

    name = "account_collector"

    def __init__(self, adapter: Any = None, snapshot_dir: str = SNAPSHOT_DIR):
        self._adapter = adapter
        self._snapshot_dir = snapshot_dir
        self._last_snapshot: float = 0.0
        self._high_water_mark: float = 0.0

    def on_start(self, ctx: TickContext) -> None:
        Path(self._snapshot_dir).mkdir(parents=True, exist_ok=True)
        # Restore high water mark from disk
        hwm_path = os.path.join(self._snapshot_dir, "hwm.json")
        if os.path.exists(hwm_path):
            try:
                with open(hwm_path) as f:
                    data = json.load(f)
                self._high_water_mark = float(data.get("hwm", 0.0))
                log.info("Restored HWM: $%.2f", self._high_water_mark)
            except Exception as e:
                log.warning("Failed to restore HWM: %s", e)
        log.info("AccountCollectorIterator started  snapshot_dir=%s  hwm=$%.2f",
                 self._snapshot_dir, self._high_water_mark)

    def on_stop(self) -> None:
        self._save_hwm()

    def tick(self, ctx: TickContext) -> None:
        now = time.monotonic()
        if now - self._last_snapshot < SNAPSHOT_INTERVAL_S:
            # Still inject whatever we have even between snapshots
            ctx.high_water_mark = self._high_water_mark
            return

        self._last_snapshot = now
        self._collect_and_inject(ctx)

    def _collect_and_inject(self, ctx: TickContext) -> None:
        """Fetch account state, write snapshot, update ctx."""
        if self._adapter is None:
            log.debug("AccountCollector: mock mode, skipping")
            return

        snapshot = self._build_snapshot(ctx)
        if not snapshot:
            return

        # Write to disk
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        filename = f"{ts_str}.json"
        path = os.path.join(self._snapshot_dir, filename)
        try:
            with open(path, "w") as f:
                json.dump(snapshot, f, indent=2)
            log.info("Account snapshot: %s  equity=$%.2f  drawdown=%.1f%%",
                     filename,
                     snapshot.get("account_value", 0),
                     snapshot.get("drawdown_pct", 0))
        except Exception as e:
            log.error("Failed to write snapshot: %s", e)
            return

        # Update context
        equity = float(snapshot.get("account_value", 0))

        # Auto-reset HWM when flat (no open positions).
        # Drawdown only matters while in a trade — if you closed everything,
        # withdrew funds, or took profits off-exchange, the new equity IS your baseline.
        has_positions = bool(
            snapshot.get("positions_native")
            or snapshot.get("positions_xyz")
        )
        # Filter to non-zero positions (HL returns closed positions with szi=0)
        if has_positions:
            all_pos = list(snapshot.get("positions_native", []))
            all_pos.extend(
                p.get("position", p) if isinstance(p, dict) and "position" in p else p
                for p in snapshot.get("positions_xyz", [])
            )
            has_positions = any(
                float(p.get("szi", 0)) != 0 for p in all_pos if isinstance(p, dict)
            )

        if not has_positions and equity > 0:
            # Flat — reset HWM to current equity
            if abs(self._high_water_mark - equity) > 0.01:
                log.info("Flat (no positions) — resetting HWM from $%.2f to $%.2f",
                         self._high_water_mark, equity)
                self._high_water_mark = equity
                self._save_hwm()
        elif equity > self._high_water_mark:
            self._high_water_mark = equity
            self._save_hwm()

        drawdown_pct = 0.0
        if self._high_water_mark > 0 and equity < self._high_water_mark:
            drawdown_pct = (self._high_water_mark - equity) / self._high_water_mark * 100

        ctx.snapshot_ref = filename
        ctx.high_water_mark = self._high_water_mark
        ctx.account_drawdown_pct = drawdown_pct

        # Alert on significant drawdowns (only when in a position)
        if has_positions and drawdown_pct >= 25.0:
            ctx.alerts.append(Alert(
                severity="critical",
                source=self.name,
                message=f"DRAWDOWN: `${equity:,.0f}` is {drawdown_pct:.0f}% below peak `${self._high_water_mark:,.0f}` — halting new entries",
                data={"drawdown_pct": drawdown_pct, "hwm": self._high_water_mark, "equity": equity},
            ))
        elif has_positions and drawdown_pct >= 15.0:
            ctx.alerts.append(Alert(
                severity="warning",
                source=self.name,
                message=f"Drawdown: `${equity:,.0f}` is {drawdown_pct:.0f}% below peak — reduce risk",
                data={"drawdown_pct": drawdown_pct, "equity": equity},
            ))

        # Cleanup old snapshots (keep 7 days full, 1/day for 30 days)
        self._expire_old_snapshots()

    def _build_snapshot(self, ctx: TickContext) -> Optional[Dict]:
        """Build a comprehensive account snapshot including xyz dex positions."""
        snapshot: Dict[str, Any] = {
            "timestamp": int(time.time() * 1000),
            "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

        # Native HL account state
        try:
            state = self._adapter.get_account_state()
            snapshot["account_value"] = state.get("account_value", 0)
            snapshot["total_margin"] = state.get("total_margin", 0)
            snapshot["withdrawable"] = state.get("withdrawable", 0)
            snapshot["spot_usdc"] = state.get("spot_usdc", 0)
            snapshot["positions_native"] = state.get("positions", [])
        except Exception as e:
            log.warning("Failed to fetch native account state: %s", e)
            snapshot["account_value"] = 0

        # xyz dex state (BRENTOIL and other commodity perps)
        try:
            if hasattr(self._adapter, "get_xyz_state"):
                xyz = self._adapter.get_xyz_state()
                if xyz:
                    xyz_positions = xyz.get("assetPositions", [])
                    snapshot["positions_xyz"] = xyz_positions
                    snapshot["xyz_margin_summary"] = xyz.get("marginSummary", {})
                    snapshot["xyz_open_orders"] = xyz.get("open_orders", [])

                    # Merge xyz account value into total if available
                    xyz_equity = float(xyz.get("marginSummary", {}).get("accountValue", 0))
                    if xyz_equity > 0:
                        snapshot["xyz_account_value"] = xyz_equity
                        # Combined equity (main perps + xyz + spot)
                        native_equity = float(snapshot.get("account_value", 0))
                        spot_usdc = float(snapshot.get("spot_usdc", 0))
                        snapshot["total_equity"] = native_equity + xyz_equity + spot_usdc
                        snapshot["account_value"] = snapshot["total_equity"]
        except Exception as e:
            log.warning("Failed to fetch xyz state: %s", e)

        # Compute total equity: perps (native + xyz) + spot USDC
        # account_value may only have perps — spot USDC sits separately
        perp_equity = float(snapshot.get("account_value", 0))
        spot_usdc = float(snapshot.get("spot_usdc", 0))
        total_equity = perp_equity + spot_usdc
        snapshot["total_equity"] = total_equity
        # Use total_equity for HWM/drawdown (not just perps)
        snapshot["account_value"] = total_equity

        # Add drawdown info
        hwm = self._high_water_mark
        equity = total_equity
        if equity > hwm:
            hwm = equity
        snapshot["high_water_mark"] = hwm
        snapshot["drawdown_pct"] = (hwm - equity) / hwm * 100 if hwm > 0 else 0.0

        return snapshot

    def _save_hwm(self) -> None:
        """Persist high water mark to disk."""
        try:
            Path(self._snapshot_dir).mkdir(parents=True, exist_ok=True)
            hwm_path = os.path.join(self._snapshot_dir, "hwm.json")
            with open(hwm_path, "w") as f:
                json.dump({"hwm": self._high_water_mark, "ts": int(time.time())}, f)
        except Exception as e:
            log.warning("Failed to save HWM: %s", e)

    def _expire_old_snapshots(self) -> None:
        """Delete snapshots older than 30 days; keep only 1/day after 7 days."""
        try:
            p = Path(self._snapshot_dir)
            now = time.time()
            files = sorted(p.glob("????????_??????.json"))

            for fp in files:
                age_days = (now - fp.stat().st_mtime) / 86400
                if age_days > 30:
                    fp.unlink()
                    continue
                if age_days > 7:
                    # Keep only one snapshot per day: the most recent one
                    # (handled by the naming convention — lexicographic last for each date prefix)
                    day_prefix = fp.name[:8]
                    same_day = sorted(p.glob(f"{day_prefix}_??????.json"))
                    if len(same_day) > 1 and fp != same_day[-1]:
                        fp.unlink()
        except Exception as e:
            log.debug("Snapshot expiry error: %s", e)

    @staticmethod
    def get_latest(snapshot_dir: str = SNAPSHOT_DIR) -> Optional[Dict]:
        """Load the most recent account snapshot from disk.

        Used by the AI scheduled task to ground its evaluation in current state.
        Returns None if no snapshots exist.
        """
        p = Path(snapshot_dir)
        if not p.exists():
            return None
        files = sorted(p.glob("????????_??????.json"))
        if not files:
            return None
        try:
            with open(files[-1]) as f:
                data = json.load(f)
            data["_filename"] = files[-1].name
            return data
        except Exception as e:
            log.error("Failed to load latest snapshot: %s", e)
            return None
