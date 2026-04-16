#!/usr/bin/env python3
"""Heartbeat runner — launchd entry point with PID enforcement."""
from __future__ import annotations

import atexit
import logging
import os
import sys
from pathlib import Path

# ── Project root on sys.path ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Paths ────────────────────────────────────────────────────────────────────
PID_DIR = PROJECT_ROOT / "data" / "memory" / "pids"
PID_FILE = PID_DIR / "heartbeat.pid"
LOG_DIR = PROJECT_ROOT / "data" / "memory" / "logs"
LOG_FILE = LOG_DIR / "heartbeat.log"
TELEGRAM_ENV = Path.home() / ".claude" / "channels" / "telegram" / ".env"

MAX_LOG_BYTES = 1_000_000  # 1 MB


# ── PID enforcement ─────────────────────────────────────────────────────────

def _is_pid_alive(pid: int) -> bool:
    """Check if a process with *pid* is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _acquire_pid() -> bool:
    """Write our PID file. Returns False if another instance is alive."""
    PID_DIR.mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        try:
            existing_pid = int(PID_FILE.read_text().strip())
            if _is_pid_alive(existing_pid):
                return False  # another instance running — exit silently
            # Stale PID — remove it
            PID_FILE.unlink(missing_ok=True)
        except (ValueError, OSError):
            PID_FILE.unlink(missing_ok=True)

    PID_FILE.write_text(str(os.getpid()))
    return True


def _release_pid() -> None:
    """Remove our PID file."""
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ── Log rotation ─────────────────────────────────────────────────────────────

def _rotate_log() -> None:
    """If log file > 1 MB, rename to .log.old."""
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
        old = LOG_FILE.with_suffix(".log.old")
        try:
            LOG_FILE.rename(old)
        except OSError:
            pass


# ── Telegram token loading ───────────────────────────────────────────────────

def _load_telegram_token() -> None:
    """Load TELEGRAM_BOT_TOKEN from channel .env if not already in environment."""
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return
    if not TELEGRAM_ENV.is_file():
        return
    try:
        for line in TELEGRAM_ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                value = line.split("=", 1)[1].strip()
                # Strip surrounding quotes
                if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                os.environ["TELEGRAM_BOT_TOKEN"] = value
                return
    except OSError:
        pass


# ── Logging setup ────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    """Configure logging to file + stderr."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _rotate_log()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    file_handler.setFormatter(fmt)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if not _acquire_pid():
        return  # another instance alive — exit silently

    atexit.register(_release_pid)

    try:
        _load_telegram_token()
        _setup_logging()

        log = logging.getLogger("heartbeat.runner")
        log.info("Heartbeat runner starting (PID %d)", os.getpid())

        from trading.heartbeat_config import load_config
        from trading.heartbeat import run_heartbeat
        from common.trajectory import TrajectoryLogger
        from common.telemetry import TelemetryRecorder

        config = load_config()

        # Phase 1 harness: trajectory + telemetry
        traj = TrajectoryLogger("heartbeat")
        tel = TelemetryRecorder("heartbeat")

        try:
            tel.start_cycle()
            traj.log("heartbeat_start", details={"pid": os.getpid()})

            result = run_heartbeat(config)

            traj.log("heartbeat_complete", details={
                "escalation": result.get("escalation", "?"),
                "actions": len(result.get("actions", [])),
                "errors": len(result.get("errors", [])),
            })
            log.info("Heartbeat complete: escalation=%s actions=%d errors=%d",
                     result.get("escalation", "?"),
                     len(result.get("actions", [])),
                     len(result.get("errors", [])))
        except Exception as inner_exc:
            traj.log("heartbeat_error", details={"error": str(inner_exc)}, status="error")
            raise
        finally:
            tel.end_cycle()
            traj.close()

    except Exception as exc:
        # Try to send Telegram crash alert
        try:
            from telegram.memory import send_telegram
            send_telegram(f"HEARTBEAT CRASH: {exc}")
        except Exception:
            pass
        raise
    finally:
        _release_pid()


if __name__ == "__main__":
    main()
