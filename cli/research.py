"""Per-market research project system.

Each market we trade gets its own living research project:
  data/research/markets/{coin}/
    README.md       — thesis, conviction level, current strategy
    trades.jsonl    — trade history (entries, exits, outcomes, lessons)
    signals.jsonl   — signal log (indicators, triggers, actions taken)
    charts/         — generated chart images
    algorithms/     — strategy code experiments, backtest results
    notes/          — dated analysis notes

Usage:
    from cli.research import MarketProject
    project = MarketProject("brentoil")
    project.log_signal({"rsi": 70.4, "trend": "bullish", ...})
    project.log_trade({"entry": 105.50, "size": 31.43, ...})
    project.add_note("Hormuz deadline approaching — stay long")
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


RESEARCH_ROOT = Path("data/research/markets")


class MarketProject:
    """Manages a per-market research project."""

    def __init__(self, coin: str):
        self.coin = coin.lower().replace(":", "_")  # xyz:BRENTOIL -> xyz_brentoil
        self.display_name = coin
        self.root = RESEARCH_ROOT / self.coin
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for subdir in ["charts", "algorithms", "notes"]:
            (self.root / subdir).mkdir(parents=True, exist_ok=True)

    # ── README (thesis) ──────────────────────────────────────

    @property
    def readme_path(self) -> Path:
        return self.root / "README.md"

    def get_thesis(self) -> Optional[str]:
        if self.readme_path.exists():
            return self.readme_path.read_text()
        return None

    def set_thesis(self, content: str) -> None:
        self.readme_path.write_text(content)

    # ── Trade log ────────────────────────────────────────────

    @property
    def trades_path(self) -> Path:
        return self.root / "trades.jsonl"

    def log_trade(self, trade: Dict[str, Any]) -> None:
        trade.setdefault("timestamp", int(time.time()))
        trade.setdefault("coin", self.display_name)
        with open(self.trades_path, "a") as f:
            f.write(json.dumps(trade) + "\n")

    def get_trades(self, limit: int = 50) -> List[Dict]:
        if not self.trades_path.exists():
            return []
        lines = self.trades_path.read_text().splitlines()
        trades = []
        for line in lines[-limit:]:
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return trades

    def get_trade_stats(self) -> Dict:
        trades = self.get_trades(limit=1000)
        if not trades:
            return {"total": 0}
        closed = [t for t in trades if t.get("pnl") is not None]
        wins = [t for t in closed if float(t.get("pnl", 0)) > 0]
        losses = [t for t in closed if float(t.get("pnl", 0)) < 0]
        total_pnl = sum(float(t.get("pnl", 0)) for t in closed)
        return {
            "total": len(trades),
            "closed": len(closed),
            "open": len(trades) - len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) if closed else 0,
            "total_pnl": total_pnl,
        }

    # ── Signal log ───────────────────────────────────────────

    @property
    def signals_path(self) -> Path:
        return self.root / "signals.jsonl"

    def log_signal(self, signal: Dict[str, Any]) -> None:
        signal.setdefault("timestamp", int(time.time()))
        signal.setdefault("coin", self.display_name)
        with open(self.signals_path, "a") as f:
            f.write(json.dumps(signal) + "\n")

    def get_signals(self, limit: int = 100) -> List[Dict]:
        if not self.signals_path.exists():
            return []
        lines = self.signals_path.read_text().splitlines()
        return [json.loads(l) for l in lines[-limit:] if l.strip()]

    # ── Notes ────────────────────────────────────────────────

    def add_note(self, content: str, title: Optional[str] = None) -> Path:
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        if title:
            slug = title.lower().replace(" ", "-")[:40]
            filename = f"{date_str}-{slug}.md"
        else:
            filename = f"{date_str}-{now.strftime('%H%M')}.md"

        path = self.root / "notes" / filename
        header = f"# {title or 'Analysis'} — {date_str}\n\n"
        path.write_text(header + content + "\n")
        return path

    def get_notes(self) -> List[Path]:
        notes_dir = self.root / "notes"
        if not notes_dir.exists():
            return []
        return sorted(notes_dir.glob("*.md"), reverse=True)

    # ── Charts ───────────────────────────────────────────────

    def chart_path(self, name: str) -> Path:
        return self.root / "charts" / name

    def list_charts(self) -> List[Path]:
        charts_dir = self.root / "charts"
        if not charts_dir.exists():
            return []
        return sorted(charts_dir.glob("*.png"), reverse=True)

    # ── Algorithms ───────────────────────────────────────────

    def save_algorithm(self, name: str, content: str) -> Path:
        path = self.root / "algorithms" / f"{name}.py"
        path.write_text(content)
        return path

    def list_algorithms(self) -> List[Path]:
        alg_dir = self.root / "algorithms"
        if not alg_dir.exists():
            return []
        return sorted(alg_dir.glob("*.py"))

    # ── Summary ──────────────────────────────────────────────

    def summary(self) -> str:
        stats = self.get_trade_stats()
        signals = self.get_signals(limit=5)
        notes = self.get_notes()[:3]
        charts = self.list_charts()[:3]

        lines = [f"Project: {self.display_name}", ""]

        if self.get_thesis():
            # First line of thesis
            first_line = self.get_thesis().split("\n")[0].strip("# ")
            lines.append(f"Thesis: {first_line}")

        lines.append(f"Trades: {stats['total']} ({stats.get('open', 0)} open, "
                     f"{stats.get('wins', 0)}W/{stats.get('losses', 0)}L)")
        if stats.get("total_pnl"):
            lines.append(f"Total PnL: ${stats['total_pnl']:+,.2f}")
        lines.append(f"Signals: {len(self.get_signals())} logged")
        lines.append(f"Notes: {len(self.get_notes())} | Charts: {len(self.list_charts())}")

        return "\n".join(lines)


def list_projects() -> List[MarketProject]:
    """List all market projects."""
    if not RESEARCH_ROOT.exists():
        return []
    return [
        MarketProject(d.name.replace("_", ":"))
        for d in sorted(RESEARCH_ROOT.iterdir())
        if d.is_dir()
    ]


def get_or_create_project(coin: str) -> MarketProject:
    """Get or create a market research project."""
    return MarketProject(coin)
