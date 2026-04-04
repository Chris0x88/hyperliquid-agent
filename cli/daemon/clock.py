"""Clock — tick-based daemon loop inspired by Hummingbot's TimeIterator pattern."""
from __future__ import annotations

import logging
import signal
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from cli.daemon.config import DaemonConfig
from cli.daemon.context import Alert, Iterator, OrderIntent, TickContext
from cli.daemon.roster import Roster
from cli.daemon.state import DaemonState, StateStore
from cli.daemon.tiers import iterators_for_tier
from common.middleware import run_with_middleware
from common.telemetry import TelemetryRecorder
from common.trajectory import TrajectoryLogger
from parent.risk_manager import RiskGate

log = logging.getLogger("daemon.clock")


class Clock:
    """Tick-based daemon loop.

    Each tick:
      1. Check control file for runtime commands
      2. Call each registered iterator in order
      3. Execute queued orders
      4. Persist state
    """

    def __init__(
        self,
        config: DaemonConfig,
        roster: Roster,
        store: StateStore,
        adapter: Any = None,  # VenueAdapter — injected
    ):
        self.config = config
        self.roster = roster
        self.store = store
        self.adapter = adapter

        self.state = store.load_state()
        self.state.tier = config.tier

        self._iterators: Dict[str, Iterator] = {}
        self._iterator_order: List[str] = []
        self._running = False
        self._consecutive_failures: Dict[str, int] = {}

        # Phase 1 harness: middleware telemetry + trajectory
        self.telemetry = TelemetryRecorder("daemon")
        self.trajectory: Optional[TrajectoryLogger] = None

        # Passivbot-style health window: sliding window error budget
        from common.telemetry import HealthWindow
        self.health_window = HealthWindow(window_s=900, error_budget=10)

    # ── Iterator management ──────────────────────────────────

    def register(self, iterator: Iterator) -> None:
        self._iterators[iterator.name] = iterator
        if iterator.name not in self._iterator_order:
            self._iterator_order.append(iterator.name)

    def _rebuild_active_set(self) -> List[Iterator]:
        """Return iterators active for the current tier, in order."""
        tier_names = set(iterators_for_tier(self.state.tier))
        return [
            self._iterators[name]
            for name in self._iterator_order
            if name in tier_names and name in self._iterators
        ]

    # ── Main loop ────────────────────────────────────────────

    def run(self) -> None:
        """Block until max_ticks reached or signal received."""
        self._running = True
        self.store.write_pid()
        self.trajectory = TrajectoryLogger("daemon")

        # Signal handling
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)

        # Start iterators
        active = self._rebuild_active_set()
        init_ctx = self._make_context()
        for it in active:
            try:
                it.on_start(init_ctx)
            except Exception as e:
                if it.name == "connector":
                    log.error("ConnectorIterator failed to start: %s — aborting", e)
                    self._shutdown()
                    return
                log.warning("Iterator %s failed to start: %s — skipping", it.name, e)

        log.info("Daemon started — tier=%s, tick=%.0fs, strategies=%d",
                 self.state.tier, self.config.tick_interval, len(self.roster.slots))

        try:
            while self._running:
                self._tick()
                if 0 < self.config.max_ticks <= self.state.tick_count:
                    log.info("Reached max_ticks=%d — stopping", self.config.max_ticks)
                    break
                if self._running:
                    time.sleep(self.config.tick_interval)
        finally:
            self._shutdown()

    def _tick(self) -> None:
        """Execute one full tick cycle."""
        self.state.tick_count += 1
        ctx = self._make_context()

        # Check control file for runtime commands
        self._process_control(ctx)

        # Run iterators with middleware
        self.telemetry.start_cycle()
        active = self._rebuild_active_set()
        for it in active:
            mw = run_with_middleware(
                it.name, it.tick, ctx,
                timeout_s=getattr(self.config, 'iterator_timeout_s', 10),
                telemetry=self.telemetry,
            )

            if mw.status == "ok":
                self._consecutive_failures[it.name] = 0
            else:
                failures = self._consecutive_failures.get(it.name, 0) + 1
                self._consecutive_failures[it.name] = failures
                log.error("[%s] tick failed (%d/%d): %s",
                          it.name, failures, self.config.max_consecutive_failures,
                          mw.error)

                if it.name == "connector":
                    log.warning("Connector failed — skipping rest of tick")
                    if self.trajectory:
                        self.trajectory.log("connector_failed", details={"error": mw.error}, status="error")
                    self.telemetry.end_cycle()
                    return

                # Record error in health window
                self.health_window.record("error")

                if failures >= self.config.max_consecutive_failures:
                    log.warning("[%s] circuit breaker open — %d consecutive failures",
                                it.name, failures)
                    ctx.alerts.append(Alert(
                        severity="critical",
                        source=it.name,
                        message=f"Circuit breaker: {failures} consecutive failures",
                    ))
                    self._maybe_downgrade_tier(ctx)

        # Check health budget — auto-downgrade if too many errors
        if self.health_window.budget_exhausted():
            ctx.alerts.append(Alert(
                severity="critical",
                source="health_budget",
                message=f"Error budget exhausted ({self.health_window.budget_summary()}) — auto-downgrading",
            ))
            self._maybe_downgrade_tier(ctx)

        # Execute queued orders
        self._execute_orders(ctx)

        # Process alerts
        for alert in ctx.alerts:
            log.log(
                logging.WARNING if alert.severity == "critical" else logging.INFO,
                "[alert:%s] %s: %s", alert.severity, alert.source, alert.message,
            )

        # Persist
        self.store.save_state(self.state)
        self.roster.save()

        # Finalize telemetry + trajectory for this tick
        self.telemetry.set_health_window(self.health_window.to_dict())
        self.telemetry.end_cycle()
        if self.trajectory:
            self.trajectory.log("tick_complete", details={
                "tick": self.state.tick_count,
                "tier": self.state.tier,
                "strategies": len(self.roster.slots),
                "orders": len(ctx.order_queue),
            })

        # Tick summary
        n_orders = len(ctx.order_queue)
        log.info("tick=%d tier=%s strategies=%d orders=%d gate=%s",
                 self.state.tick_count, self.state.tier,
                 len(self.roster.slots), n_orders, ctx.risk_gate.value)

    def _make_context(self) -> TickContext:
        return TickContext(
            timestamp=int(time.time() * 1000),
            tick_number=self.state.tick_count,
            active_strategies={
                name: slot for name, slot in self.roster.slots.items()
                if not slot.paused
            },
        )

    # ── Order execution ──────────────────────────────────────

    def _execute_orders(self, ctx: TickContext) -> None:
        """Drain order queue and submit to exchange."""
        if not ctx.order_queue:
            return

        if ctx.risk_gate == RiskGate.CLOSED:
            log.warning("Risk gate CLOSED — dropping %d orders", len(ctx.order_queue))
            ctx.order_queue.clear()
            return

        for intent in ctx.order_queue:
            if intent.action == "noop":
                continue

            # Skip new entries in COOLDOWN
            if ctx.risk_gate == RiskGate.COOLDOWN and not intent.reduce_only:
                log.info("Risk gate COOLDOWN — skipping entry: %s %s",
                         intent.action, intent.instrument)
                continue

            if self.adapter is None:
                log.info("[mock] Would execute: %s %s %s @ %s",
                         intent.action, intent.size, intent.instrument, intent.price)
                self.state.total_trades += 1
                continue

            try:
                self._submit_order(intent)
                self.state.total_trades += 1
                self.health_window.record("order_placed")
            except Exception as e:
                log.error("Order execution failed: %s — %s", intent, e)
                self.health_window.record("error")

        ctx.order_queue.clear()

    def _submit_order(self, intent: OrderIntent) -> None:
        """Submit a single order to the exchange adapter."""
        is_buy = intent.action == "buy"
        price = float(intent.price) if intent.price else 0.0
        size = float(intent.size)

        if intent.action == "close":
            # Close = reduce-only in opposite direction
            self.adapter.cancel_all(intent.instrument)
            # Place market close — implementation depends on adapter
            log.info("Closing position on %s", intent.instrument)
            return

        self.adapter.place_order(
            coin=intent.instrument.replace("-PERP", ""),
            is_buy=is_buy,
            sz=size,
            limit_px=price,
            order_type={"limit": {"tif": intent.order_type}},
            reduce_only=intent.reduce_only,
        )
        log.info("Submitted: %s %.4f %s @ %.2f", intent.action, size, intent.instrument, price)

    # ── Control commands ─────────────────────────────────────

    def _process_control(self, ctx: TickContext) -> None:
        cmd = self.store.read_control()
        if cmd is None:
            return

        action = cmd.get("action")
        log.info("Control command: %s", cmd)

        if action == "shutdown":
            self._running = False
        elif action == "set_tier":
            new_tier = cmd.get("tier", self.state.tier)
            self.state.tier = new_tier
            self.config.tier = new_tier
            log.info("Tier changed to: %s", new_tier)
        elif action == "add_strategy":
            try:
                self.roster.add(
                    cmd["name"],
                    instrument=cmd.get("instrument", "BTC-PERP"),
                    tick_interval=cmd.get("tick_interval", 3600),
                    params=cmd.get("params"),
                )
                self.roster.instantiate_all()
            except Exception as e:
                log.error("Failed to add strategy: %s", e)
        elif action == "remove_strategy":
            try:
                self.roster.remove(cmd["name"])
            except Exception as e:
                log.error("Failed to remove strategy: %s", e)
        elif action == "pause_strategy":
            try:
                self.roster.pause(cmd["name"])
            except Exception as e:
                log.error("Failed to pause strategy: %s", e)
        elif action == "resume_strategy":
            try:
                self.roster.resume(cmd["name"])
            except Exception as e:
                log.error("Failed to resume strategy: %s", e)

    # ── Tier auto-downgrade ──────────────────────────────────

    def _maybe_downgrade_tier(self, ctx: TickContext) -> None:
        if self.state.tier == "opportunistic":
            self.state.tier = "rebalance"
            self.config.tier = "rebalance"
            log.warning("Auto-downgraded to rebalance tier due to errors")
        elif self.state.tier == "rebalance":
            self.state.tier = "watch"
            self.config.tier = "watch"
            log.warning("Auto-downgraded to watch tier due to errors")

    # ── Shutdown ─────────────────────────────────────────────

    def _handle_signal(self, signum, frame):
        log.info("Received signal %d — shutting down after current tick", signum)
        self._running = False

    def _shutdown(self) -> None:
        log.info("Shutting down daemon...")
        for it in self._iterators.values():
            try:
                it.on_stop()
            except Exception as e:
                log.warning("Iterator %s failed to stop: %s", it.name, e)

        self.store.save_state(self.state)
        self.roster.save()
        self.store.remove_pid()
        if self.trajectory:
            self.trajectory.log("daemon_shutdown", details={
                "ticks": self.state.tick_count,
                "trades": self.state.total_trades,
            })
            self.trajectory.close()
        log.info("Daemon stopped. Ticks=%d, Trades=%d", self.state.tick_count, self.state.total_trades)
