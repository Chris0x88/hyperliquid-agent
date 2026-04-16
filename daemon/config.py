"""Daemon configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DaemonConfig:
    """Configuration for the daemon loop."""
    tier: str = "watch"                # watch | rebalance | opportunistic
    tick_interval: float = 60.0        # seconds between clock ticks
    mock: bool = False
    mainnet: bool = False
    data_dir: str = "data/daemon"
    max_ticks: int = 0                 # 0 = unlimited
    log_json: bool = False

    # Opportunistic tier limits
    opp_capital_pct: float = 5.0       # max % of account per opportunity
    opp_max_leverage: float = 3.0
    opp_max_size_usd: float = 5000.0

    # Circuit breaker
    max_consecutive_failures: int = 5
