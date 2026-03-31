#!/usr/bin/env python3
"""
Power Law Adapter — Bridges Heartbeat Model to Hyperliquid
===========================================================

Replaces the original SpaceLord/Hedera adapter with a DirectHLProxy-backed
implementation. All Hedera/HTS/SaucerSwap references removed.

Integration points:
  - get_btc_price()      → BTC-PERP mark price from HL snapshot
  - get_portfolio_state() → HL account value + current BTC-PERP position
  - execute_rebalance()  → place_order on BTC-PERP via DirectHLProxy

Portfolio model on HL perps
----------------------------
Unlike spot (WBTC + USDC), on HL you hold:
  - USDC collateral (account_value from marginSummary)
  - A BTC-PERP long position (size in BTC, potentially leveraged)

We map "BTC allocation %" to leverage:
  btc_percent  = (position_notional / account_value) / max_leverage × 100
  target_pct   = heartbeat model's allocation_pct (0–100 %)
  deviation    = btc_percent - target_pct  → triggers rebalance if > threshold
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("power_law.adapter")

INSTRUMENT = "BTC-PERP"


@dataclass
class PortfolioState:
    """Current portfolio snapshot for the rebalancer."""
    btc_position: float       # BTC-PERP position size (positive = long)
    usdc_balance: float       # Free collateral / account value in USDC
    btc_price_usd: float      # Current BTC mark price in USD
    total_value_usd: float    # Total account value in USD
    btc_percent: float        # Current effective BTC allocation % (leverage-adjusted)
    max_leverage: float       # Max leverage configured (e.g. 40)


class HLPowerLawAdapter:
    """
    Adapts DirectHLProxy for the Power Law rebalancer.

    The bot calls adapter methods instead of talking to HL directly.
    This is the ONLY integration point between the Power Law bot and HL.
    """

    def __init__(self, proxy, max_leverage: float = 40.0):
        """
        Args:
            proxy: DirectHLProxy or DirectMockProxy instance (already connected).
            max_leverage: Max leverage for BTC-PERP (default 40 on HL mainnet).
        """
        self._proxy = proxy
        self.max_leverage = max_leverage
        self._cached_price: float = 0.0

    # ------------------------------------------------------------------
    # Price
    # ------------------------------------------------------------------

    def get_btc_price(self) -> float:
        """Get current BTC mark price from HL order book mid."""
        try:
            snap = self._proxy.get_snapshot(INSTRUMENT)
            price = snap.mid_price
            if price and price > 0:
                self._cached_price = price
                return price
        except Exception as e:
            log.warning("[PowerLaw] BTC price fetch failed: %s", e)

        if self._cached_price > 0:
            log.warning("[PowerLaw] Using cached BTC price: %.2f", self._cached_price)
            return self._cached_price

        log.error("[PowerLaw] Cannot get BTC price — no data available")
        return 0.0

    # ------------------------------------------------------------------
    # Portfolio state
    # ------------------------------------------------------------------

    def get_portfolio_state(self) -> Optional[PortfolioState]:
        """
        Build portfolio state from HL account + BTC-PERP position.

        btc_percent is leverage-normalised so it maps directly to the
        heartbeat model's 0-100 allocation range:
          btc_percent = (long_notional / account_value) / max_leverage * 100
        """
        try:
            state = self._proxy.get_account_state()
            if not state:
                log.error("[PowerLaw] Empty account state from HL")
                return None

            account_value = float(state.get("account_value", 0))
            if account_value <= 0:
                # Unified account: spot USDC serves as perp margin
                account_value = float(state.get("spot_usdc", 0))
            if account_value <= 0:
                log.error("[PowerLaw] Account value is zero")
                return None

            btc_price = self.get_btc_price()
            if btc_price <= 0:
                log.error("[PowerLaw] BTC price is zero, cannot compute allocation")
                return None

            # Parse current BTC-PERP position from assetPositions
            btc_position = self._get_btc_position(state)

            long_notional = max(0.0, btc_position) * btc_price  # only count longs
            btc_percent = (long_notional / account_value) / self.max_leverage * 100

            # Free collateral: withdrawable margin (spot USDC for unified accounts)
            usdc_free = float(state.get("withdrawable", 0))
            if usdc_free <= 0:
                usdc_free = float(state.get("spot_usdc", account_value))

            return PortfolioState(
                btc_position=btc_position,
                usdc_balance=usdc_free,
                btc_price_usd=btc_price,
                total_value_usd=account_value,
                btc_percent=round(btc_percent, 2),
                max_leverage=self.max_leverage,
            )

        except Exception as e:
            log.error("[PowerLaw] Portfolio state error: %s", e, exc_info=True)
            return None

    def _get_btc_position(self, account_state: dict) -> float:
        """Extract current BTC-PERP position size (signed, in BTC)."""
        try:
            positions = account_state.get("positions", [])
            for pos in positions:
                # HL position structure: {"position": {"coin": "BTC", "szi": "0.5", ...}}
                inner = pos.get("position", pos)
                coin = inner.get("coin", "")
                if coin.upper() == "BTC":
                    szi = inner.get("szi", "0")
                    return float(szi)
        except Exception as e:
            log.warning("[PowerLaw] Could not parse BTC position: %s", e)
        return 0.0

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_rebalance(
        self,
        direction: str,
        amount_usd: float,
        btc_price: float,
        simulate: bool = True,
    ) -> dict:
        """
        Execute a rebalance trade on BTC-PERP.

        Args:
            direction:  "buy_btc"  (increase long / reduce short)
                        "sell_btc" (reduce long / go flat)
            amount_usd: Trade size in notional USD.
            btc_price:  Current BTC price used for size calculation.
            simulate:   If True, log only — no order sent.

        Returns:
            dict with success, direction, amount_usd, amount_btc, error.
        """
        if btc_price <= 0:
            return {"success": False, "error": "BTC price is zero"}

        amount_btc = amount_usd / btc_price
        side = "buy" if direction == "buy_btc" else "sell"

        log.info(
            "[PowerLaw] Rebalance: %s $%.2f (%.6f BTC @ $%.2f)",
            direction, amount_usd, amount_btc, btc_price,
        )

        if simulate:
            log.info("[PowerLaw] SIMULATE — no order sent")
            return {
                "success": True,
                "simulated": True,
                "direction": direction,
                "amount_usd": amount_usd,
                "amount_btc": amount_btc,
                "side": side,
            }

        try:
            fill = self._proxy.place_order(
                instrument=INSTRUMENT,
                side=side,
                size=amount_btc,
                price=btc_price,
                tif="Ioc",
            )

            if fill is not None:
                log.info(
                    "[PowerLaw] Filled: %s %.6f BTC @ $%.2f",
                    side, float(fill.quantity), float(fill.price),
                )
                return {
                    "success": True,
                    "simulated": False,
                    "direction": direction,
                    "amount_usd": amount_usd,
                    "amount_btc": float(fill.quantity),
                    "fill_price": float(fill.price),
                    "oid": fill.oid,
                }
            else:
                log.warning("[PowerLaw] Order placed but no fill returned")
                return {
                    "success": False,
                    "error": "No fill — order may be resting or rejected",
                    "direction": direction,
                    "amount_usd": amount_usd,
                }

        except Exception as e:
            log.error("[PowerLaw] Rebalance execution error: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}
