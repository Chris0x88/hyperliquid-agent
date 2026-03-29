"""Chart engine — generates trading charts and sends to Telegram.

Renders charts as PNG images using matplotlib. Designed for:
  1. Claude: raw data analysis (numbers)
  2. User: visual charts sent to Telegram
  3. Research: saved to per-market project folders

Chart types:
  - price_action: Candlestick/line with EMAs, volume, RSI
  - power_law: BTC Power Law floor/ceiling with current price
  - market_overview: Multi-market dashboard

Usage:
    from cli.chart_engine import ChartEngine
    engine = ChartEngine()
    path = engine.price_action("xyz:BRENTOIL", hours=72)
    engine.send_to_telegram(path)
"""
from __future__ import annotations

import io
import json
import logging
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import requests

log = logging.getLogger("chart_engine")

HL_API = "https://api.hyperliquid.xyz/info"


def _hl_post(payload: dict) -> dict:
    try:
        return requests.post(HL_API, json=payload, timeout=15).json()
    except Exception:
        return {}


def _keychain_read(key_name: str) -> Optional[str]:
    try:
        r = subprocess.run(
            ["security", "find-generic-password",
             "-s", "hl-agent-telegram", "-a", key_name, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


class ChartEngine:
    """Generates charts and optionally sends to Telegram."""

    def __init__(self, output_dir: str = "data/research/markets"):
        self._output_dir = Path(output_dir)

    def price_action(
        self,
        coin: str,
        hours: int = 72,
        show_emas: bool = True,
        show_volume: bool = True,
        show_rsi: bool = True,
        title: Optional[str] = None,
    ) -> Path:
        """Generate a price action chart with indicators."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime as dt

        # Fetch candle data
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (hours * 3600 * 1000)
        candles = _hl_post({
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": "1h", "startTime": start_ms, "endTime": end_ms},
        })
        if not candles:
            raise ValueError(f"No candle data for {coin}")

        times = [dt.fromtimestamp(c["t"] / 1000, tz=timezone.utc) for c in candles]
        opens = [float(c["o"]) for c in candles]
        highs = [float(c["h"]) for c in candles]
        lows = [float(c["l"]) for c in candles]
        closes = [float(c["c"]) for c in candles]
        volumes = [float(c["v"]) for c in candles]

        # Calculate indicators
        ema9 = self._ema(closes, 9)
        ema21 = self._ema(closes, 21)
        ema50 = self._ema(closes, 50)
        rsi = self._rsi(closes, 14)

        # Setup figure
        n_panels = 1 + (1 if show_volume else 0) + (1 if show_rsi else 0)
        heights = [3] + ([1] if show_volume else []) + ([1] if show_rsi else [])
        fig, axes = plt.subplots(n_panels, 1, figsize=(14, 3 * n_panels),
                                  gridspec_kw={"height_ratios": heights},
                                  sharex=True)
        if n_panels == 1:
            axes = [axes]

        fig.patch.set_facecolor("#0d1117")
        for ax in axes:
            ax.set_facecolor("#0d1117")
            ax.tick_params(colors="#8b949e")
            ax.spines["bottom"].set_color("#30363d")
            ax.spines["left"].set_color("#30363d")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

        # Price panel
        ax_price = axes[0]

        # Y-axis padding — 5% margin above highs and below lows
        price_min = min(lows)
        price_max = max(highs)
        price_range = price_max - price_min
        pad = price_range * 0.08  # 8% padding
        ax_price.set_ylim(price_min - pad, price_max + pad)

        # Candlestick as colored bars
        for i in range(len(times)):
            color = "#3fb950" if closes[i] >= opens[i] else "#f85149"
            ax_price.plot([times[i], times[i]], [lows[i], highs[i]],
                         color=color, linewidth=0.8)
            ax_price.plot([times[i], times[i]],
                         [min(opens[i], closes[i]), max(opens[i], closes[i])],
                         color=color, linewidth=2.5)

        if show_emas and len(closes) >= 50:
            ax_price.plot(times, ema9, color="#58a6ff", linewidth=1, alpha=0.8, label="EMA 9")
            ax_price.plot(times, ema21, color="#d2a8ff", linewidth=1, alpha=0.8, label="EMA 21")
            ax_price.plot(times, ema50, color="#f0883e", linewidth=1, alpha=0.8, label="EMA 50")
            ax_price.legend(loc="upper left", fontsize=8,
                           facecolor="#161b22", edgecolor="#30363d", labelcolor="#c9d1d9")

        chart_title = title or f"{coin} — {hours}h"
        ax_price.set_title(chart_title, color="#c9d1d9", fontsize=14, fontweight="bold", pad=10)
        ax_price.set_ylabel("Price ($)", color="#8b949e", fontsize=10)
        ax_price.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.2f}"))

        # Current price annotation
        last_price = closes[-1]
        ax_price.axhline(y=last_price, color="#58a6ff", linestyle="--", linewidth=0.5, alpha=0.5)
        ax_price.annotate(f"${last_price:,.2f}", xy=(times[-1], last_price),
                         fontsize=9, color="#58a6ff",
                         bbox=dict(boxstyle="round,pad=0.3", facecolor="#161b22", edgecolor="#58a6ff"))

        panel_idx = 1

        # Volume panel
        if show_volume:
            ax_vol = axes[panel_idx]
            colors = ["#3fb95066" if closes[i] >= opens[i] else "#f8514966"
                     for i in range(len(volumes))]
            ax_vol.bar(times, volumes, width=0.03, color=colors)
            ax_vol.set_ylabel("Vol", color="#8b949e", fontsize=9)
            panel_idx += 1

        # RSI panel
        if show_rsi and len(rsi) == len(times):
            ax_rsi = axes[panel_idx]
            ax_rsi.plot(times, rsi, color="#58a6ff", linewidth=1)
            ax_rsi.axhline(y=70, color="#f85149", linestyle="--", linewidth=0.5, alpha=0.5)
            ax_rsi.axhline(y=30, color="#3fb950", linestyle="--", linewidth=0.5, alpha=0.5)
            ax_rsi.fill_between(times, 30, 70, alpha=0.05, color="#8b949e")
            ax_rsi.set_ylabel("RSI", color="#8b949e", fontsize=9)
            ax_rsi.set_ylim(10, 90)

        # X-axis formatting
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        axes[-1].tick_params(axis="x", rotation=30)

        plt.tight_layout()

        # Save
        coin_slug = coin.lower().replace(":", "_")
        chart_dir = self._output_dir / coin_slug / "charts"
        chart_dir.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        path = chart_dir / f"price_{now_str}.png"
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)

        log.info("Chart saved: %s", path)
        return path

    def send_to_telegram(self, image_path: Path, caption: Optional[str] = None) -> bool:
        """Send a chart image to Telegram."""
        token = _keychain_read("bot_token")
        chat_id = _keychain_read("chat_id")
        if not token or not chat_id:
            log.warning("Telegram not configured")
            return False

        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        try:
            with open(image_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption[:1024]  # Telegram limit
                resp = requests.post(url, data=data, files=files, timeout=30)
                return resp.json().get("ok", False)
        except Exception as e:
            log.warning("Telegram photo send failed: %s", e)
            return False

    @staticmethod
    def _ema(values: List[float], span: int) -> List[float]:
        """Calculate EMA series."""
        if len(values) < span:
            return values[:]
        alpha = 2.0 / (span + 1)
        result = [values[0]]
        for v in values[1:]:
            result.append(alpha * v + (1 - alpha) * result[-1])
        return result

    @staticmethod
    def _rsi(values: List[float], period: int = 14) -> List[float]:
        """Calculate RSI series."""
        if len(values) < period + 1:
            return [50.0] * len(values)
        result = [50.0] * period  # pad
        gains = []
        losses = []
        for i in range(1, len(values)):
            delta = values[i] - values[i - 1]
            gains.append(max(delta, 0))
            losses.append(max(-delta, 0))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            result.append(100 - (100 / (1 + rs)))

        return result
