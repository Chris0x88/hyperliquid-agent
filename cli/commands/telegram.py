"""hl telegram — real-time Telegram bot commands."""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import typer

telegram_app = typer.Typer(no_args_is_help=True)


@telegram_app.command("start")
def telegram_start(
    background: bool = typer.Option(True, "--background/--foreground",
                                     help="Run in background (default) or foreground"),
):
    """Start the real-time Telegram bot.

    Polls every 2s. Commands like /status, /price, /help execute instantly
    as fixed Python code — zero AI credits. Free-text messages are queued
    for Claude's next scheduled check-in.
    """
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    pid_file = Path(project_root) / "data/daemon/telegram_bot.pid"

    # Check if already running
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            typer.echo(f"Telegram bot already running (PID {pid}). Use 'hl telegram stop' first.")
            raise typer.Exit()
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    if background:
        import subprocess
        proc = subprocess.Popen(
            [sys.executable, "-m", "telegram.bot"],
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        typer.echo(f"Telegram bot started in background (PID {proc.pid})")
        typer.echo("Commands: /status /price /orders /pnl /help")
        typer.echo("Stop: hl telegram stop")
    else:
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        os.chdir(project_root)
        from telegram.bot import run
        typer.echo("Starting Telegram bot in foreground. Ctrl+C to stop.")
        run()


@telegram_app.command("stop")
def telegram_stop():
    """Stop the running Telegram bot."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    pid_file = Path(project_root) / "data/daemon/telegram_bot.pid"

    if not pid_file.exists():
        typer.echo("No Telegram bot running.")
        raise typer.Exit()

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        typer.echo(f"Sent SIGTERM to Telegram bot (PID {pid})")

        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                typer.echo("Telegram bot stopped.")
                return
        typer.echo("Bot did not stop within 5s. May need manual kill.")
    except (ValueError, OSError) as e:
        typer.echo(f"Error: {e}")
        pid_file.unlink(missing_ok=True)


@telegram_app.command("status")
def telegram_status():
    """Check if the Telegram bot is running."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    pid_file = Path(project_root) / "data/daemon/telegram_bot.pid"

    if not pid_file.exists():
        typer.echo("Telegram bot: stopped")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        typer.echo(f"Telegram bot: running (PID {pid})")
    except (OSError, ValueError):
        typer.echo("Telegram bot: stopped (stale PID file)")
        pid_file.unlink(missing_ok=True)
