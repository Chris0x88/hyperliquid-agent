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
        self._sent_alerts: dict = {}  # message_hash -> timestamp (dedup)

    def on_start(self, ctx: TickContext) -> None:
        self._bot_token = os.environ.get("HL_TELEGRAM_BOT_TOKEN")
        self._chat_id = os.environ.get("HL_TELEGRAM_CHAT_ID")

        # Try macOS Keychain (encrypted at rest)
        if not self._bot_token:
            self._bot_token = self._keychain_read("bot_token")
        if not self._chat_id:
            self._chat_id = self._keychain_read("chat_id")

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
                       f"Tier: {ctx.daemon_tier}\n"
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

        # Forward alerts with severity-aware dedup cooldowns (Freqtrade-inspired)
        # critical: max once per 15min (persistent conditions need re-alerting)
        # warning: max once per 1hr
        # info: max once per 4hr
        import hashlib
        now = time.time()
        severity_cooldowns = {"critical": 900, "warning": 3600, "info": 14400}

        for alert in ctx.alerts:
            cooldown = severity_cooldowns.get(alert.severity, 3600)
            if cooldown == 0:
                continue  # unknown severity, skip

            dedup_key = f"{alert.source}:{alert.message[:60]}"
            msg_hash = hashlib.md5(dedup_key.encode()).hexdigest()[:8]
            last_sent = self._sent_alerts.get(msg_hash, 0)
            if now - last_sent < cooldown:
                continue
            self._sent_alerts[msg_hash] = now

            # Escalation: if same alert has been firing for >10min, mark ACTION REQUIRED
            escalated = (last_sent > 0 and now - last_sent >= cooldown)
            if alert.severity == "critical":
                icon = "🚨" if escalated else "❌"
                prefix = "*ACTION REQUIRED* — " if escalated else ""
            elif alert.severity == "warning":
                icon = "⚠️"
                prefix = ""
            else:
                icon = "ℹ️"
                prefix = ""

            # BUG-FIX 2026-04-08 (alert-format): emit a labelled section
            # block instead of ``source: message`` so the operator can read
            # alerts at a glance. Markdown formatting (parse_mode set in
            # _send below) makes the source bold and the message body
            # clean. Multi-line alerts (e.g. journal trade close) keep
            # their newline structure.
            self._queue(f"{icon} {prefix}*{alert.source}*\n{alert.message}")

        # Prune old dedup entries (keep last 24h)
        self._sent_alerts = {k: v for k, v in self._sent_alerts.items() if now - v < 86400}

        # Notify on risk gate changes
        gate_val = ctx.risk_gate.value
        if self._last_gate is not None and gate_val != self._last_gate:
            icons = {"OPEN": "\u2705", "COOLDOWN": "\u26a0\ufe0f", "CLOSED": "\ud83d\uded1"}
            self._queue(f"{icons.get(gate_val, '')} *Risk gate*: {self._last_gate} → {gate_val}")
        self._last_gate = gate_val

        # Notify on order execution
        for intent in ctx.order_queue:
            if intent.action == "noop":
                continue
            icons = {"buy": "\ud83d\udfe2", "sell": "\ud83d\udd34", "close": "\ud83d\udfe1"}
            price_str = f" @ `${float(intent.price):,.2f}`" if intent.price else " (market)"
            self._queue(
                f"{icons.get(intent.action, '\u26aa')} *{intent.action.upper()}* "
                f"`{intent.size}` `{intent.instrument}`"
                f"{price_str}"
                f" — _{intent.strategy_name}_"
            )

        # Periodic status every 30 ticks (less noisy).
        #
        # BUG-FIX 2026-04-08 (equity-reporting): use ctx.total_equity
        # (native + xyz + spot) so this number matches what /status shows.
        # Falls back to ctx.balances["USDC"] (native-only) if connector
        # has not yet populated total_equity (tick 0 / mock mode).
        if ctx.tick_number > 0 and ctx.tick_number % 30 == 0:
            tier = (ctx.daemon_tier or "watch").upper()
            if ctx.total_equity > 0:
                equity_val = ctx.total_equity
            else:
                equity_val = float(ctx.balances.get("USDC", ctx.balances.get("USD", 0)) or 0)
            n_pos = len(ctx.positions)
            equity_str = f"`${equity_val:,.2f}`" if equity_val else "`--`"
            lines = [
                f"💓 *Daemon alive* — _{tier}_",
                f"  Equity: {equity_str}",
                f"  Tracking `{n_pos}` position{'s' if n_pos != 1 else ''}",
            ]
            self._queue("\n".join(lines))

        # Flush queue
        self._flush()

    @staticmethod
    def _keychain_read(key_name: str) -> Optional[str]:
        """Read a secret from macOS Keychain (hl-agent-telegram service)."""
        import subprocess
        try:
            result = subprocess.run(
                ["security", "find-generic-password",
                 "-s", "hl-agent-telegram", "-a", key_name, "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

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
        """Send message via Telegram Bot API.

        BUG-FIX 2026-04-08 (alert-format): switched parse_mode from "HTML"
        to "Markdown" to match telegram_bot.py (the working /status path).
        Iterators emit alerts with markdown formatting (backticks for code,
        asterisks for bold) — under HTML those rendered as literal
        characters in the user's chat. With Markdown enabled the alerts
        match the look of /status, /position, /pnl etc.
        """
        now = time.time()
        if now - self._last_send < MIN_MSG_INTERVAL_S:
            time.sleep(MIN_MSG_INTERVAL_S - (now - self._last_send))

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"

        def _post(parse_mode: str | None) -> bool:
            payload_dict = {
                "chat_id": self._chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
            if parse_mode:
                payload_dict["parse_mode"] = parse_mode
            payload = json.dumps(payload_dict).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read()
                # Telegram returns 200 even on parse errors but with ok=False
                try:
                    return json.loads(body).get("ok", False)
                except Exception:
                    return True
            except (urllib.error.URLError, OSError) as e:
                log.warning("Telegram send failed: %s", e)
                return False

        # Try Markdown first; fall back to plain text if Telegram rejects it
        # (e.g. unbalanced markdown characters in an alert message body).
        if _post("Markdown"):
            self._last_send = time.time()
            return
        log.warning("Markdown parse failed — retrying as plain text")
        if _post(None):
            self._last_send = time.time()
