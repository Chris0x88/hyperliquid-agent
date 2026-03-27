"""Telemetry — REMOVED.

All telemetry / phone-home code has been stripped. This stub exists so
existing imports don't break. No data is ever sent anywhere.
"""
from __future__ import annotations


class TelemetryClient:
    """No-op telemetry client. All methods are safe to call unconditionally."""

    def __init__(self, **kwargs):
        pass

    @property
    def enabled(self) -> bool:
        return False

    def register(self) -> None:
        pass

    def heartbeat(self, tick_count: int = 0, uptime_s: float = 0, active_positions: int = 0) -> None:
        pass

    def should_heartbeat(self, tick_count: int) -> bool:
        return False


def create_telemetry(wallet_address: str = "", strategy_name: str = "") -> TelemetryClient:
    """Factory — returns a no-op client. Nothing is ever sent."""
    return TelemetryClient()
