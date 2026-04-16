"""Lab Engine — autonomous strategy development pipeline.

Lifecycle: DISCOVER → HYPOTHESIS → BACKTEST → PAPER_TRADE → GRADUATED → PRODUCTION

Each experiment tracks:
  - Market, strategy archetype, parameters
  - Backtest metrics (Sharpe, win rate, max drawdown, profit factor)
  - Paper trade metrics (live validation)
  - Graduation criteria (must pass all thresholds)
  - Production deployment status

Multiple strategies can run per market. Graduated strategies become
signals in a matrix — multiple signals lining up = higher conviction.

This module is pure computation + file I/O. No API calls, no AI calls.
The daemon iterator (`lab`) drives the tick loop.

Kill switch: data/config/lab.json → enabled: false

Usage:
    from engines.learning.lab_engine import LabEngine
    lab = LabEngine()
    lab.discover("BRENTOIL")  # profiles market, creates candidate experiments
    lab.create_experiment("BTC", "momentum_breakout", params={...})
    lab.run_backtest("exp-001")  # uses modules/backtest_engine.py
    status = lab.get_status()
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("lab_engine")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LAB_DIR = _PROJECT_ROOT / "data" / "lab"
_EXPERIMENTS_FILE = _LAB_DIR / "experiments.json"
_CONFIG_FILE = _PROJECT_ROOT / "data" / "config" / "lab.json"

# Graduation thresholds — experiments must pass ALL to graduate
_DEFAULT_GRADUATION = {
    "min_sharpe": 0.8,
    "min_win_rate": 0.40,
    "max_drawdown": 0.15,    # 15%
    "min_profit_factor": 1.3,
    "min_trades": 20,        # minimum trades in backtest
    "min_paper_hours": 24,   # minimum paper trading duration
}

# Strategy archetypes — each defines a parameter template
STRATEGY_ARCHETYPES = {
    "momentum_breakout": {
        "description": "Breakout on strong momentum with ATR-based stops",
        "params": {
            "lookback_bars": 20,
            "breakout_atr_mult": 1.5,
            "stop_atr_mult": 2.0,
            "take_profit_atr_mult": 4.0,
            "min_adx": 25,
            "min_volume_ratio": 1.2,
        },
        "signals": ["ema_cross", "adx", "volume_breakout"],
        "suitable_for": ["trending", "high_volatility"],
    },
    "mean_reversion": {
        "description": "Fade overextended moves with RSI + Bollinger bands",
        "params": {
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "bb_period": 20,
            "bb_std": 2.0,
            "stop_atr_mult": 1.5,
            "take_profit_pct": 0.02,
        },
        "signals": ["rsi", "bollinger", "volume_decline"],
        "suitable_for": ["range_bound", "low_volatility"],
    },
    "bot_fade": {
        "description": "Fade bot-driven overcorrections using classifier signals",
        "params": {
            "min_bot_confidence": 0.7,
            "fade_entry_pct": 0.02,     # enter after 2% overcorrection
            "stop_pct": 0.03,
            "take_profit_pct": 0.04,
            "max_hold_hours": 24,
        },
        "signals": ["bot_classifier", "supply_disruption", "catalyst_timing"],
        "suitable_for": ["bot_driven", "event_driven"],
    },
    "catalyst_anticipation": {
        "description": "Position ahead of known catalysts, exit on event",
        "params": {
            "entry_hours_before": 48,
            "exit_hours_after": 4,
            "min_catalyst_severity": 3,
            "stop_pct": 0.02,
            "size_by_severity": True,
        },
        "signals": ["catalyst_calendar", "supply_ledger", "thesis"],
        "suitable_for": ["event_driven", "oil"],
    },
    "trend_following": {
        "description": "Follow established trends with trailing stops",
        "params": {
            "fast_ema": 12,
            "slow_ema": 26,
            "signal_ema": 9,
            "trail_atr_mult": 3.0,
            "min_trend_strength": 0.6,
        },
        "signals": ["ema_cross", "macd", "adx"],
        "suitable_for": ["trending"],
    },
}


@dataclass
class Experiment:
    """A single strategy experiment in the lab pipeline."""
    id: str
    market: str
    strategy: str                   # archetype name
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "hypothesis"      # hypothesis → backtesting → paper_trading → graduated → production → retired
    created_at: float = 0.0
    updated_at: float = 0.0

    # Backtest results
    backtest_metrics: Dict[str, float] = field(default_factory=dict)
    backtest_trades: int = 0
    backtest_completed_at: float = 0.0

    # Paper trading results
    paper_start_at: float = 0.0
    paper_trades: int = 0
    paper_pnl: float = 0.0
    paper_metrics: Dict[str, float] = field(default_factory=dict)

    # Graduation
    graduation_passed: bool = False
    graduation_notes: str = ""

    # Production
    production_enabled: bool = False
    production_start_at: float = 0.0
    frozen: bool = False            # once approved, freeze params

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Experiment":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class LabEngine:
    """Strategy development lab — manages experiment lifecycle."""

    def __init__(self, config_path: str = str(_CONFIG_FILE)):
        self._config_path = Path(config_path)
        self._config = self._load_config()
        self._experiments: List[Experiment] = []
        self._load_experiments()

    @property
    def enabled(self) -> bool:
        return self._config.get("enabled", False)

    def _load_config(self) -> dict:
        if self._config_path.exists():
            try:
                return json.loads(self._config_path.read_text())
            except Exception:
                pass
        return {"enabled": False, "graduation": _DEFAULT_GRADUATION}

    def _load_experiments(self) -> None:
        if _EXPERIMENTS_FILE.exists():
            try:
                data = json.loads(_EXPERIMENTS_FILE.read_text())
                self._experiments = [Experiment.from_dict(e) for e in data]
            except Exception as e:
                log.warning("Failed to load experiments: %s", e)
                self._experiments = []

    def _save_experiments(self) -> None:
        _LAB_DIR.mkdir(parents=True, exist_ok=True)
        data = [e.to_dict() for e in self._experiments]
        _EXPERIMENTS_FILE.write_text(json.dumps(data, indent=2))

    # ── Discovery ────────────────────────────────────────────────

    def discover(self, market: str) -> List[str]:
        """Profile a market and create candidate experiments for matching archetypes.

        Returns list of created experiment IDs.
        """
        if not self.enabled:
            return []

        profile = self._profile_market(market)
        created_ids = []

        for arch_name, arch in STRATEGY_ARCHETYPES.items():
            # Check if this archetype suits the market profile
            if not self._archetype_matches(arch, profile):
                continue

            # Skip if we already have an active experiment for this combo
            existing = [e for e in self._experiments
                        if e.market == market and e.strategy == arch_name
                        and e.status not in ("retired",)]
            if existing:
                continue

            exp = self.create_experiment(market, arch_name, arch["params"].copy())
            if exp:
                created_ids.append(exp.id)

        return created_ids

    def _profile_market(self, market: str) -> dict:
        """Profile a market's characteristics from cached data."""
        profile = {
            "market": market,
            "volatility": "medium",
            "trend_strength": "medium",
            "mean_reversion": False,
            "bot_driven": False,
            "event_driven": False,
        }

        # Read from radar/market_structure data if available
        try:
            from engines.data.candle_cache import CandleCache
            cache = CandleCache()
            candles = cache.read(market, "1d", limit=30)
            if candles:
                # Simple volatility classification from daily ranges
                ranges = [(c.get("h", 0) - c.get("l", 0)) / max(c.get("c", 1), 0.01)
                          for c in candles if c.get("c")]
                avg_range = sum(ranges) / len(ranges) if ranges else 0
                if avg_range > 0.03:
                    profile["volatility"] = "high"
                elif avg_range < 0.01:
                    profile["volatility"] = "low"
        except Exception:
            pass

        # Check bot classifier data
        try:
            bp_path = _PROJECT_ROOT / "data" / "research" / "bot_patterns.jsonl"
            if bp_path.exists():
                from collections import Counter
                bare = market.replace("xyz:", "").upper()
                classifications = Counter()
                with bp_path.open() as fh:
                    for ln in fh:
                        try:
                            entry = json.loads(ln)
                            if entry.get("instrument", "").replace("xyz:", "").upper() == bare:
                                classifications[entry.get("classification", "")] += 1
                        except Exception:
                            continue
                if classifications.get("bot_driven", 0) > classifications.get("informed", 0):
                    profile["bot_driven"] = True
        except Exception:
            pass

        # Oil markets are event-driven
        if market.upper() in ("BRENTOIL", "CL"):
            profile["event_driven"] = True

        return profile

    def _archetype_matches(self, archetype: dict, profile: dict) -> bool:
        """Check if an archetype's suitability matches the market profile."""
        suitable = set(archetype.get("suitable_for", []))
        if not suitable:
            return True

        # Map profile characteristics to suitability tags
        profile_tags = set()
        vol = profile.get("volatility", "medium")
        if vol == "high":
            profile_tags.add("high_volatility")
            profile_tags.add("trending")
        elif vol == "low":
            profile_tags.add("low_volatility")
            profile_tags.add("range_bound")
        else:
            profile_tags.add("trending")
            profile_tags.add("range_bound")

        if profile.get("bot_driven"):
            profile_tags.add("bot_driven")
        if profile.get("event_driven"):
            profile_tags.add("event_driven")
            profile_tags.add("oil")

        return bool(suitable & profile_tags)

    # ── Experiment CRUD ──────────────────────────────────────────

    def create_experiment(
        self, market: str, strategy: str, params: Optional[dict] = None
    ) -> Optional[Experiment]:
        """Create a new experiment."""
        if not self.enabled:
            return None

        if strategy not in STRATEGY_ARCHETYPES:
            log.warning("Unknown strategy archetype: %s", strategy)
            return None

        if params is None:
            params = STRATEGY_ARCHETYPES[strategy]["params"].copy()

        exp = Experiment(
            id=f"exp-{uuid.uuid4().hex[:8]}",
            market=market,
            strategy=strategy,
            params=params,
            status="hypothesis",
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._experiments.append(exp)
        self._save_experiments()
        log.info("Created experiment %s: %s on %s", exp.id, strategy, market)
        return exp

    def get_experiment(self, exp_id: str) -> Optional[Experiment]:
        for e in self._experiments:
            if e.id == exp_id:
                return e
        return None

    def get_status(self) -> Dict[str, Any]:
        """Get summary of all experiments grouped by status."""
        by_status: Dict[str, list] = {}
        for e in self._experiments:
            by_status.setdefault(e.status, []).append({
                "id": e.id,
                "market": e.market,
                "strategy": e.strategy,
                "metrics": e.backtest_metrics or e.paper_metrics,
            })
        return {
            "total": len(self._experiments),
            "by_status": by_status,
            "enabled": self.enabled,
        }

    # ── Backtest ─────────────────────────────────────────────────

    def run_backtest(self, exp_id: str) -> Optional[Dict[str, float]]:
        """Run a backtest for an experiment using the backtest engine.

        Returns metrics dict or None if backtest couldn't run.
        """
        exp = self.get_experiment(exp_id)
        if not exp or exp.status not in ("hypothesis",):
            return None

        exp.status = "backtesting"
        exp.updated_at = time.time()
        self._save_experiments()

        try:
            from engines.learning.backtest_engine import BacktestEngine
            bt = BacktestEngine()
            results = bt.run(
                market=exp.market,
                strategy=exp.strategy,
                params=exp.params,
            )

            exp.backtest_metrics = {
                "sharpe": results.get("sharpe", 0),
                "win_rate": results.get("win_rate", 0),
                "max_drawdown": results.get("max_drawdown", 0),
                "profit_factor": results.get("profit_factor", 0),
                "total_return": results.get("total_return", 0),
            }
            exp.backtest_trades = results.get("n_trades", 0)
            exp.backtest_completed_at = time.time()

            # Check graduation criteria for backtest
            grad = self._config.get("graduation", _DEFAULT_GRADUATION)
            bt_pass = (
                exp.backtest_metrics.get("sharpe", 0) >= grad["min_sharpe"]
                and exp.backtest_metrics.get("win_rate", 0) >= grad["min_win_rate"]
                and exp.backtest_metrics.get("max_drawdown", 1) <= grad["max_drawdown"]
                and exp.backtest_trades >= grad["min_trades"]
            )

            if bt_pass:
                exp.status = "paper_trading"
                exp.paper_start_at = time.time()
                log.info("Experiment %s passed backtest, moving to paper trading", exp_id)
            else:
                exp.status = "hypothesis"  # back to hypothesis for param tuning
                log.info("Experiment %s failed backtest: %s", exp_id, exp.backtest_metrics)

            exp.updated_at = time.time()
            self._save_experiments()
            return exp.backtest_metrics

        except Exception as e:
            log.error("Backtest failed for %s: %s", exp_id, e)
            exp.status = "hypothesis"
            exp.updated_at = time.time()
            self._save_experiments()
            return None

    # ── Paper Trading ────────────────────────────────────────────

    def check_paper_graduation(self, exp_id: str) -> bool:
        """Check if a paper-trading experiment is ready to graduate.

        Called by the lab iterator on each tick.
        """
        exp = self.get_experiment(exp_id)
        if not exp or exp.status != "paper_trading":
            return False

        grad = self._config.get("graduation", _DEFAULT_GRADUATION)
        hours_elapsed = (time.time() - exp.paper_start_at) / 3600

        if hours_elapsed < grad.get("min_paper_hours", 24):
            return False

        # Check paper metrics
        if exp.paper_metrics.get("sharpe", 0) >= grad["min_sharpe"]:
            exp.status = "graduated"
            exp.graduation_passed = True
            exp.graduation_notes = (
                f"Passed after {hours_elapsed:.1f}h paper trading. "
                f"Sharpe={exp.paper_metrics.get('sharpe', 0):.2f}, "
                f"WR={exp.paper_metrics.get('win_rate', 0):.0%}"
            )
            exp.updated_at = time.time()
            self._save_experiments()
            log.info("Experiment %s GRADUATED: %s", exp_id, exp.graduation_notes)
            return True

        return False

    # ── Production ───────────────────────────────────────────────

    def promote_to_production(self, exp_id: str) -> bool:
        """Promote a graduated experiment to production (requires human approval)."""
        exp = self.get_experiment(exp_id)
        if not exp or exp.status != "graduated":
            return False

        exp.status = "production"
        exp.production_enabled = True
        exp.production_start_at = time.time()
        exp.frozen = True  # freeze params once in production
        exp.updated_at = time.time()
        self._save_experiments()
        log.info("Experiment %s promoted to PRODUCTION (params frozen)", exp_id)
        return True

    def retire_experiment(self, exp_id: str) -> bool:
        """Retire an experiment (any status)."""
        exp = self.get_experiment(exp_id)
        if not exp:
            return False
        exp.status = "retired"
        exp.production_enabled = False
        exp.updated_at = time.time()
        self._save_experiments()
        return True

    # ── Signal Matrix ────────────────────────────────────────────

    def get_active_signals(self, market: str) -> List[Dict[str, Any]]:
        """Get signals from all production experiments for a market.

        Multiple strategies can produce signals for the same market.
        When multiple signals align, conviction increases.
        """
        signals = []
        for exp in self._experiments:
            if exp.market != market or exp.status != "production" or not exp.production_enabled:
                continue
            signals.append({
                "experiment_id": exp.id,
                "strategy": exp.strategy,
                "params": exp.params,
                "metrics": exp.paper_metrics or exp.backtest_metrics,
                "frozen": exp.frozen,
            })
        return signals
