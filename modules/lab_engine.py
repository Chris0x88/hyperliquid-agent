"""Lab Engine — autonomous strategy development pipeline.

Takes a market from raw discovery through to production-ready, with gates:

  DISCOVERY   → Scan markets for characteristics (Radar + custom filters)
  HYPOTHESIS  → Select strategy archetypes that fit the market profile
  BACKTEST    → Run backtests with parameter variations, score results
  PAPER_TRADE → Run in mock mode for N ticks, track live performance
  GRADUATED   → Metrics exceed thresholds → propose for live deployment
  REJECTED    → Metrics failed → archive with learnings

Each market+strategy combo is a LabExperiment that progresses through stages.
The Lab runs autonomously in the daemon (every 15 min) and sends Telegram
alerts when experiments graduate or need attention.

This is the "get a trading bot up and running" system the user controls
by turning it on/off, while the Lab handles the research → production path.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("lab")

LAB_DIR = "data/lab"
EXPERIMENTS_FILE = f"{LAB_DIR}/experiments.json"
LAB_LOG_FILE = f"{LAB_DIR}/lab_log.jsonl"

# Graduation thresholds (must ALL pass to graduate)
GRADUATION_THRESHOLDS = {
    "min_sharpe": 0.8,          # annualized Sharpe ratio
    "min_win_rate": 40.0,       # percentage
    "max_drawdown_pct": 15.0,   # max acceptable drawdown
    "min_profit_factor": 1.3,   # gross wins / gross losses
    "min_trades": 10,           # must have enough samples
    "min_backtest_days": 30,    # minimum data coverage
}

# Strategy archetypes matched to market characteristics
STRATEGY_ARCHETYPES = {
    "trending": [
        "momentum_breakout", "trend_follower", "power_law_btc",
    ],
    "mean_reverting": [
        "mean_reversion", "grid_mm", "avellaneda_mm",
    ],
    "high_funding": [
        "funding_arb", "funding_momentum",
    ],
    "high_volatility": [
        "brent_oil_squeeze", "oil_liq_sweep",
    ],
    "liquid": [
        "simple_mm", "engine_mm", "avellaneda_mm",
    ],
}


@dataclass
class BacktestMetrics:
    """Metrics from a backtest run."""
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float = 0.0
    net_pnl: float = 0.0
    net_pnl_pct: float = 0.0
    total_trades: int = 0
    candles_processed: int = 0
    best_trade: float = 0.0
    worst_trade: float = 0.0

    def passes_graduation(self) -> bool:
        return (
            self.sharpe_ratio >= GRADUATION_THRESHOLDS["min_sharpe"]
            and self.win_rate >= GRADUATION_THRESHOLDS["min_win_rate"]
            and self.max_drawdown_pct <= GRADUATION_THRESHOLDS["max_drawdown_pct"]
            and self.profit_factor >= GRADUATION_THRESHOLDS["min_profit_factor"]
            and self.total_trades >= GRADUATION_THRESHOLDS["min_trades"]
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LabExperiment:
    """One market + strategy combination being tested."""

    experiment_id: str = ""
    market: str = ""               # e.g. "BTC-PERP", "xyz:BRENTOIL"
    strategy: str = ""             # e.g. "momentum_breakout"
    params: Dict[str, Any] = field(default_factory=dict)

    stage: str = "discovery"       # discovery, hypothesis, backtest, paper_trade, graduated, rejected
    created_ts: int = 0
    updated_ts: int = 0
    stage_history: List[Dict] = field(default_factory=list)

    # Discovery data
    market_profile: Dict[str, Any] = field(default_factory=dict)

    # Backtest results (may have multiple runs with different params)
    backtest_results: List[Dict] = field(default_factory=list)
    best_backtest: Optional[Dict] = None

    # Paper trade metrics (accumulated during mock runs)
    paper_trade_ticks: int = 0
    paper_trade_pnl: float = 0.0
    paper_trade_start_ts: int = 0

    # Graduation
    graduation_score: float = 0.0
    rejection_reason: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.created_ts:
            self.created_ts = int(time.time() * 1000)
        if not self.experiment_id:
            self.experiment_id = f"{self.market}:{self.strategy}:{self.created_ts}"

    def advance_stage(self, new_stage: str, reason: str = "") -> None:
        self.stage_history.append({
            "from": self.stage,
            "to": new_stage,
            "ts": int(time.time() * 1000),
            "reason": reason,
        })
        self.stage = new_stage
        self.updated_ts = int(time.time() * 1000)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> LabExperiment:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class LabEngine:
    """Manages the lifecycle of strategy experiments.

    Call tick() periodically (e.g., every 15 min from the daemon).
    It will progress experiments through their stages automatically.
    """

    def __init__(self):
        self._experiments: List[LabExperiment] = []
        self._load()

    def _load(self) -> None:
        path = Path(EXPERIMENTS_FILE)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                self._experiments = [LabExperiment.from_dict(d) for d in data]
                log.info("Lab: loaded %d experiments", len(self._experiments))
            except Exception as e:
                log.error("Lab: failed to load experiments: %s", e)

    def _save(self) -> None:
        Path(LAB_DIR).mkdir(parents=True, exist_ok=True)
        with open(EXPERIMENTS_FILE, "w") as f:
            json.dump([e.to_dict() for e in self._experiments], f, indent=2)

    def _log_event(self, event_type: str, data: dict) -> None:
        Path(LAB_DIR).mkdir(parents=True, exist_ok=True)
        entry = {"ts": int(time.time() * 1000), "type": event_type, **data}
        with open(LAB_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # ── Public API ──────────────────────────────────────────────

    @property
    def experiments(self) -> List[LabExperiment]:
        return self._experiments

    def get_active(self) -> List[LabExperiment]:
        """Experiments not yet graduated or rejected."""
        return [e for e in self._experiments if e.stage not in ("graduated", "rejected")]

    def get_graduated(self) -> List[LabExperiment]:
        return [e for e in self._experiments if e.stage == "graduated"]

    def get_by_stage(self, stage: str) -> List[LabExperiment]:
        return [e for e in self._experiments if e.stage == stage]

    def create_experiment(self, market: str, strategy: str, params: Optional[Dict] = None) -> LabExperiment:
        """Create a new experiment manually or from discovery."""
        exp = LabExperiment(
            market=market,
            strategy=strategy,
            params=params or {},
            stage="hypothesis",
        )
        self._experiments.append(exp)
        self._save()
        self._log_event("created", {"id": exp.experiment_id, "market": market, "strategy": strategy})
        log.info("Lab: created experiment %s", exp.experiment_id)
        return exp

    # ── Discovery: profile a market ─────────────────────────────

    def discover_market(self, market: str, candles: List[Dict]) -> Dict[str, Any]:
        """Analyze a market's characteristics from OHLCV data.

        Returns a profile dict with: volatility, trend_strength, mean_reversion_score,
        avg_volume, funding_bias, recommended_archetypes.
        """
        if not candles or len(candles) < 20:
            return {"error": "insufficient data", "candles": len(candles) if candles else 0}

        import numpy as np

        closes = np.array([float(c["c"]) for c in candles])
        highs = np.array([float(c["h"]) for c in candles])
        lows = np.array([float(c["l"]) for c in candles])
        volumes = np.array([float(c["v"]) for c in candles])

        # Returns
        returns = np.diff(closes) / closes[:-1]

        # Volatility (annualized)
        volatility = float(np.std(returns) * np.sqrt(365 * 24))

        # Trend strength: autocorrelation of returns
        if len(returns) > 1:
            autocorr = float(np.corrcoef(returns[:-1], returns[1:])[0, 1])
        else:
            autocorr = 0.0
        trend_strength = max(0, autocorr)

        # Mean reversion score: negative autocorrelation = mean reverting
        mean_reversion_score = max(0, -autocorr)

        # Average true range (ATR proxy)
        tr = np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]))
        atr_pct = float(np.mean(tr / closes[:-1]) * 100) if len(closes) > 1 else 0

        # Volume profile
        avg_volume = float(np.mean(volumes))

        # Classify
        archetypes = []
        if trend_strength > 0.1:
            archetypes.append("trending")
        if mean_reversion_score > 0.1:
            archetypes.append("mean_reverting")
        if volatility > 1.0:
            archetypes.append("high_volatility")
        if avg_volume > 1_000_000:
            archetypes.append("liquid")
        if not archetypes:
            archetypes.append("trending")  # default

        profile = {
            "market": market,
            "volatility_ann": round(volatility, 4),
            "trend_strength": round(trend_strength, 4),
            "mean_reversion_score": round(mean_reversion_score, 4),
            "atr_pct": round(atr_pct, 4),
            "avg_volume": round(avg_volume, 2),
            "candles_analyzed": len(candles),
            "archetypes": archetypes,
        }
        return profile

    def create_experiments_from_profile(self, market: str, profile: Dict) -> List[LabExperiment]:
        """Given a market profile, create experiments for matching strategy archetypes."""
        archetypes = profile.get("archetypes", ["trending"])
        experiments = []

        for archetype in archetypes:
            strategies = STRATEGY_ARCHETYPES.get(archetype, [])
            for strategy in strategies:
                # Skip if we already have an active experiment for this combo
                existing = [
                    e for e in self._experiments
                    if e.market == market and e.strategy == strategy
                    and e.stage not in ("rejected",)
                ]
                if existing:
                    continue

                exp = LabExperiment(
                    market=market,
                    strategy=strategy,
                    stage="hypothesis",
                    market_profile=profile,
                )
                self._experiments.append(exp)
                experiments.append(exp)
                log.info("Lab: created %s for %s (archetype=%s)", strategy, market, archetype)

        if experiments:
            self._save()
            self._log_event("discovery", {
                "market": market,
                "profile": profile,
                "experiments_created": len(experiments),
            })

        return experiments

    # ── Backtest: run and score ──────────────────────────────────

    def record_backtest(self, experiment_id: str, result: Dict) -> None:
        """Record a backtest result for an experiment."""
        exp = self._find(experiment_id)
        if not exp:
            return

        exp.backtest_results.append(result)

        # Track best result
        if exp.best_backtest is None or result.get("sharpe_ratio", 0) > exp.best_backtest.get("sharpe_ratio", 0):
            exp.best_backtest = result

        # Check if we should advance to paper_trade
        metrics = BacktestMetrics(**{k: v for k, v in result.items() if k in BacktestMetrics.__dataclass_fields__})
        if metrics.passes_graduation():
            exp.advance_stage("paper_trade", f"Backtest passed: sharpe={metrics.sharpe_ratio:.2f}, wr={metrics.win_rate:.1f}%")
            exp.graduation_score = metrics.sharpe_ratio
            log.info("Lab: %s advanced to paper_trade (sharpe=%.2f)", experiment_id, metrics.sharpe_ratio)
        elif len(exp.backtest_results) >= 3:
            # 3 failed backtests → reject
            exp.advance_stage("rejected", "3 backtests failed graduation thresholds")
            log.info("Lab: %s rejected after 3 failed backtests", experiment_id)

        self._save()

    def run_backtest(self, experiment_id: str) -> Optional[Dict]:
        """Run a backtest for an experiment. Returns metrics dict or None."""
        exp = self._find(experiment_id)
        if not exp:
            return None

        try:
            from modules.candle_cache import CandleCache
            from modules.backtest_engine import BacktestEngine, BacktestConfig

            coin = exp.market.replace("-PERP", "").replace("xyz:", "")
            config = BacktestConfig(
                coin=coin,
                instrument=exp.market,
                interval="1h",
                days=90,
            )

            # Load strategy
            from cli.strategy_registry import STRATEGY_REGISTRY
            reg = STRATEGY_REGISTRY.get(exp.strategy)
            if not reg:
                log.warning("Lab: unknown strategy %s", exp.strategy)
                return None

            strategy_cls = reg["class"]
            params = {**reg.get("params", {}), **exp.params}
            strategy = strategy_cls(**params) if params else strategy_cls()

            cache = CandleCache()
            engine = BacktestEngine(cache, config)
            result = engine.run(strategy)
            result.compute_metrics()

            metrics = {
                "sharpe_ratio": result.sharpe_ratio,
                "win_rate": result.win_rate,
                "max_drawdown_pct": result.max_drawdown_pct,
                "profit_factor": result.profit_factor,
                "net_pnl": result.net_pnl,
                "net_pnl_pct": result.net_pnl_pct,
                "total_trades": result.total_trades,
                "candles_processed": result.candles_processed,
                "best_trade": result.best_trade,
                "worst_trade": result.worst_trade,
                "run_ts": int(time.time() * 1000),
            }

            self.record_backtest(experiment_id, metrics)
            return metrics

        except Exception as e:
            log.error("Lab: backtest failed for %s: %s", experiment_id, e)
            return None

    # ── Paper trade tracking ─────────────────────────────────────

    def record_paper_tick(self, experiment_id: str, pnl_delta: float) -> None:
        """Record one paper trade tick for an experiment."""
        exp = self._find(experiment_id)
        if not exp or exp.stage != "paper_trade":
            return

        if exp.paper_trade_start_ts == 0:
            exp.paper_trade_start_ts = int(time.time() * 1000)

        exp.paper_trade_ticks += 1
        exp.paper_trade_pnl += pnl_delta
        exp.updated_ts = int(time.time() * 1000)

        # Check graduation after minimum ticks (e.g., 24h worth at 60s ticks)
        min_ticks = 1440  # 24 hours
        if exp.paper_trade_ticks >= min_ticks:
            if exp.paper_trade_pnl > 0 and exp.graduation_score > 0:
                exp.advance_stage("graduated",
                    f"Paper trade passed: {exp.paper_trade_ticks} ticks, "
                    f"pnl=${exp.paper_trade_pnl:.2f}")
                log.info("Lab: %s GRADUATED!", experiment_id)
            elif exp.paper_trade_ticks >= min_ticks * 3:
                exp.advance_stage("rejected",
                    f"Paper trade failed: {exp.paper_trade_ticks} ticks, "
                    f"pnl=${exp.paper_trade_pnl:.2f}")

        self._save()

    # ── Tick: progress experiments ───────────────────────────────

    def tick(self) -> List[Dict]:
        """Run one lab cycle. Returns list of events (for Telegram alerts)."""
        events = []

        for exp in self.get_active():
            if exp.stage == "hypothesis":
                # Auto-advance to backtest
                exp.advance_stage("backtest", "Auto-advancing from hypothesis")
                events.append({"type": "stage_change", "id": exp.experiment_id, "stage": "backtest"})

            elif exp.stage == "backtest":
                # Run backtest if not yet done
                if len(exp.backtest_results) < 3:
                    metrics = self.run_backtest(exp.experiment_id)
                    if metrics:
                        events.append({
                            "type": "backtest_complete",
                            "id": exp.experiment_id,
                            "metrics": metrics,
                        })
                        if exp.stage == "paper_trade":
                            events.append({
                                "type": "stage_change",
                                "id": exp.experiment_id,
                                "stage": "paper_trade",
                                "message": f"{exp.market}:{exp.strategy} passed backtest! "
                                           f"Sharpe={metrics['sharpe_ratio']:.2f}",
                            })

        self._save()
        return events

    # ── Status ───────────────────────────────────────────────────

    def status(self) -> Dict:
        """Return a summary of the lab's state."""
        by_stage = {}
        for exp in self._experiments:
            by_stage.setdefault(exp.stage, []).append(exp.experiment_id)

        return {
            "total_experiments": len(self._experiments),
            "by_stage": {stage: len(ids) for stage, ids in by_stage.items()},
            "active": [
                {
                    "id": e.experiment_id,
                    "market": e.market,
                    "strategy": e.strategy,
                    "stage": e.stage,
                    "score": e.graduation_score,
                }
                for e in self.get_active()
            ],
            "graduated": [
                {
                    "id": e.experiment_id,
                    "market": e.market,
                    "strategy": e.strategy,
                    "score": e.graduation_score,
                }
                for e in self.get_graduated()
            ],
        }

    # ── Helpers ──────────────────────────────────────────────────

    def _find(self, experiment_id: str) -> Optional[LabExperiment]:
        for exp in self._experiments:
            if exp.experiment_id == experiment_id:
                return exp
        return None
