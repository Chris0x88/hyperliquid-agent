"""Strategy state, decision journal, registry, and lab backtest endpoints."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.api.dependencies import DATA_DIR
from web.api.readers.jsonl_reader import FileEventReader

router = APIRouter()

_STRATEGY_DIR = DATA_DIR / "strategy"
_CONFIG_DIR = DATA_DIR / "config"
_LAB_DIR = DATA_DIR / "lab"

_journal = FileEventReader(_STRATEGY_DIR / "oil_botpattern_journal.jsonl")
_adaptive_log = FileEventReader(_STRATEGY_DIR / "oil_botpattern_adaptive_log.jsonl")
_shadow_trades_reader = FileEventReader(_STRATEGY_DIR / "oil_botpattern_shadow_trades.jsonl")

# Approved markets for backtest — no unsafe inputs
_APPROVED_MARKETS = {"BTC", "BRENTOIL", "CL", "GOLD", "SILVER"}

# All known strategies in strategies/ dir with metadata
_LIBRARY_STRATEGIES: List[Dict[str, Any]] = [
    {"id": "power_law_btc",      "name": "Power Law BTC",         "markets": ["BTC"],              "purpose": "Wraps the Power Law heartbeat model; sizes BTC-PERP positions when price deviates from the power law band."},
    {"id": "momentum_breakout",  "name": "Momentum Breakout",     "markets": ["BTC","BRENTOIL","GOLD"], "purpose": "Enters on volume + price breakout above/below N-period range with ATR-based stops."},
    {"id": "trend_follower",     "name": "Trend Follower",         "markets": ["BTC","BRENTOIL"],   "purpose": "EMA crossover with ADX strength filter to catch sustained moves and avoid choppy ranges."},
    {"id": "mean_reversion",     "name": "Mean Reversion",         "markets": ["BTC"],              "purpose": "Fades overextended moves when RSI and Bollinger bands confirm extreme deviation from SMA."},
    {"id": "funding_arb",        "name": "Funding Arb",            "markets": ["BTC"],              "purpose": "Captures funding rate dislocations between HL and external venues when they diverge from the cross-venue median."},
    {"id": "funding_momentum",   "name": "Funding Momentum",       "markets": ["BTC"],              "purpose": "Trades funding rate extremes as mean-reversion signals — extreme negative funding goes long."},
    {"id": "brent_oil_squeeze",  "name": "Brent Oil Squeeze",      "markets": ["BRENTOIL"],         "purpose": "Geopolitical-thesis + trend-following hybrid for supply squeeze scenarios (Hormuz/UAE disruptions)."},
    {"id": "oil_war_regime",     "name": "Oil War Regime",         "markets": ["BRENTOIL"],         "purpose": "Professional-grade mean-reversion with geopolitical overlay for high-volatility BRENTOIL regime."},
    {"id": "oil_liq_sweep",      "name": "Oil Liq Sweep",          "markets": ["BRENTOIL"],         "purpose": "Profits from leveraged bot liquidation cascades — buys dips caused by stop-hunting."},
    {"id": "basis_arb",          "name": "Basis Arb",              "markets": ["BTC"],              "purpose": "Cash-futures basis arbitrage between spot and perp."},
    {"id": "oi_divergence",      "name": "OI Divergence",          "markets": ["BTC","BRENTOIL"],   "purpose": "Trades open interest divergence from price — leading indicator of large position unwinds."},
    {"id": "grid_mm",            "name": "Grid MM",                "markets": ["BTC"],              "purpose": "Grid market making with inventory management for range-bound markets."},
    {"id": "avellaneda_mm",      "name": "Avellaneda MM",          "markets": ["BTC"],              "purpose": "Avellaneda-Stoikov market-making model with optimal spread / inventory risk control."},
    {"id": "engine_mm",          "name": "Engine MM",              "markets": ["BTC"],              "purpose": "Wrapper around the core market-making engine with configurable quote logic."},
    {"id": "simple_mm",          "name": "Simple MM",              "markets": ["BTC"],              "purpose": "Simple spread-based market maker — baseline reference strategy."},
    {"id": "liquidation_mm",     "name": "Liquidation MM",         "markets": ["BTC"],              "purpose": "Market maker that widens quotes ahead of projected liquidation cascades."},
    {"id": "regime_mm",          "name": "Regime MM",              "markets": ["BTC"],              "purpose": "Regime-aware market maker — switches spread/inventory policy based on detected regime."},
    {"id": "aggressive_taker",   "name": "Aggressive Taker",       "markets": ["BTC"],              "purpose": "Momentum taker — crosses the spread when directional signals align strongly."},
    {"id": "hedge_agent",        "name": "Hedge Agent",            "markets": ["BTC","BRENTOIL","GOLD"], "purpose": "Cross-market hedging agent — reduces correlated exposure between thesis positions."},
    {"id": "rfq_agent",          "name": "RFQ Agent",              "markets": ["BTC"],              "purpose": "Request-for-quote agent for OTC-style large-block executions."},
    {"id": "claude_agent",       "name": "Claude Agent",           "markets": ["BTC","BRENTOIL"],   "purpose": "AI-driven strategy agent — routes AI judgements as trading signals."},
    {"id": "simplified_ensemble","name": "Simplified Ensemble",    "markets": ["BTC"],              "purpose": "Combines signals from multiple sub-strategies via weighted ensemble voting."},
]


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _read_jsonl_latest(path: Path, limit: int = 50) -> List[dict]:
    reader = FileEventReader(path)
    return reader.read_latest(limit)


def _shadow_pnl_summary() -> dict:
    """Compute shadow PnL summary from shadow_trades.jsonl + shadow_balance.json."""
    trades = _shadow_trades_reader.read_latest(1000)
    balance = _read_json(_STRATEGY_DIR / "oil_botpattern_shadow_balance.json")
    seed = balance.get("seed_balance_usd", 100_000.0)
    current = balance.get("current_balance_usd", seed)
    total_pnl = balance.get("realised_pnl_usd", 0.0)
    win_rate = balance.get("win_rate", 0.0)
    closed = balance.get("closed_trades", 0)
    wins = balance.get("wins", 0)
    losses = balance.get("losses", 0)
    return {
        "seed_balance_usd": seed,
        "current_balance_usd": current,
        "realised_pnl_usd": total_pnl,
        "pnl_pct": balance.get("pnl_pct", 0.0),
        "win_rate": win_rate,
        "closed_trades": closed,
        "wins": wins,
        "losses": losses,
        "last_updated_at": balance.get("last_updated_at"),
    }


def _ss_state_for_name(name: str, cfg_name: Optional[str] = None) -> dict:
    cfg_file = cfg_name or name
    cfg_path = _CONFIG_DIR / f"{cfg_file}.json"
    cfg = _read_json(cfg_path)
    return {
        "enabled": cfg.get("enabled", True),
        "has_config": cfg_path.exists(),
        "config": cfg,
    }


def _build_sub6_layers() -> List[dict]:
    """Build the 4 self-improvement layer descriptors with live status."""
    layers = [
        {
            "id": "L1",
            "name": "Bounded Auto-Tune",
            "file": "oil_botpattern_tune",
            "description": "After each closed trade, nudges tunable params (min_edge, sizing thresholds) within hard bounds. Never changes strategy structure — only tightens or loosens numbers.",
            "what_it_produces": "Atomic updates to oil_botpattern.json with an audit trail in oil_botpattern_tune_audit.jsonl.",
            "safe_to_enable": "Enable after 10+ closed trades in shadow mode.",
        },
        {
            "id": "L2",
            "name": "Weekly Reflect Proposals",
            "file": "oil_botpattern_reflect",
            "description": "Runs once per week, reads closed trades + decision journal, detects structural anti-patterns, and writes human-readable proposals. Never auto-applies — you approve via /selftuneapprove.",
            "what_it_produces": "StructuralProposal records in oil_botpattern_proposals.jsonl + Telegram alert.",
            "safe_to_enable": "Enable after 20+ closed trades for meaningful proposals.",
        },
        {
            "id": "L3",
            "name": "Pattern Library Growth",
            "file": "oil_botpattern_patternlib",
            "description": "Watches bot_patterns.jsonl for novel signatures (classification, direction, confidence) that exceed the minimum occurrence threshold, and writes candidates for manual promotion.",
            "what_it_produces": "PatternCandidate records in bot_pattern_candidates.jsonl.",
            "safe_to_enable": "Already enabled — observational only, no trading impact.",
        },
        {
            "id": "L4",
            "name": "Counterfactual Shadow Eval",
            "file": "oil_botpattern_shadow",
            "description": "For each approved L2 proposal, re-runs the recent decision window with the proposed params and computes divergence metrics. Tells you how different the strategy would have behaved.",
            "what_it_produces": "ShadowEval records in oil_botpattern_shadow_evals.jsonl attached to proposals.",
            "safe_to_enable": "Enable after L2 has produced at least one approved proposal.",
        },
    ]
    for layer in layers:
        state = _ss_state_for_name("", cfg_name=layer["file"])
        layer["enabled"] = state["enabled"]
        layer["has_config"] = state["has_config"]
    return layers


# ── Lab helpers ────────────────────────────────────────────────────────────────

def _load_experiments() -> List[dict]:
    exp_file = _LAB_DIR / "experiments.json"
    if not exp_file.exists():
        return []
    try:
        return json.loads(exp_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _lab_config() -> dict:
    return _read_json(_CONFIG_DIR / "lab.json")


# ── Original endpoints (preserved, no regressions) ────────────────────────────

@router.get("/")
async def list_strategies():
    """Summary of all known strategies — extended with registry + shadow PnL."""
    obp_config = _read_json(_CONFIG_DIR / "oil_botpattern.json")
    obp_state = _read_json(_STRATEGY_DIR / "oil_botpattern_state.json")

    enabled = obp_config.get("enabled", False)
    decisions_only = obp_config.get("decisions_only", True)
    short_legs = obp_config.get("short_legs_enabled", False)

    sub_systems_meta = [
        {"id": 1, "name": "news_ingest",     "label": "News Ingest"},
        {"id": 2, "name": "supply_ledger",   "label": "Supply Ledger"},
        {"id": 3, "name": "heatmap",         "label": "Heatmap"},
        {"id": 4, "name": "bot_classifier",  "label": "Bot Classifier"},
        {"id": 5, "name": "oil_botpattern",  "label": "Oil Bot Pattern"},
        {"id": 6, "name": "self_tune",       "label": "Self-Tune"},
    ]

    sub_system_states = []
    for ss in sub_systems_meta:
        cfg_path = _CONFIG_DIR / f"{ss['name']}.json"
        cfg = _read_json(cfg_path)
        sub_system_states.append({
            "id": ss["id"],
            "name": ss["name"],
            "label": ss["label"],
            "enabled": cfg.get("enabled", True),
            "has_config": cfg_path.exists(),
        })

    brakes = {
        "daily": obp_state.get("daily_brake_tripped_at"),
        "weekly": obp_state.get("weekly_brake_tripped_at"),
        "monthly": obp_state.get("monthly_brake_tripped_at"),
    }
    brake_count = sum(1 for v in brakes.values() if v is not None)

    # Shadow PnL from closed shadow trades
    shadow = _shadow_pnl_summary()

    # Latest journal entry for last-activity
    latest_journal = _journal.read_latest(1)
    last_activity = latest_journal[0].get("decided_at") if latest_journal else None

    return {
        "strategies": [
            {
                "id": "oil_botpattern",
                "name": "Oil Bot Pattern",
                "enabled": enabled,
                "decisions_only": decisions_only,
                "shadow_mode": decisions_only,
                "short_legs_enabled": short_legs,
                "sub_system_count": len(sub_systems_meta),
                "sub_systems": sub_system_states,
                "brakes_tripped": brake_count,
                "brakes": brakes,
                "instruments": obp_config.get("instruments", []),
                "shadow_pnl": shadow,
                "last_activity": last_activity,
            }
        ]
    }


@router.get("/oil-botpattern/state")
async def get_oil_botpattern_state():
    """Current oil bot pattern runtime state."""
    state = _read_json(_STRATEGY_DIR / "oil_botpattern_state.json")
    return {"state": state}


@router.get("/oil-botpattern/journal")
async def get_oil_botpattern_journal(limit: int = 20):
    """Paginated decision journal, newest first."""
    entries = _journal.read_latest(limit)
    return {"journal": entries, "count": len(entries)}


@router.get("/oil-botpattern/config")
async def get_oil_botpattern_config():
    """Strategy config with kill switches."""
    cfg = _read_json(_CONFIG_DIR / "oil_botpattern.json")
    return {"config": cfg}


# ── New registry + detail endpoints ───────────────────────────────────────────

@router.get("/registry")
async def get_strategy_registry():
    """Full strategy registry — LIVE + PARKED + LIBRARY groups.

    LIVE: strategies with an active daemon iterator.
    PARKED: registered in roster but paused or kill-switched.
    LIBRARY: code exists in strategies/ but not in roster.
    """
    roster_path = DATA_DIR / "daemon" / "roster.json"
    roster: List[dict] = []
    if roster_path.exists():
        try:
            roster = json.loads(roster_path.read_text())
        except (json.JSONDecodeError, OSError):
            roster = []

    # Build roster index by strategy name fragment
    roster_by_name: Dict[str, dict] = {}
    for entry in roster:
        name = entry.get("name", "")
        roster_by_name[name] = entry

    # Oil botpattern counts as LIVE (daemon iterator, not roster-managed)
    obp_config = _read_json(_CONFIG_DIR / "oil_botpattern.json")
    obp_enabled = obp_config.get("enabled", False)
    shadow = _shadow_pnl_summary()
    latest_journal = _journal.read_latest(1)
    last_activity = latest_journal[0].get("decided_at") if latest_journal else None

    live: List[dict] = []
    parked: List[dict] = []

    # Oil Bot Pattern — always in live section (it's the primary strategy)
    oil_entry = {
        "id": "oil_botpattern",
        "name": "Oil Bot Pattern",
        "status": "SHADOW" if obp_config.get("decisions_only", True) else ("LIVE" if obp_enabled else "PAUSED"),
        "markets": obp_config.get("instruments", ["BRENTOIL", "CL"]),
        "purpose": "Multi-subsystem oil trading strategy. Classifies bot vs informed moves, uses supply disruption data and catalysts, runs full gate chain in shadow mode before real execution.",
        "last_activity": last_activity,
        "shadow_pnl_usd": shadow.get("realised_pnl_usd"),
        "shadow_trades": shadow.get("closed_trades", 0),
        "shadow_win_rate": shadow.get("win_rate"),
    }
    if obp_enabled or obp_config.get("decisions_only", True):
        live.append(oil_entry)
    else:
        parked.append(oil_entry)

    # Roster strategies (power_law_btc etc.)
    for entry in roster:
        name = entry.get("name", "")
        paused = entry.get("paused", False)
        simulate = entry.get("params", {}).get("simulate", False)
        lib_meta = next((s for s in _LIBRARY_STRATEGIES if s["id"] == name), None)
        record = {
            "id": name,
            "name": lib_meta["name"] if lib_meta else name,
            "status": "PAUSED" if paused else ("SHADOW" if simulate else "LIVE"),
            "markets": [entry.get("instrument", "")],
            "purpose": lib_meta["purpose"] if lib_meta else "Roster strategy.",
            "last_tick": entry.get("last_tick"),
            "simulate": simulate,
        }
        if paused or simulate:
            parked.append(record)
        else:
            live.append(record)

    # Library strategies — code exists, not in roster
    roster_ids = {e.get("name") for e in roster} | {"oil_botpattern"}
    library: List[dict] = []
    for s in _LIBRARY_STRATEGIES:
        if s["id"] not in roster_ids:
            library.append({
                "id": s["id"],
                "name": s["name"],
                "status": "DORMANT",
                "markets": s["markets"],
                "purpose": s["purpose"],
            })

    return {
        "live": live,
        "parked": parked,
        "library": library,
        "counts": {
            "live": len(live),
            "parked": len(parked),
            "library": len(library),
        },
    }


@router.get("/oil-botpattern/detail")
async def get_oil_botpattern_detail():
    """Full drill-down for the Oil Bot Pattern strategy."""
    config = _read_json(_CONFIG_DIR / "oil_botpattern.json")
    state = _read_json(_STRATEGY_DIR / "oil_botpattern_state.json")
    shadow_balance = _read_json(_STRATEGY_DIR / "oil_botpattern_shadow_balance.json")
    shadow_positions = _read_json(_STRATEGY_DIR / "oil_botpattern_shadow_positions.json")
    patternlib_state = _read_json(_STRATEGY_DIR / "oil_botpattern_patternlib_state.json")

    # Sub-systems with named descriptions
    sub_systems = [
        {
            "id": 1, "name": "news_ingest", "label": "News Ingest",
            "description": "Polls RSS/iCal feeds for oil news. Scores and stores headlines as catalyst events. Feeds sub-system 2 and 4.",
            "data_in": ["RSS feeds", "iCal feeds"],
            "data_out": ["data/news/headlines.jsonl", "data/news/catalysts.jsonl"],
        },
        {
            "id": 2, "name": "supply_ledger", "label": "Supply Ledger",
            "description": "Tracks active supply disruptions (pipeline damage, sanctions, field shutdowns). Auto-extracts from catalyst events. Gate input for sub-system 5.",
            "data_in": ["data/news/catalysts.jsonl"],
            "data_out": ["data/supply/disruptions.jsonl"],
        },
        {
            "id": 3, "name": "heatmap", "label": "Heatmap",
            "description": "Detects large liquidity zones from order book snapshots. Identifies where stop clusters and iceberg orders sit. Used by sub-system 5 for entry timing.",
            "data_in": ["Live order book", "BRENTOIL"],
            "data_out": ["data/heatmap/zones.jsonl"],
        },
        {
            "id": 4, "name": "bot_classifier", "label": "Bot Classifier",
            "description": "Classifies every candle as informed_move, bot_driven, or noise using pattern signatures. Pattern library (L3) grows this catalog over time.",
            "data_in": ["BRENTOIL candles", "bot_pattern_catalog"],
            "data_out": ["data/research/bot_patterns.jsonl"],
        },
        {
            "id": 5, "name": "oil_botpattern", "label": "Strategy Engine",
            "description": "The trading brain. Reads outputs from SS1-4 + thesis conviction + funding rates. Runs a gate chain (bot-pattern gate, supply gate, catalyst gate, funding gate). In shadow mode: logs every decision to oil_botpattern_adaptive_log.jsonl but never places real orders.",
            "data_in": ["SS1-4 outputs", "thesis conviction", "funding rates"],
            "data_out": ["oil_botpattern_adaptive_log.jsonl", "oil_botpattern_shadow_trades.jsonl"],
        },
        {
            "id": 6, "name": "self_tune", "label": "Self-Improvement (L1-L4)",
            "description": "Four-layer self-improvement harness. L1 tunes params after each trade. L2 proposes structural changes weekly. L3 grows the pattern library. L4 counterfactually evaluates approved proposals.",
            "data_in": ["oil_botpattern_adaptive_log.jsonl", "closed trades", "proposals"],
            "data_out": ["param updates", "proposals", "pattern candidates", "shadow evals"],
        },
    ]

    sub_system_states = []
    for ss in sub_systems:
        cfg_name = ss["name"]
        cfg_path = _CONFIG_DIR / f"{cfg_name}.json"
        cfg = _read_json(cfg_path)
        sub_system_states.append({
            **ss,
            "enabled": cfg.get("enabled", True),
            "has_config": cfg_path.exists(),
        })

    # Self-improvement layers
    sub6_layers = _build_sub6_layers()

    # Shadow activity
    shadow_trades = _shadow_trades_reader.read_latest(20)

    return {
        "config": config,
        "state": state,
        "shadow_balance": shadow_balance,
        "shadow_positions": shadow_positions.get("positions", []),
        "sub_systems": sub_system_states,
        "sub6_layers": sub6_layers,
        "patternlib_state": patternlib_state,
        "recent_shadow_trades": shadow_trades,
    }


@router.get("/oil-botpattern/activity")
async def get_oil_botpattern_activity(limit: int = 20):
    """Recent decisions from adaptive log + shadow trade exits, newest first."""
    # Adaptive log decisions
    decisions = _adaptive_log.read_latest(limit)
    # Shadow trade exits
    shadow_exits = _shadow_trades_reader.read_latest(limit)

    # Merge and tag
    activity: List[dict] = []
    for d in decisions:
        activity.append({
            "type": "decision",
            "ts": d.get("logged_at"),
            "instrument": d.get("position", {}).get("instrument"),
            "action": d.get("decision", {}).get("action"),
            "reason": d.get("decision", {}).get("reason"),
            "price_progress": d.get("decision", {}).get("price_progress"),
        })
    for t in shadow_exits:
        activity.append({
            "type": "shadow_trade",
            "ts": t.get("exit_ts"),
            "instrument": t.get("instrument"),
            "action": t.get("exit_reason"),
            "pnl_usd": t.get("realised_pnl_usd"),
            "roe_pct": t.get("roe_pct"),
            "edge": t.get("edge"),
            "hold_hours": t.get("hold_hours"),
        })

    # Sort newest first
    def _ts_sort(item: dict) -> float:
        ts = item.get("ts") or ""
        return ts

    activity.sort(key=_ts_sort, reverse=True)
    return {"activity": activity[:limit], "count": len(activity[:limit])}


# ── Lab endpoints ──────────────────────────────────────────────────────────────

@router.get("/lab/status")
async def get_lab_status():
    """Lab Engine status — archetypes, experiments by kanban column, config."""
    lab_config = _lab_config()
    experiments = _load_experiments()

    # Group by status for kanban
    kanban: Dict[str, List[dict]] = {
        "hypothesis": [],
        "backtesting": [],
        "paper_trading": [],
        "graduated": [],
        "production": [],
        "retired": [],
    }
    for exp in experiments:
        status = exp.get("status", "hypothesis")
        bucket = kanban.setdefault(status, [])
        bucket.append({
            "id": exp.get("id"),
            "market": exp.get("market"),
            "strategy": exp.get("strategy"),
            "params": exp.get("params", {}),
            "backtest_metrics": exp.get("backtest_metrics", {}),
            "backtest_trades": exp.get("backtest_trades", 0),
            "paper_pnl": exp.get("paper_pnl", 0),
            "paper_trades": exp.get("paper_trades", 0),
            "paper_metrics": exp.get("paper_metrics", {}),
            "graduation_passed": exp.get("graduation_passed", False),
            "graduation_notes": exp.get("graduation_notes", ""),
            "created_at": exp.get("created_at"),
            "updated_at": exp.get("updated_at"),
        })

    # Archetype catalog
    from engines.learning.lab_engine import STRATEGY_ARCHETYPES
    archetypes = [
        {
            "id": name,
            "description": meta["description"],
            "params": meta["params"],
            "signals": meta["signals"],
            "suitable_for": meta["suitable_for"],
            "wired": name == "momentum_breakout",  # only wired archetype
        }
        for name, meta in STRATEGY_ARCHETYPES.items()
    ]

    return {
        "enabled": lab_config.get("enabled", False),
        "graduation_thresholds": lab_config.get("graduation", {}),
        "kanban": kanban,
        "archetypes": archetypes,
        "approved_markets": sorted(_APPROVED_MARKETS),
    }


class BacktestRequest(BaseModel):
    market: str
    archetype: str
    params: Optional[Dict[str, Any]] = None


@router.post("/lab/backtest")
async def run_lab_backtest(req: BacktestRequest):
    """Trigger a backtest for a market + archetype combo.

    Creates a hypothesis experiment and runs backtest immediately.
    Only approved markets are accepted. Returns metrics or error message.
    """
    # Validate market
    market_clean = req.market.replace("xyz:", "").upper()
    if market_clean not in _APPROVED_MARKETS:
        raise HTTPException(
            status_code=400,
            detail=f"Market '{req.market}' not in approved list: {sorted(_APPROVED_MARKETS)}",
        )

    try:
        import sys
        # Ensure project root is importable
        project_root = str(DATA_DIR.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from engines.learning.lab_engine import LabEngine, STRATEGY_ARCHETYPES

        if req.archetype not in STRATEGY_ARCHETYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown archetype '{req.archetype}'. Valid: {list(STRATEGY_ARCHETYPES)}",
            )

        lab = LabEngine()

        # Override enabled for this one-shot backtest
        lab._config["enabled"] = True

        params = req.params or STRATEGY_ARCHETYPES[req.archetype]["params"].copy()
        exp = lab.create_experiment(market_clean, req.archetype, params)
        if exp is None:
            raise HTTPException(status_code=500, detail="Failed to create experiment")

        metrics = lab.run_backtest(exp.id)

        # Reload experiment to get final state
        lab._load_experiments()
        final_exp = lab.get_experiment(exp.id)

        return {
            "experiment_id": exp.id,
            "market": market_clean,
            "archetype": req.archetype,
            "status": final_exp.status if final_exp else "unknown",
            "metrics": metrics or final_exp.backtest_metrics if final_exp else {},
            "trades": final_exp.backtest_trades if final_exp else 0,
            "params": params,
        }

    except NotImplementedError as e:
        # Surface stub error cleanly to UI
        return {
            "experiment_id": None,
            "market": market_clean,
            "archetype": req.archetype,
            "status": "not_implemented",
            "error": str(e),
            "metrics": {},
            "trades": 0,
            "params": req.params or {},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/oil-botpattern/shadow-summary")
async def get_shadow_summary():
    """Shadow P&L summary and current positions."""
    balance = _read_json(_STRATEGY_DIR / "oil_botpattern_shadow_balance.json")
    positions = _read_json(_STRATEGY_DIR / "oil_botpattern_shadow_positions.json")
    shadow_trades = _shadow_trades_reader.read_latest(50)

    # Compute per-trade stats
    trade_stats: List[dict] = []
    for t in shadow_trades:
        trade_stats.append({
            "instrument": t.get("instrument"),
            "side": t.get("side"),
            "entry_price": t.get("entry_price"),
            "exit_price": t.get("exit_price"),
            "pnl_usd": t.get("realised_pnl_usd"),
            "roe_pct": t.get("roe_pct"),
            "exit_reason": t.get("exit_reason"),
            "edge": t.get("edge"),
            "hold_hours": t.get("hold_hours"),
            "entry_ts": t.get("entry_ts"),
            "exit_ts": t.get("exit_ts"),
        })

    return {
        "balance": balance,
        "positions": positions.get("positions", []),
        "recent_trades": trade_stats,
    }
