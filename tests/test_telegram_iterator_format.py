"""Regression tests for TelegramIterator alert formatting + equity reporting.

BUG-FIX 2026-04-08:
- (alert-format): TelegramIterator was sending with ``parse_mode="HTML"``
  but the alerts emitted by other iterators contained markdown formatting
  (backticks for code, asterisks for bold). Under HTML those rendered as
  literal characters. The fix flips parse_mode to "Markdown" to match
  telegram_bot.py and reformats the periodic status block + per-alert
  output as labelled markdown sections.

- (equity-reporting): the periodic 'Daemon alive' alert read
  ``ctx.balances.get("USDC", ...)`` which is native-perps-only and did
  not match the equity number ``/status`` reports (native + xyz + spot).
  The fix reads ``ctx.total_equity`` first, falling back to the legacy
  field only when total_equity has not yet been populated.

These tests lock in both behaviours by stubbing the network send and
inspecting the queued/dispatched payload.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List

from cli.daemon.context import Alert, TickContext
from cli.daemon.iterators.telegram import TelegramIterator


def _make_iterator() -> TelegramIterator:
    """Build an enabled iterator with the network call stubbed."""
    it = TelegramIterator()
    it._enabled = True
    it._bot_token = "test-token"
    it._chat_id = "12345"
    return it


class TestPeriodicEquityAlert:

    def test_periodic_uses_total_equity_when_populated(self):
        """ctx.total_equity > 0 wins over ctx.balances['USDC']."""
        it = _make_iterator()
        sent: List[str] = []
        it._send = lambda text: sent.append(text)  # type: ignore[assignment]

        ctx = TickContext(tick_number=30)
        ctx.balances["USDC"] = Decimal("500.0")     # native-only
        ctx.total_equity = 645.50                   # native + xyz + spot

        it.tick(ctx)

        assert sent, "expected at least one Telegram payload"
        msg = sent[0]
        assert "$645.50" in msg, (
            f"periodic alert must report ctx.total_equity, got: {msg!r}"
        )
        # The legacy native-only number must NOT be the headline
        assert "$500.00" not in msg

    def test_periodic_falls_back_to_balances_when_total_equity_zero(self):
        """ctx.total_equity == 0 → use ctx.balances['USDC'] (tick 0 / mock mode)."""
        it = _make_iterator()
        sent: List[str] = []
        it._send = lambda text: sent.append(text)  # type: ignore[assignment]

        ctx = TickContext(tick_number=30)
        ctx.balances["USDC"] = Decimal("123.45")
        ctx.total_equity = 0.0

        it.tick(ctx)

        assert sent
        assert "$123.45" in sent[0]

    def test_periodic_format_uses_markdown_blocks(self):
        """Header is bold, equity is in code formatting (markdown rendering)."""
        it = _make_iterator()
        sent: List[str] = []
        it._send = lambda text: sent.append(text)  # type: ignore[assignment]

        ctx = TickContext(tick_number=30)
        ctx.daemon_tier = "opportunistic"
        ctx.total_equity = 1234.56

        it.tick(ctx)

        msg = sent[0]
        # The "Daemon alive" header is bold-marked
        assert "*Daemon alive*" in msg
        assert "_OPPORTUNISTIC_" in msg
        # The equity figure is in backtick-quoted code style
        assert "`$1,234.56`" in msg

    def test_periodic_skipped_off_cadence(self):
        """tick_number not divisible by 30 → no periodic alert sent."""
        it = _make_iterator()
        sent: List[str] = []
        it._send = lambda text: sent.append(text)  # type: ignore[assignment]

        ctx = TickContext(tick_number=15)
        ctx.total_equity = 999.0

        it.tick(ctx)

        assert sent == [], "no payload should fire off the 30-tick cadence"


class TestAlertSectionFormat:

    def test_alert_emits_labelled_section_block(self):
        """Alerts now produce ``icon *source*\\nmessage`` not ``icon source: message``."""
        it = _make_iterator()
        sent: List[str] = []
        it._send = lambda text: sent.append(text)  # type: ignore[assignment]

        ctx = TickContext(tick_number=1)
        ctx.alerts.append(Alert(
            severity="critical",
            source="liquidation_monitor",
            message="🔴 *xyz:CL* SHORT — Mark `$94.93` → Liq `$97.84` (Cushion `3.1%`)",
        ))

        it.tick(ctx)

        assert sent
        payload = sent[0]
        # Source rendered as human-readable bold header
        assert "*Liquidation*" in payload
        # The message body is preserved (with its own markdown)
        assert "$94.93" in payload
        # Critical severity prepends the right icon
        assert payload.startswith("❌") or payload.startswith("🚨")

    def test_alert_dedup_within_cooldown(self):
        """Same source+message within cooldown is only sent once."""
        it = _make_iterator()
        sent: List[str] = []
        it._send = lambda text: sent.append(text)  # type: ignore[assignment]

        ctx1 = TickContext(tick_number=1)
        ctx1.alerts.append(Alert(
            severity="warning",
            source="risk",
            message="Drawdown above 15%",
        ))
        it.tick(ctx1)

        ctx2 = TickContext(tick_number=2)
        ctx2.alerts.append(Alert(
            severity="warning",
            source="risk",
            message="Drawdown above 15%",
        ))
        it.tick(ctx2)

        # Only the first alert should have produced a payload
        assert len(sent) == 1


class TestParseModeDefault:
    """The constructor doesn't set parse_mode — it lives in _send. We verify
    by spying on the urlopen call. Markdown is the default; HTML is no longer
    in the codepath.
    """

    def test_send_function_uses_markdown_parse_mode(self, monkeypatch):
        captured: dict = {}

        class _FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return b'{"ok":true}'

        def _fake_urlopen(req, timeout=10):
            captured["data"] = req.data.decode("utf-8")
            return _FakeResp()

        import urllib.request as _ur
        monkeypatch.setattr(_ur, "urlopen", _fake_urlopen)

        it = _make_iterator()
        it._send("hello *world*")

        assert "data" in captured
        import json as _json
        body = _json.loads(captured["data"])
        assert body.get("parse_mode") == "Markdown", (
            f"parse_mode should default to Markdown, got {body.get('parse_mode')!r}"
        )
