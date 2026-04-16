#!/usr/bin/env python3
"""
AI Direct Execution Script
==========================
Allows the OpenClaw agent to directly execute trades via terminal.
Usage:
  python scripts/execute_action.py --coin BRENTOIL --action close
  python scripts/execute_action.py --coin BRENTOIL --action reduce --pct 50
  python scripts/execute_action.py --coin BTC-PERP --action set-sl --price 89000
  python scripts/execute_action.py --coin BTC-PERP --action buy --size 0.05
"""
import argparse
import logging
import sys
import os

from cli.config import TradingConfig
from exchange.hl_proxy import HLProxy
from cli.hl_adapter import DirectHLProxy
from cli.strategy_registry import YEX_MARKETS

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("execute_action")

def get_position(proxy: DirectHLProxy, coin: str):
    """Fetch position for a given coin. Handles both main perps and YEX (xyz)."""
    yex = YEX_MARKETS.get(coin) or YEX_MARKETS.get(f"{coin}-PERP")
    if yex or coin.startswith("xyz:"):
        target_coin = yex["hl_coin"] if yex else coin.split(":")[-1]
        state = proxy.get_xyz_state()
    else:
        target_coin = coin.replace("-PERP", "")
        state = proxy.get_account_state()
        
    positions = state.get("assetPositions", [])
    for p in positions:
        pos = p.get("position", {})
        if pos.get("coin") == target_coin:
            return float(pos.get("szi", 0.0))
    return 0.0

def main():
    parser = argparse.ArgumentParser(description="AI Execution Wrapper")
    parser.add_argument("--coin", required=True, help="Coin symbol (e.g. BRENTOIL, BTC-PERP)")
    parser.add_argument("--action", required=True, choices=["buy", "sell", "reduce", "close", "set-sl", "set-tp"], help="Action to perform")
    parser.add_argument("--pct", type=float, default=100.0, help="Percentage of position to target (for reduce/close)")
    parser.add_argument("--size", type=float, help="Absolute size (for buy/sell)")
    parser.add_argument("--price", type=float, help="Trigger price (for set-sl / set-tp)")
    parser.add_argument("--simulate", action="store_true", help="Dry run only")
    args = parser.parse_args()

    instrument = args.coin
    if not instrument.endswith("-PERP") and not instrument.endswith("-USDYP"):
        if instrument in ["BRENTOIL", "VXX", "US3M", "SILVER", "GOLD"] or instrument.startswith("xyz:"):
            instrument = instrument.replace("xyz:", "")
            if not instrument.endswith("-USDYP"):
                instrument = f"{instrument}-USDYP"
        else:
            instrument = f"{instrument}-PERP"

    # Load Proxy
    cfg = TradingConfig()
    key = cfg.get_private_key()
    testnet = os.environ.get("HL_TESTNET", "true").lower() != "false"
    hl = HLProxy(private_key=key, testnet=testnet)
    proxy = DirectHLProxy(hl)

    if args.simulate:
        log.info(f"[SIMULATE] Loaded proxy for {instrument}. Testnet={testnet}")

    current_pos = get_position(proxy, instrument)
    is_long = current_pos > 0

    log.info(f"Target: {instrument} | Current Position: {current_pos}")

    if args.action in ["close", "reduce"]:
        if current_pos == 0:
            log.error(f"Cannot {args.action} {instrument}: position is 0.")
            sys.exit(1)
        
        pct = args.pct / 100.0
        size_to_close = abs(current_pos) * pct
        side = "sell" if is_long else "buy"
        
        log.info(f"Action: {args.action.upper()} {args.pct}% -> {side.upper()} {size_to_close} lots")
        if not args.simulate:
            fill = proxy.place_order(instrument, side, size_to_close, 0.0, tif="Ioc")
            if fill:
                log.info(f"SUCCESS! Filled {fill.quantity} @ {fill.price}")
            else:
                log.error("FAILED to place order.")
                
    elif args.action in ["buy", "sell"]:
        if not args.size:
            log.error("ERROR: --size required for buy/sell")
            sys.exit(1)
            
        log.info(f"Action: {args.action.upper()} {args.size} lots")
        if not args.simulate:
            fill = proxy.place_order(instrument, args.action, args.size, 0.0, tif="Ioc")
            if fill:
                log.info(f"SUCCESS! Filled {fill.quantity} @ {fill.price}")
            else:
                log.error("FAILED to place order.")

    elif args.action == "set-sl":
        if not args.price:
            log.error("ERROR: --price required for set-sl")
            sys.exit(1)
            
        # Stop loss opposite to position
        if current_pos == 0:
            log.warning("Warning: Setting SL on 0 position! Side may be ambiguous.")
            side = "sell" # Defaulting
        else:
            side = "sell" if is_long else "buy"
            
        log.info(f"Action: SL -> {side.upper()} {abs(current_pos)} lots @ {args.price}")
        if not args.simulate:
            oid = proxy.place_trigger_order(instrument, side, abs(current_pos), args.price)
            if oid:
                log.info(f"SUCCESS! Placed SL order ID: {oid}")
            else:
                log.error("FAILED to place SL.")

    elif args.action == "set-tp":
        if not args.price:
            log.error("ERROR: --price required for set-tp")
            sys.exit(1)
            
        if current_pos == 0:
            log.warning("Warning: Setting TP on 0 position! Side may be ambiguous.")
            side = "sell" 
        else:
            side = "sell" if is_long else "buy"
            
        log.info(f"Action: TP -> {side.upper()} {abs(current_pos)} lots @ {args.price}")
        if not args.simulate:
            oid = proxy.place_tp_trigger_order(instrument, side, abs(current_pos), args.price)
            if oid:
                log.info(f"SUCCESS! Placed TP order ID: {oid}")
            else:
                log.error("FAILED to place TP.")

if __name__ == "__main__":
    main()
