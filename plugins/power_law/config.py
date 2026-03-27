#!/usr/bin/env python3
"""
Power Law Bot Configuration — Hyperliquid
==========================================

All settings read from environment variables with POWER_LAW_ prefix.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class PowerLawConfig:
    """
    Configuration for the Power Law rebalancer on Hyperliquid.

    All values read from env with POWER_LAW_ prefix.
    """

    # --- Instrument ---
    instrument: str = field(default_factory=lambda:
        os.getenv("POWER_LAW_INSTRUMENT", "BTC-PERP")
    )

    # --- Leverage ---
    # BTC-PERP on HL supports up to 40x. The model's 0-100% allocation
    # maps linearly to 0-max_leverage.
    max_leverage: float = field(default_factory=lambda: float(
        os.getenv("POWER_LAW_MAX_LEVERAGE", "40.0")
    ))

    # --- Rebalance Strategy ---
    # 15% allocation deviation triggers a rebalance.
    # e.g. model says 60% but current is 80% -> 20% deviation -> rebalance.
    threshold_percent: float = field(default_factory=lambda: float(
        os.getenv("POWER_LAW_THRESHOLD_PERCENT", "15.0")
    ))

    # Extreme price moves (% of BTC price change) also trigger an immediate check.
    extreme_threshold_percent: float = field(default_factory=lambda: float(
        os.getenv("POWER_LAW_EXTREME_THRESHOLD", "5.0")
    ))

    # Check interval in seconds (3600 = hourly)
    interval_seconds: int = field(default_factory=lambda: int(
        os.getenv("POWER_LAW_INTERVAL_SECONDS", "3600")
    ))

    # --- Trading Safety ---
    # Minimum trade in USD notional (avoids dust orders)
    min_trade_usd: float = field(default_factory=lambda: float(
        os.getenv("POWER_LAW_MIN_TRADE_USD", "10.0")
    ))

    # Minimum account value (USD) before rebalancing is attempted.
    min_portfolio_usd: float = field(default_factory=lambda: float(
        os.getenv("POWER_LAW_MIN_PORTFOLIO_USD", "100.0")
    ))

    # --- Model Selection ---
    model: str = field(default_factory=lambda:
        os.getenv("POWER_LAW_MODEL", "HEARTBEAT")
    )

    # --- Simulation Mode ---
    # Default True for safety. Set POWER_LAW_SIMULATE=false for live trading.
    simulate: bool = field(default_factory=lambda:
        os.getenv("POWER_LAW_SIMULATE", "true").lower() != "false"
    )

    # --- Network ---
    # Inherits from HL_TESTNET env var if not explicitly set.
    testnet: bool = field(default_factory=lambda:
        os.getenv("HL_TESTNET", "true").lower() != "false"
    )


# Keep old name as alias so any lingering imports don't break
RobotConfig = PowerLawConfig


def get_power_law_config() -> PowerLawConfig:
    """Factory: create config from environment."""
    return PowerLawConfig()


# Legacy alias
def get_robot_config() -> PowerLawConfig:
    return get_power_law_config()
