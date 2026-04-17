"""Checklist runner — orchestrates evaluators for one market + mode.

Usage:
    from engines.checklist.runner import run_checklist, build_ctx

    ctx = build_ctx()          # loads live data (positions, orders, thesis, etc.)
    result = run_checklist("xyz:SILVER", mode="evening", ctx=ctx)
    print(result)              # dict — JSON-serializable

The runner:
1. Loads per-market YAML config (if exists) from data/checklist/<market_bare>.yaml
2. Selects evaluators for the requested mode ("evening" / "morning")
3. Calls each evaluator, wraps in ChecklistItem
4. Aggregates into ChecklistResult
5. Writes JSON to data/checklist/state/<market>_<mode>_<ts>.json
6. Updates data/checklist/state/latest.json
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from engines.checklist.spec import (
    ChecklistItem,
    ChecklistResult,
    MarketChecklist,
    ITEM_DEFAULTS,
)
from engines.checklist.evaluators import EVALUATOR_REGISTRY
from engines.checklist.sweep_detector import detect_sweep_risk

log = logging.getLogger("checklist.runner")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CHECKLIST_CFG_DIR = DATA_DIR / "checklist"
STATE_DIR = CHECKLIST_CFG_DIR / "state"
THESIS_DIR = DATA_DIR / "thesis"
HEATMAP_ZONES_FILE = DATA_DIR / "heatmap" / "zones.jsonl"
HEATMAP_CASCADES_FILE = DATA_DIR / "heatmap" / "cascades.jsonl"
BOT_PATTERNS_FILE = DATA_DIR / "research" / "bot_patterns.jsonl"
CATALYSTS_FILE = DATA_DIR / "news" / "catalysts.jsonl"

# ── YAML config loader ────────────────────────────────────────


def _load_market_cfg(market: str) -> MarketChecklist:
    """Load per-market YAML config or return defaults."""
    bare = market.replace("xyz:", "").lower()
    cfg_file = CHECKLIST_CFG_DIR / f"{bare}.yaml"
    overrides: Dict[str, Any] = {}
    enabled = True

    if cfg_file.exists():
        try:
            import yaml  # type: ignore
            raw = yaml.safe_load(cfg_file.read_text()) or {}
            enabled = raw.get("enabled", True)
            overrides = raw.get("items", {})
        except Exception as exc:
            log.warning("Failed to load checklist YAML for %s: %s", market, exc)

    return MarketChecklist(market=market, enabled=enabled, item_overrides=overrides)


# ── Data loaders (bounded — read-only, no network) ────────────


def _load_jsonl(path: Path, limit: int = 200) -> list:
    """Read last `limit` lines from a JSONL file, parse as list of dicts."""
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        # Take last `limit` lines
        lines = lines[-limit:]
        result = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return result
    except Exception as exc:
        log.warning("Failed to read %s: %s", path, exc)
        return []


def _load_thesis(market: str) -> Optional[dict]:
    """Load thesis JSON for a market. Tries xyz_ prefix and bare name."""
    bare = market.replace("xyz:", "").lower()
    for candidate in [
        f"xyz_{bare}_state.json",
        f"{bare}_perp_state.json",
        f"{bare}_state.json",
    ]:
        p = THESIS_DIR / candidate
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return None


def _get_funding_rate(coin: str) -> Optional[float]:
    """Fetch current hourly funding rate for coin. Returns None if unavailable."""
    try:
        import requests
        bare = coin.replace("xyz:", "")
        is_xyz = coin.startswith("xyz:")

        payload: dict = {"type": "metaAndAssetCtxs"}
        if is_xyz:
            payload["dex"] = "xyz"
        resp = requests.post("https://api.hyperliquid.xyz/info",
                             json=payload, timeout=5)
        data = resp.json()
        if isinstance(data, list) and len(data) >= 2:
            universe = data[0].get("universe", [])
            ctxs = data[1]
            for i, ctx_item in enumerate(ctxs):
                if i >= len(universe):
                    break
                name = universe[i].get("name", "")
                name_bare = name.replace("xyz:", "")
                if name_bare == bare or name == coin:
                    rate_str = ctx_item.get("funding", "0")
                    return float(rate_str)
    except Exception as exc:
        log.debug("Funding rate fetch failed for %s: %s", coin, exc)
    return None


def _get_market_price(coin: str) -> Optional[float]:
    """Fetch current mid price for coin."""
    try:
        import requests
        resp = requests.post("https://api.hyperliquid.xyz/info",
                             json={"type": "allMids"}, timeout=5)
        mids = resp.json()
        bare = coin.replace("xyz:", "")
        # Try exact match first
        for k, v in mids.items():
            if k == coin or k.replace("xyz:", "") == bare:
                return float(v)
    except Exception:
        pass
    return None


def _get_atr(coin: str) -> Optional[float]:
    """Estimate 14-day ATR from candle cache if available."""
    bare = coin.replace("xyz:", "").upper()
    candle_dir = DATA_DIR / "candles"
    if not candle_dir.exists():
        return None
    try:
        # Look for pre-cached daily candle files
        for pattern in [f"{bare}_1d.json", f"xyz_{bare}_1d.json"]:
            p = candle_dir / pattern
            if p.exists():
                candles = json.loads(p.read_text())
                closes = [float(c[4]) for c in candles[-15:] if len(c) >= 5]
                highs = [float(c[2]) for c in candles[-15:] if len(c) >= 5]
                lows = [float(c[3]) for c in candles[-15:] if len(c) >= 5]
                if len(closes) < 2:
                    return None
                trs = []
                for i in range(1, len(closes)):
                    tr = max(highs[i] - lows[i],
                             abs(highs[i] - closes[i - 1]),
                             abs(lows[i] - closes[i - 1]))
                    trs.append(tr)
                if trs:
                    return sum(trs) / len(trs)
    except Exception:
        pass
    return None


def _is_friday_brisbane() -> bool:
    """Return True if current wall-clock time is Friday in Brisbane (UTC+10)."""
    import datetime
    brisbane_offset = datetime.timezone(datetime.timedelta(hours=10))
    now_brisbane = datetime.datetime.now(tz=brisbane_offset)
    return now_brisbane.weekday() == 4  # 0=Mon, 4=Fri


def build_ctx(
    market: Optional[str] = None,
    positions: Optional[list] = None,
    orders: Optional[list] = None,
    total_equity: Optional[float] = None,
) -> dict:
    """Build context dict for the checklist evaluators.

    Callers can inject positions/orders/equity (e.g. from tests or
    already-fetched account state) to avoid double network calls.
    Pass None to trigger live fetches.
    """
    from common.account_state import fetch_registered_account_state

    # Account state
    if positions is None or orders is None or total_equity is None:
        try:
            bundle = fetch_registered_account_state()
            if positions is None:
                positions = bundle.get("positions", [])
            if total_equity is None:
                total_equity = float(bundle.get("account", {}).get("total_equity", 0))
            if orders is None:
                # Fetch orders from main account address
                from exchange.helpers import _get_all_orders
                main_addr = next(
                    (a["address"] for a in bundle.get("accounts", []) if a.get("role") == "main"),
                    "",
                )
                orders = _get_all_orders(main_addr) if main_addr else []
        except Exception as exc:
            log.warning("Failed to fetch account state: %s", exc)
            positions = positions or []
            orders = orders or []
            total_equity = total_equity or 0.0

    thesis = _load_thesis(market) if market else None
    market_price = _get_market_price(market) if market else None
    atr = _get_atr(market) if market else None
    funding_rate = _get_funding_rate(market) if market else None

    heatmap_zones = _load_jsonl(HEATMAP_ZONES_FILE, limit=500)
    cascades = _load_jsonl(HEATMAP_CASCADES_FILE, limit=200)
    bot_patterns = _load_jsonl(BOT_PATTERNS_FILE, limit=100)
    catalysts = _load_jsonl(CATALYSTS_FILE, limit=50)

    # Pre-compute sweep risk for this market
    sweep_result = None
    if market:
        mini_ctx = {
            "positions": positions,
            "market_price": market_price,
            "atr": atr,
            "funding_rate": funding_rate,
            "heatmap_zones": heatmap_zones,
            "cascades": cascades,
            "bot_patterns": bot_patterns,
        }
        try:
            sweep_result = detect_sweep_risk(market, mini_ctx)
        except Exception as exc:
            log.warning("Sweep detector failed for %s: %s", market, exc)

    return {
        "positions": positions,
        "orders": orders,
        "total_equity": total_equity,
        "thesis": thesis,
        "market_price": market_price,
        "atr": atr,
        "funding_rate": funding_rate,
        "catalysts": catalysts,
        "heatmap_zones": heatmap_zones,
        "cascades": cascades,
        "bot_patterns": bot_patterns,
        "closed_since": [],      # TODO Phase 2.5: diff fill log vs snapshot
        "filled_orders": [],     # TODO Phase 2.5: read fill log since last evening ts
        "sweep_result": sweep_result,
        "is_friday_brisbane": _is_friday_brisbane(),
    }


# ── Main runner ───────────────────────────────────────────────


def run_checklist(market: str, mode: str, ctx: dict) -> dict:
    """Run the checklist for one market in one mode.

    Args:
        market: coin identifier (e.g. "xyz:SILVER", "BTC")
        mode:   "evening" or "morning"
        ctx:    context dict from build_ctx()

    Returns:
        JSON-serialisable dict (ChecklistResult.to_dict())
    """
    if mode not in ("evening", "morning"):
        raise ValueError(f"Invalid mode {mode!r} — must be 'evening' or 'morning'")

    cfg = _load_market_cfg(market)
    ts = int(time.time())

    items: List[ChecklistItem] = []

    for key, defaults in ITEM_DEFAULTS.items():
        item_mode = defaults.get("mode", "both")
        # Filter by mode
        if item_mode not in (mode, "both"):
            continue

        if not cfg.is_item_enabled(key):
            continue

        evaluator = EVALUATOR_REGISTRY.get(key)
        if evaluator is None:
            log.warning("No evaluator registered for key %r — skipping", key)
            continue

        item_cfg = cfg.item_config(key)
        weight = int(item_cfg.get("weight", defaults.get("weight", 5)))
        category = str(item_cfg.get("category", defaults.get("category", "other")))

        try:
            # Pass market-scoped ctx with sweep_result pre-computed
            status, reason, data = evaluator(market, ctx)
        except Exception as exc:
            log.warning("Evaluator %r failed for %s: %s", key, market, exc)
            status, reason, data = "skip", f"Evaluator error: {exc}", None

        items.append(ChecklistItem(
            name=key,
            status=status,
            reason=reason,
            weight=weight,
            mode=item_mode,
            category=category,
            data=data,
        ))

    result = ChecklistResult(market=market, mode=mode, timestamp=ts, items=items)
    result_dict = result.to_dict()

    # Persist
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        bare = market.replace("xyz:", "").lower()
        out_file = STATE_DIR / f"{bare}_{mode}_{ts}.json"
        out_file.write_text(json.dumps(result_dict, indent=2))

        # Update latest
        latest_file = STATE_DIR / "latest.json"
        latest: dict = {}
        if latest_file.exists():
            try:
                latest = json.loads(latest_file.read_text())
            except Exception:
                pass
        key_str = f"{bare}_{mode}"
        latest[key_str] = result_dict
        latest_file.write_text(json.dumps(latest, indent=2))
    except Exception as exc:
        log.warning("Failed to persist checklist state: %s", exc)

    return result_dict


def run_all_markets(mode: str, ctx: Optional[dict] = None) -> dict:
    """Run checklist for all markets with open positions + approved thesis.

    Returns dict mapping market -> ChecklistResult dict.
    """
    from common.watchlist import get_watchlist_coins

    # Start with thesis-driven approved markets
    approved = ["BTC", "xyz:BRENTOIL", "xyz:GOLD", "xyz:SILVER", "xyz:CL", "xyz:SP500"]

    # Auto-add any market with an open position (Audit F2 rule)
    if ctx is None:
        ctx = build_ctx()

    positions = ctx.get("positions", [])
    position_coins = set(p.get("coin", "") for p in positions if p.get("coin"))
    for coin in position_coins:
        if coin not in approved and coin.replace("xyz:", "") not in [a.replace("xyz:", "") for a in approved]:
            approved.append(coin)

    results = {}
    for market in approved:
        # Build market-scoped ctx (injects market-specific data)
        market_ctx = dict(ctx)
        # Refresh market-specific fields if not already scoped
        if market_ctx.get("thesis") is None or market_ctx.get("market") != market:
            market_ctx["thesis"] = _load_thesis(market)
        market_ctx["market"] = market

        try:
            results[market] = run_checklist(market, mode, market_ctx)
        except Exception as exc:
            log.warning("Checklist failed for %s: %s", market, exc)

    return results
