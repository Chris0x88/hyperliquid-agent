"""UI-agnostic rendering interface — Telegram today, web app tomorrow.

Follows the same Protocol pattern as common/venue_adapter.py.
All command logic produces data, renderer handles presentation.

Usage:
    # Telegram (current)
    renderer = TelegramRenderer(token, chat_id)
    renderer.send_text("*Portfolio*\nEquity: `$450`")

    # Web API (future)
    renderer = BufferRenderer()
    cmd_status(renderer, args)
    return jsonify(renderer.messages)

    # Tests
    renderer = BufferRenderer()
    cmd_status(renderer, args)
    assert "Equity" in renderer.messages[0]["text"]
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

log = logging.getLogger("renderer")


class Renderer(ABC):
    """Abstract rendering interface for command output.

    Concrete implementations: TelegramRenderer (production), BufferRenderer (tests/web).
    Commands that accept a Renderer work on any platform without changes.
    """

    @abstractmethod
    def send_text(self, text: str, markdown: bool = True) -> bool:
        """Send a text message. Returns success."""
        ...

    @abstractmethod
    def send_buttons(self, text: str, buttons: List[dict]) -> bool:
        """Send text with inline action buttons (one per row)."""
        ...

    @abstractmethod
    def send_grid(self, text: str, rows: List[List[dict]]) -> dict:
        """Send text with button grid (rows of buttons). Returns response data."""
        ...

    @abstractmethod
    def send_image(self, image_bytes: bytes, caption: str = "") -> bool:
        """Send an image with optional caption."""
        ...

    @abstractmethod
    def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Acknowledge a callback/button press."""
        ...

    @abstractmethod
    def edit_grid(self, message_id: int, text: str, rows: List[List[dict]]) -> bool:
        """Edit an existing message in-place (for menu navigation)."""
        ...


class TelegramRenderer(Renderer):
    """Concrete Telegram implementation wrapping existing tg_send functions."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send_text(self, text: str, markdown: bool = True) -> bool:
        from cli.telegram_bot import tg_send
        return tg_send(self.token, self.chat_id, text)

    def send_buttons(self, text: str, buttons: list) -> bool:
        from cli.telegram_bot import tg_send_buttons
        return tg_send_buttons(self.token, self.chat_id, text, buttons)

    def send_grid(self, text: str, rows: list) -> dict:
        from cli.telegram_bot import tg_send_grid
        return tg_send_grid(self.token, self.chat_id, text, rows)

    def send_image(self, image_bytes: bytes, caption: str = "") -> bool:
        # Future: implement via sendPhoto API
        log.warning("TelegramRenderer.send_image not yet implemented")
        return False

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        from cli.telegram_bot import tg_answer_callback
        tg_answer_callback(self.token, callback_id, text)

    def edit_grid(self, message_id: int, text: str, rows: list) -> bool:
        from cli.telegram_bot import tg_edit_grid
        return tg_edit_grid(self.token, self.chat_id, message_id, text, rows)


class BufferRenderer(Renderer):
    """Captures output for testing or web API serialization.

    Usage:
        buf = BufferRenderer()
        cmd_status(buf, "")
        assert len(buf.messages) == 1
        assert "Equity" in buf.messages[0]["text"]
    """

    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.callbacks_answered: List[dict] = []

    def send_text(self, text: str, markdown: bool = True) -> bool:
        self.messages.append({"type": "text", "text": text, "markdown": markdown})
        return True

    def send_buttons(self, text: str, buttons: list) -> bool:
        self.messages.append({"type": "buttons", "text": text, "buttons": buttons})
        return True

    def send_grid(self, text: str, rows: list) -> dict:
        msg = {"type": "grid", "text": text, "rows": rows}
        self.messages.append(msg)
        return {"ok": True, "result": {"message_id": len(self.messages)}}

    def send_image(self, image_bytes: bytes, caption: str = "") -> bool:
        self.messages.append({"type": "image", "caption": caption, "size": len(image_bytes)})
        return True

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.callbacks_answered.append({"id": callback_id, "text": text})

    def edit_grid(self, message_id: int, text: str, rows: list) -> bool:
        self.messages.append({"type": "edit_grid", "message_id": message_id, "text": text, "rows": rows})
        return True
