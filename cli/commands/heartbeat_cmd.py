"""hl heartbeat — position auditor and risk monitor commands."""
from __future__ import annotations

import json
import time
from pathlib import Path

import typer

heartbeat_app = typer.Typer(no_args_is_help=True)


@heartbeat_app.command("run")
def heartbeat_run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute only — no trades or Telegram"),
) -> None:
    """Run one heartbeat cycle."""
    from common.heartbeat_config import load_config
    from common.heartbeat import run_heartbeat

    config = load_config()
    result = run_heartbeat(config, dry_run=dry_run)

    esc = result.get("escalation", "?")
    n_actions = len(result.get("actions", []))
    n_errors = len(result.get("errors", []))
    duration = result.get("duration_ms", 0)
    mode = "DRY-RUN" if dry_run else "LIVE"

    typer.echo(f"[{mode}] Heartbeat complete — escalation={esc}  actions={n_actions}  errors={n_errors}  {duration}ms")

    if result.get("errors"):
        for err in result["errors"]:
            typer.echo(f"  ERROR: {err}", err=True)

    if result.get("actions"):
        for act in result["actions"]:
            typer.echo(f"  ACTION: {act.get('action')} {act.get('market', '')} — {act.get('reason', '')}")


@heartbeat_app.command("status")
def heartbeat_status() -> None:
    """Show current working state JSON."""
    from common.heartbeat_state import load_working_state, DEFAULT_STATE_PATH

    state = load_working_state()
    from dataclasses import asdict
    typer.echo(json.dumps(asdict(state), indent=2))


@heartbeat_app.command("health")
def heartbeat_health() -> None:
    """Show health: GREEN / YELLOW / RED based on state freshness and escalation."""
    from common.heartbeat_state import load_working_state

    state = load_working_state()
    now_ms = int(time.time() * 1000)
    age_ms = now_ms - state.last_updated_ms if state.last_updated_ms else None

    # Determine colour
    esc = state.escalation_level
    failures = state.heartbeat_consecutive_failures

    if esc in ("L2", "L3") or failures >= 3:
        colour = "RED"
    elif esc == "L1" or failures >= 1 or (age_ms is not None and age_ms > 10 * 60 * 1000):
        colour = "YELLOW"
    else:
        colour = "GREEN"

    typer.echo(f"Health: {colour}")
    typer.echo(f"  Escalation: {esc}")
    typer.echo(f"  Consecutive failures: {failures}")

    if age_ms is not None:
        age_min = age_ms / 60_000
        typer.echo(f"  Last update: {age_min:.1f} min ago")
    else:
        typer.echo("  Last update: never")
