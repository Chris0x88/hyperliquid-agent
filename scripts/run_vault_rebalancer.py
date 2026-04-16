#!/usr/bin/env python3
"""
Vault BTC Power Law Rebalancer — background daemon
====================================================

Runs forever, checking the vault every hour and rebalancing BTC-PERP
according to the Heartbeat Model.  Start/stop via launchctl or Telegram.

Usage:
    python scripts/run_vault_rebalancer.py

Environment (set in launchd plist or shell):
    HL_VAULT_ADDRESS   Vault address to trade on behalf of (required)
    HL_TESTNET         Set to 'false' for mainnet (default: false here)
    POWER_LAW_MAX_LEVERAGE    1  (no leverage — allocation IS the exposure)
    POWER_LAW_THRESHOLD_PERCENT  10
    POWER_LAW_SIMULATE  false
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

# ── repo root on sys.path ──────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── defaults (env vars override) ──────────────────────────────────────────
os.environ.setdefault("POWER_LAW_SIMULATE", "false")
os.environ.setdefault("HL_TESTNET", "false")
os.environ.setdefault("POWER_LAW_MAX_LEVERAGE", "1")
os.environ.setdefault("POWER_LAW_THRESHOLD_PERCENT", "10")

TICK_SECONDS = int(os.environ.get("POWER_LAW_INTERVAL_SECONDS", "3600"))
PID_FILE = REPO_ROOT / "data" / "vault_rebalancer.pid"

# ── logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vault_rebalancer")

# ── graceful shutdown ─────────────────────────────────────────────────────
_running = True

def _shutdown(sig, frame):
    global _running
    log.info("Signal %s received — shutting down", sig)
    _running = False

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


def _build_bot():
    """Build the PowerLawBot wired to the vault."""
    from common.credentials import resolve_private_key
    from exchange.hl_proxy import HLProxy
    from cli.hl_adapter import DirectHLProxy
    from plugins.power_law.bot import PowerLawBot
    from plugins.power_law.config import PowerLawConfig

    vault_address = os.environ.get("HL_VAULT_ADDRESS", "").strip()
    if not vault_address:
        raise RuntimeError("HL_VAULT_ADDRESS is not set — cannot start vault rebalancer")

    key = resolve_private_key(venue="hl")
    hl = HLProxy(private_key=key, testnet=False, vault_address=vault_address)
    proxy = DirectHLProxy(hl)
    cfg = PowerLawConfig(
        max_leverage=float(os.environ.get("POWER_LAW_MAX_LEVERAGE", "1")),
        threshold_percent=float(os.environ.get("POWER_LAW_THRESHOLD_PERCENT", "10")),
        simulate=False,
    )
    return PowerLawBot(proxy=proxy, config=cfg)


def _kill_previous():
    """Ensure only one instance runs. Kill any stale process from a previous PID file."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if old_pid != os.getpid():
                os.kill(old_pid, signal.SIGTERM)
                time.sleep(1)
                log.info("Killed previous instance (PID %d)", old_pid)
        except (OSError, ValueError):
            pass
        PID_FILE.unlink(missing_ok=True)


def main():
    _kill_previous()
    PID_FILE.write_text(str(os.getpid()))
    log.info("Vault rebalancer started (pid=%s, tick=%ss)", os.getpid(), TICK_SECONDS)

    try:
        bot = _build_bot()
    except Exception as e:
        log.error("Failed to initialise bot: %s", e)
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)

    # Run immediately on start, then every TICK_SECONDS
    while _running:
        try:
            result = bot.check_and_rebalance()
            if result.get("traded"):
                log.info("Rebalanced — %s $%.2f @ $%.2f",
                         result.get("direction"), result.get("amount_usd", 0),
                         result.get("fill_price", 0))
            else:
                log.info("No rebalance needed — %s", result.get("reason", "within threshold"))
        except Exception as e:
            log.error("check_and_rebalance error: %s", e, exc_info=True)

        # Sleep in 10s increments so SIGTERM is handled promptly
        for _ in range(TICK_SECONDS // 10):
            if not _running:
                break
            time.sleep(10)

    PID_FILE.unlink(missing_ok=True)
    log.info("Vault rebalancer stopped cleanly")


if __name__ == "__main__":
    main()
