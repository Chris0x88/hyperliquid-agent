"""hl daemon — monitoring and trading daemon commands."""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import typer

log = logging.getLogger("daemon.commands")

daemon_app = typer.Typer(no_args_is_help=True)


def _setup_logging(data_dir: str, log_json: bool = False):
    """Configure daemon logging with file rotation."""
    from logging.handlers import RotatingFileHandler

    log_dir = Path(data_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "daemon.log"

    handler = RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=3)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if log_json:
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Also log to stderr
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    root.addHandler(console)


def _build_adapter(mock: bool, mainnet: bool):
    """Build the HL adapter (or None for mock mode)."""
    if mock:
        return None

    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from parent.hl_proxy import HLProxy
    from cli.hl_adapter import DirectHLProxy

    testnet = not mainnet
    try:
        hl = HLProxy(testnet=testnet)
    except Exception as e:
        typer.echo(f"Error: Could not connect to HL: {e}", err=True)
        raise typer.Exit(1)

    proxy = DirectHLProxy(hl=hl)
    return proxy


@daemon_app.command("start")
def daemon_start(
    tier: str = typer.Option("watch", "--tier", "-t", help="Tier: watch, rebalance, opportunistic"),
    tick: float = typer.Option(60.0, "--tick", help="Seconds between ticks"),
    mock: bool = typer.Option(False, "--mock", help="Simulated mode — no network calls"),
    mainnet: bool = typer.Option(False, "--mainnet", help="Use mainnet (default: testnet)"),
    max_ticks: int = typer.Option(0, "--max-ticks", help="Stop after N ticks (0 = unlimited)"),
    data_dir: str = typer.Option("data/daemon", "--data-dir"),
    log_json: bool = typer.Option(False, "--log-json", help="Structured JSON logging"),
    resume: bool = typer.Option(True, "--resume/--fresh", help="Resume from saved state or start fresh"),
):
    """Start the daemon monitoring/trading loop."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    _setup_logging(data_dir, log_json)

    from cli.daemon.config import DaemonConfig
    from cli.daemon.clock import Clock
    from cli.daemon.roster import Roster
    from cli.daemon.state import StateStore
    from cli.daemon.tiers import VALID_TIERS

    if tier not in VALID_TIERS:
        typer.echo(f"Invalid tier '{tier}'. Valid: {VALID_TIERS}", err=True)
        raise typer.Exit(1)

    store = StateStore(data_dir)

    # Single-instance enforcement (pacman pattern) — kill any existing daemon
    old_pid = store.read_pid()
    if old_pid and old_pid != os.getpid():
        try:
            os.kill(old_pid, 0)  # Check if alive
            log.info("Killing previous daemon instance (PID %d)", old_pid)
            os.kill(old_pid, signal.SIGTERM)
            import time as _time
            _time.sleep(1.0)
            try:
                os.kill(old_pid, signal.SIGKILL)  # Force if still alive
            except OSError:
                pass
        except OSError:
            pass  # Already dead
        store.remove_pid()

    config = DaemonConfig(
        tier=tier,
        tick_interval=tick,
        mock=mock,
        mainnet=mainnet,
        data_dir=data_dir,
        max_ticks=max_ticks,
        log_json=log_json,
    )

    # Load or create roster
    roster = Roster(path=f"{data_dir}/roster.json")
    if resume:
        roster.load()
    roster.ensure_default()
    roster.instantiate_all()

    # Build adapter
    adapter = _build_adapter(mock, mainnet)

    # Build clock and register iterators
    clock = Clock(config=config, roster=roster, store=store, adapter=adapter)

    from cli.daemon.iterators.apex_advisor import ApexAdvisorIterator
    from cli.daemon.iterators.brent_rollover_monitor import BrentRolloverMonitorIterator
    from cli.daemon.iterators.connector import ConnectorIterator
    from cli.daemon.iterators.liquidation_monitor import LiquidationMonitorIterator
    from cli.daemon.iterators.liquidity import LiquidityIterator
    from cli.daemon.iterators.protection_audit import ProtectionAuditIterator
    from cli.daemon.iterators.risk import RiskIterator
    from cli.daemon.iterators.guard import GuardIterator
    from cli.daemon.iterators.rebalancer import RebalancerIterator
    from cli.daemon.iterators.radar import RadarIterator
    from cli.daemon.iterators.news_ingest import NewsIngestIterator
    from cli.daemon.iterators.supply_ledger import SupplyLedgerIterator
    from cli.daemon.iterators.pulse import PulseIterator
    from cli.daemon.iterators.profit_lock import ProfitLockIterator
    from cli.daemon.iterators.journal import JournalIterator
    from cli.daemon.iterators.telegram import TelegramIterator
    from cli.daemon.iterators.account_collector import AccountCollectorIterator
    from cli.daemon.iterators.thesis_engine import ThesisEngineIterator
    from cli.daemon.iterators.execution_engine import ExecutionEngineIterator
    from cli.daemon.iterators.exchange_protection import ExchangeProtectionIterator
    from cli.daemon.iterators.autoresearch import AutoresearchIterator
    from cli.daemon.iterators.market_structure_iter import MarketStructureIterator
    try:
        from cli.daemon.iterators.funding_tracker import FundingTrackerIterator
        _has_funding = True
    except ImportError:
        _has_funding = False
    try:
        from cli.daemon.iterators.catalyst_deleverage import CatalystDeleverageIterator
        _has_catalyst = True
    except ImportError:
        _has_catalyst = False

    clock.register(AccountCollectorIterator(adapter=adapter))
    clock.register(ConnectorIterator(adapter=adapter))
    clock.register(LiquidationMonitorIterator())
    clock.register(ProtectionAuditIterator())
    clock.register(BrentRolloverMonitorIterator())
    clock.register(MarketStructureIterator())
    clock.register(ThesisEngineIterator())
    clock.register(ExecutionEngineIterator(adapter=adapter))
    clock.register(ExchangeProtectionIterator(adapter=adapter))
    clock.register(LiquidityIterator())
    clock.register(RiskIterator(mainnet=mainnet))
    clock.register(GuardIterator())
    clock.register(RebalancerIterator())
    clock.register(RadarIterator())
    clock.register(NewsIngestIterator())   # sub-system 1: RSS → catalysts
    clock.register(SupplyLedgerIterator())  # sub-system 2: supply disruption ledger
    clock.register(PulseIterator())
    clock.register(ProfitLockIterator(data_dir=data_dir))
    if _has_funding:
        clock.register(FundingTrackerIterator(data_dir=data_dir))
    if _has_catalyst:
        clock.register(CatalystDeleverageIterator(data_dir=data_dir))
    clock.register(ApexAdvisorIterator())
    clock.register(AutoresearchIterator())

    # Memory consolidation — compresses old events into summaries hourly
    try:
        from cli.daemon.iterators.memory_consolidation import MemoryConsolidationIterator
        clock.register(MemoryConsolidationIterator())
    except ImportError:
        pass

    clock.register(JournalIterator(data_dir=data_dir))
    clock.register(TelegramIterator(data_dir=data_dir))

    mode = "mock" if mock else ("mainnet" if mainnet else "testnet")
    typer.echo(f"Starting daemon — tier={tier}, tick={tick}s, mode={mode}")
    typer.echo(f"Strategies: {', '.join(roster.slots.keys())}")
    typer.echo("Press Ctrl+C to stop.\n")

    clock.run()


@daemon_app.command("stop")
def daemon_stop(data_dir: str = typer.Option("data/daemon", "--data-dir")):
    """Stop the running daemon."""
    from cli.daemon.state import StateStore

    store = StateStore(data_dir)
    pid = store.read_pid()

    if pid is None or not store.is_running():
        typer.echo("No daemon running.")
        raise typer.Exit()

    typer.echo(f"Sending SIGTERM to daemon (PID {pid})...")
    os.kill(pid, signal.SIGTERM)

    # Wait up to 30s
    for _ in range(30):
        if not store.is_running():
            typer.echo("Daemon stopped.")
            return
        time.sleep(1)

    typer.echo("Daemon did not stop within 30s. You may need to kill it manually.", err=True)


@daemon_app.command("status")
def daemon_status(data_dir: str = typer.Option("data/daemon", "--data-dir")):
    """Show daemon status, positions, and active strategies."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.daemon.state import StateStore
    from cli.daemon.roster import Roster

    store = StateStore(data_dir)
    state = store.load_state()

    running = store.is_running()
    pid = store.read_pid()

    typer.echo(f"{'Running' if running else 'Stopped'}" + (f" (PID {pid})" if running else ""))
    typer.echo(f"Tier: {state.tier}")
    typer.echo(f"Ticks: {state.tick_count}  |  Trades: {state.total_trades}")
    typer.echo(f"Daily PnL: ${state.daily_pnl:+.2f}  |  Total PnL: ${state.total_pnl:+.2f}")

    roster = Roster(path=f"{data_dir}/roster.json")
    roster.load()

    if roster.slots:
        typer.echo(f"\n{'Strategy':<20} {'Instrument':<12} {'Tick':<8} {'Status':<10}")
        typer.echo("-" * 52)
        for s in roster.slots.values():
            status = "paused" if s.paused else "active"
            typer.echo(f"{s.name:<20} {s.instrument:<12} {s.tick_interval:<8} {status:<10}")
    else:
        typer.echo("\nNo strategies in roster.")


@daemon_app.command("once")
def daemon_once(
    tier: str = typer.Option("", "--tier", "-t", help="Override tier (default: use persisted)"),
    mock: bool = typer.Option(False, "--mock"),
    mainnet: bool = typer.Option(False, "--mainnet"),
    data_dir: str = typer.Option("data/daemon", "--data-dir"),
):
    """Run a single daemon tick and exit."""
    effective_tier = tier if tier else None
    # Reuse start with max_ticks=1
    daemon_start(
        tier=effective_tier or "watch",
        tick=0,
        mock=mock,
        mainnet=mainnet,
        max_ticks=1,
        data_dir=data_dir,
        log_json=False,
        resume=True,
    )


@daemon_app.command("tier")
def daemon_tier(
    new_tier: Optional[str] = typer.Argument(None, help="New tier (omit to show current)"),
    data_dir: str = typer.Option("data/daemon", "--data-dir"),
):
    """Show or change the daemon tier."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.daemon.state import StateStore
    from cli.daemon.tiers import VALID_TIERS

    store = StateStore(data_dir)

    if new_tier is None:
        state = store.load_state()
        typer.echo(f"Current tier: {state.tier}")
        return

    if new_tier not in VALID_TIERS:
        typer.echo(f"Invalid tier '{new_tier}'. Valid: {VALID_TIERS}", err=True)
        raise typer.Exit(1)

    if store.is_running():
        store.write_control({"action": "set_tier", "tier": new_tier})
        typer.echo(f"Sent tier change to running daemon: {new_tier}")
    else:
        state = store.load_state()
        state.tier = new_tier
        store.save_state(state)
        typer.echo(f"Tier set to: {new_tier} (will apply on next start)")


@daemon_app.command("strategies")
def daemon_strategies(data_dir: str = typer.Option("data/daemon", "--data-dir")):
    """List active strategies in the daemon roster."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.daemon.roster import Roster

    roster = Roster(path=f"{data_dir}/roster.json")
    roster.load()

    if not roster.slots:
        typer.echo("No strategies in roster. Use 'hl daemon add <name>' to add one.")
        return

    typer.echo(f"{'Strategy':<20} {'Instrument':<12} {'Tick (s)':<10} {'Status':<10}")
    typer.echo("-" * 54)
    for s in roster.slots.values():
        status = "paused" if s.paused else "active"
        typer.echo(f"{s.name:<20} {s.instrument:<12} {s.tick_interval:<10} {status:<10}")


@daemon_app.command("add")
def daemon_add(
    name: str = typer.Argument(..., help="Strategy name from registry"),
    instrument: str = typer.Option("BTC-PERP", "-i", "--instrument"),
    tick_interval: int = typer.Option(3600, "-t", "--tick-interval", help="Seconds between strategy ticks"),
    params: Optional[str] = typer.Option(None, "--params", help="JSON params override"),
    data_dir: str = typer.Option("data/daemon", "--data-dir"),
):
    """Add a strategy to the daemon roster."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.daemon.roster import Roster
    from cli.daemon.state import StateStore

    parsed_params = json.loads(params) if params else None

    roster = Roster(path=f"{data_dir}/roster.json")
    roster.load()

    try:
        roster.add(name, instrument=instrument, tick_interval=tick_interval, params=parsed_params)
        roster.save()
        typer.echo(f"Added {name} on {instrument} (tick={tick_interval}s)")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    # If daemon is running, notify via control file
    store = StateStore(data_dir)
    if store.is_running():
        store.write_control({
            "action": "add_strategy",
            "name": name,
            "instrument": instrument,
            "tick_interval": tick_interval,
            "params": parsed_params,
        })
        typer.echo("Notified running daemon.")


@daemon_app.command("remove")
def daemon_remove(
    name: str = typer.Argument(..., help="Strategy name to remove"),
    data_dir: str = typer.Option("data/daemon", "--data-dir"),
):
    """Remove a strategy from the daemon roster."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.daemon.roster import Roster
    from cli.daemon.state import StateStore

    roster = Roster(path=f"{data_dir}/roster.json")
    roster.load()

    try:
        roster.remove(name)
        roster.save()
        typer.echo(f"Removed {name}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    store = StateStore(data_dir)
    if store.is_running():
        store.write_control({"action": "remove_strategy", "name": name})


@daemon_app.command("pause")
def daemon_pause(
    name: str = typer.Argument(..., help="Strategy name to pause"),
    data_dir: str = typer.Option("data/daemon", "--data-dir"),
):
    """Pause a strategy without removing it."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.daemon.roster import Roster
    from cli.daemon.state import StateStore

    roster = Roster(path=f"{data_dir}/roster.json")
    roster.load()

    try:
        roster.pause(name)
        roster.save()
        typer.echo(f"Paused {name}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    store = StateStore(data_dir)
    if store.is_running():
        store.write_control({"action": "pause_strategy", "name": name})


@daemon_app.command("resume")
def daemon_resume(
    name: str = typer.Argument(..., help="Strategy name to resume"),
    data_dir: str = typer.Option("data/daemon", "--data-dir"),
):
    """Resume a paused strategy."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.daemon.roster import Roster
    from cli.daemon.state import StateStore

    roster = Roster(path=f"{data_dir}/roster.json")
    roster.load()

    try:
        roster.resume(name)
        roster.save()
        typer.echo(f"Resumed {name}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    store = StateStore(data_dir)
    if store.is_running():
        store.write_control({"action": "resume_strategy", "name": name})
