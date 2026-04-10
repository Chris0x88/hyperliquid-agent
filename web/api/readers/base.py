"""Abstract reader interfaces — swap implementations for NautilusTrader/DB later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class TimeSeriesReader(ABC):
    """Candles, equity curves, price history."""

    @abstractmethod
    def query(self, market: str, start: datetime, end: datetime) -> list[dict]:
        ...


class EventReader(ABC):
    """Catalysts, journal entries, alerts (currently JSONL files)."""

    @abstractmethod
    def read_latest(self, limit: int = 50) -> list[dict]:
        ...

    @abstractmethod
    def read_range(self, start: datetime, end: datetime) -> list[dict]:
        ...


class StateReader(ABC):
    """Single-document state (daemon state, thesis, config)."""

    @abstractmethod
    def read(self, key: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def write(self, key: str, data: dict[str, Any]) -> None:
        ...


class ConfigReader(ABC):
    """Configuration file management."""

    @abstractmethod
    def list_configs(self) -> list[dict]:
        ...

    @abstractmethod
    def read_config(self, filename: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def write_config(self, filename: str, data: dict[str, Any]) -> None:
        ...
