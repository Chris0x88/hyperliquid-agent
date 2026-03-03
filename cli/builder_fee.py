"""Builder fee configuration and construction.

Hyperliquid builder fees: collected natively per-order via BuilderInfo.
Fee field 'f' is in tenths of basis points (e.g., f=10 = 1 bps = 0.01%).
Users must approve the builder fee via approve_builder_fee() before orders work.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class BuilderFeeConfig:
    """Builder fee settings. Loaded from env vars or YAML config."""

    builder_address: str = ""
    fee_rate_tenths_bps: int = 0  # 10 = 1 bps = 0.01%

    @property
    def enabled(self) -> bool:
        return bool(self.builder_address) and self.fee_rate_tenths_bps > 0

    @property
    def fee_bps(self) -> float:
        """Fee in basis points (human-readable)."""
        return self.fee_rate_tenths_bps / 10.0

    @property
    def max_fee_rate_str(self) -> str:
        """Max fee rate string for approve_builder_fee (e.g., '0.01%' for 1 bps)."""
        pct = self.fee_rate_tenths_bps / 1000.0  # tenths of bps -> percent
        return f"{pct}%"

    def to_builder_info(self) -> Optional[Dict[str, Any]]:
        """Return BuilderInfo dict for SDK, or None if disabled."""
        if not self.enabled:
            return None
        return {"b": self.builder_address, "f": self.fee_rate_tenths_bps}

    @classmethod
    def from_env(cls) -> "BuilderFeeConfig":
        """Load from BUILDER_ADDRESS and BUILDER_FEE_TENTHS_BPS env vars."""
        addr = os.environ.get("BUILDER_ADDRESS", "")
        fee = int(os.environ.get("BUILDER_FEE_TENTHS_BPS", "0"))
        return cls(builder_address=addr, fee_rate_tenths_bps=fee)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BuilderFeeConfig":
        """Load from a config dict (e.g., YAML builder: section)."""
        return cls(
            builder_address=str(d.get("builder_address", "")),
            fee_rate_tenths_bps=int(d.get("fee_rate_tenths_bps", 0)),
        )
