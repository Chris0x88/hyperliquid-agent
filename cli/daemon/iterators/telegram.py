"""TelegramIterator — sends alerts and trade notifications to Telegram."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.telegram")

# Rate limit: max 1 message per 2 seconds to avoid Telegram API limits
MIN_MSG_INTERVAL_S = 2.0


class TelegramIterator:
    """Sends daemon alerts and trade summaries to Telegram.

    Reads bot token and chat_id from environment or config file.
    Env vars: HL_TELEGRAM_BOT_TOKEN, HL_TELEGRAM_CHAT_ID
    Config:  data/daemon/telegram.json
    """
    name = "telegram"

    def __init__(self, data_dir: str = "data/daemon"):
        self._config_path = Path(data_dir) / "telegram.json"
        self._bot_token: Optional[str] = None
        self._chat_id: Optional[str] = None
        self._last_send: float = 0.0
        self._enabled = False
        self._msg_queue: list[str] = []
        # Track state changes to avoid duplicate alerts
        self._last_gate: Optional[str] = None
        self._last_tier: Optional[str] = None

    def on_start(self, ctx: TickContext) -> None:
        self._bot_token = os.environ.get("HL_TELEGRAM_BOT_TOKEN")
        self._chat_id = os.environ.get("HL_TELEGRAM_CHAT_ID")

        # Fallback to config file
        if not self._bot_token and self._config_path.exists():
            try:
                cfg = json.loads(self._config_path.read_text())
                self._bot_token = cfg.get("bot_token")
                self._chat_id = cfg.get("chat_id")
            except (json.JSONDecodeError, OSError):
                pass

        if self._bot_token and self._chat_id:
            self._enabled = True
            self._send("Daemon started\n"
                       f"Tier: {ctx.active_strategies and 'rebalance' or 'watch'}\n"
                       f"Strategies: {len(ctx.active_strategies)}")
            log.info("TelegramIterator enabled")
        else:
            log.info("TelegramIterator disabled — no bot_token/chat_id configured")

    def on_stop(self) -> None:
        if self._enabled:
            self._send("Daemon stopped")

    def tick(self, ctx: TickContext) -> None:
        if not self._enabled:
            return

        # Forward critical and warning alerts
        for alert in ctx.alerts:
            if alert.severity in ("critical", "warning"):
                icon = "\u26a0\ufe0f" if alert.severity == "warning" else "\u274c"
                self._queue(f"{icon} {alert.source}: {alert.message}")

        # Notify on risk gate changes
        gate_val = ctx.risk_gate.value
        if self._last_gate is not None and gate_val != self._last_gate:
            icons = {"OPEN": "\u2705", "COOLDOWN": "\u26a0\ufe0f", "CLOSED": "\ud83d\uded1"}
            self._queue(f"{icons.get(gate_val, '')} Risk gate: {self._last_gate} -> {gate_val}")
        self._last_gate = gate_val

        # Notify on order execution
        for intent in ctx.order_queue:
            if intent.action == "noop":
                continue
            icons = {"buy": "\ud83d\udfe2", "sell": "\ud83d\udd34", "close": "\ud83d\udfe1"}
            self._queue(
                f"{icons.get(intent.action, '\u26aa')} {intent.action.upper()} "
                f"{intent.size} {intent.instrument}"
                f"{f' @ {intent.price}' if intent.price else ' (market)'}"
                f" [{intent.strategy_name}]"
            )

        # P&L summary every 10 ticks
        if ctx.tick_number > 0 and ctx.tick_number % 10 == 0:
            equity = ctx.balances.get("USDC", ctx.balances.get("USD", 0))
            n_pos = len(ctx.positions)
            lines = [
                f"\ud83d\udcca Tick #{ctx.tick_number} Summary",
                f"Equity: ${float(equity):,.2f}" if equity else "Equity: --",
                f"Positions: {n_pos}",
                f"Gate: {gate_val}",
            ]
            # Add position details
            for pos in ctx.positions[:5]:
                price = ctx.prices.get(pos.instrument, 0)
                pnl = pos.total_pnl(price) if price else 0
                lines.append(f"  {pos.instrument}: {float(pos.net_qty):+.4f} (PnL: ${float(pnl):+.2f})")
            self._queue("\n".join(lines))

        # Flush queue
        self._flush()

    def _queue(self, msg: str) -> None:
        self._msg_queue.append(msg)

    def _flush(self) -> None:
        if not self._msg_queue:
            return
        # Batch messages to reduce API calls
        combined = "\n---\n".join(self._msg_queue)
        self._send(combined)
        self._msg_queue.clear()

    def _send(self, text: str) -> None:
        """Send message via Telegram Bot API."""
        now = time.time()
        if now - self._last_send < MIN_MSG_INTERVAL_S:
            time.sleep(MIN_MSG_INTERVAL_S - (now - self._last_send))

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            self._last_send = time.time()
        except (urllib.error.URLError, OSError) as e:
            log.warning("Telegram send failed: %s", e)
