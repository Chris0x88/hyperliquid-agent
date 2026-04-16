from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SmartMoneyConfig:
    """Configuration for smart money tracking."""
    watch_addresses: List[str] = field(default_factory=list)
    min_position_usd: float = 10_000.0     # Only signal on positions above this notional
    conviction_threshold: int = 2           # Number of wallets on same direction for HIGH_CONVICTION
    poll_interval_ticks: int = 5            # Poll every N ticks
    enabled: bool = False                   # Disabled by default

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SmartMoneyConfig":
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in valid})
