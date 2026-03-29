#!/usr/bin/env python3
"""Daily Report — 1-page PDF sent to Telegram at 7AM and 7PM AEST.

Generates portfolio snapshot, BRENTOIL chart, key metrics, catalyst calendar.
"""
from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [report] %(message)s")
log = logging.getLogger("daily_report")

HL_API = "https://api.hyperliquid.xyz/info"
ADDR = "0x80B5801ce295C4D469F4C0C2e7E17bd84dF0F205"
VAULT = "0x9da9a9aef5a968277b5ea66c6a0df7add49d98da"
REPORT_DIR = Path("data/reports")


def _hl(payload: dict) -> dict:
    try:
        return requests.post(HL_API, json=payload, timeout=10).json()
    except:
        return {}


def _keychain(key: str) -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", "hl-agent-telegram", "-a", key, "-w"],
        capture_output=True, text=True, timeout=5,
    )
    return r.stdout.strip()


def _liquidity_regime() -> str:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5 and (now.hour >= 22 or now.hour < 6):
        return "DANGEROUS"
    elif now.weekday() >= 5:
        return "WEEKEND"
    elif now.hour >= 22 or now.hour < 6:
        return "LOW"
    return "NORMAL"


def generate_report() -> Path:
    """Generate the daily report PDF."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    now = datetime.now(timezone.utc)
    aest = now + timedelta(hours=10)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = REPORT_DIR / f"report_{aest.strftime('%Y%m%d_%H%M')}.pdf"

    # Gather data
    spot = _hl({"type": "spotClearinghouseState", "user": ADDR})
    xyz_state = _hl({"type": "clearinghouseState", "user": ADDR, "dex": "xyz"})
    native_state = _hl({"type": "clearinghouseState", "user": ADDR})
    vault_state = _hl({"type": "clearinghouseState", "user": VAULT})
    xyz_orders = _hl({"type": "openOrders", "user": ADDR, "dex": "xyz"})
    native_orders = _hl({"type": "openOrders", "user": ADDR})

    # BRENTOIL price + candles
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (72 * 3600 * 1000)
    candles = _hl({
        "type": "candleSnapshot",
        "req": {"coin": "xyz:BRENTOIL", "interval": "1h",
                "startTime": start_ms, "endTime": end_ms}
    })

    closes = [float(c["c"]) for c in candles] if candles else []
    current_price = closes[-1] if closes else 0

    # EMAs
    def ema(vals, span):
        if not vals or len(vals) < span:
            return vals[:]
        a = 2 / (span + 1)
        r = [vals[0]]
        for v in vals[1:]:
            r.append(a * v + (1 - a) * r[-1])
        return r

    ema9 = ema(closes, 9)[-1] if len(closes) >= 9 else 0
    ema21 = ema(closes, 21)[-1] if len(closes) >= 21 else 0

    # RSI
    rsi = 50
    if len(closes) > 14:
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i - 1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        ag = sum(gains[-14:]) / 14
        al = sum(losses[-14:]) / 14
        rs = ag / al if al > 0 else 100
        rsi = 100 - (100 / (1 + rs))

    # Extract position data
    xyz_positions = xyz_state.get("assetPositions", [])
    vault_positions = vault_state.get("assetPositions", [])
    xyz_val = float(xyz_state.get("marginSummary", {}).get("accountValue", 0))
    vault_val = float(vault_state.get("marginSummary", {}).get("accountValue", 0))

    # Spot balances
    usdc = 0
    for b in spot.get("balances", []):
        if b["coin"] == "USDC":
            usdc = float(b.get("total", 0))

    # Build PDF
    with PdfPages(pdf_path) as pdf:
        fig = plt.figure(figsize=(8.5, 11))
        fig.patch.set_facecolor("#0d1117")

        # Title
        fig.text(0.5, 0.96, "HyperLiquid Trading Report",
                 ha="center", fontsize=16, fontweight="bold", color="#c9d1d9")
        fig.text(0.5, 0.935, aest.strftime("%A %d %B %Y, %I:%M %p AEST"),
                 ha="center", fontsize=10, color="#8b949e")

        # Portfolio Summary
        y = 0.89
        fig.text(0.05, y, "PORTFOLIO", fontsize=12, fontweight="bold", color="#58a6ff")
        y -= 0.025
        fig.text(0.05, y, f"Spot USDC: ${usdc:,.2f}", fontsize=10, color="#c9d1d9")
        fig.text(0.5, y, f"Perps equity: ${xyz_val:,.2f}", fontsize=10, color="#c9d1d9")
        y -= 0.02
        fig.text(0.05, y, f"Vault equity: ${vault_val:,.2f}", fontsize=10, color="#c9d1d9")
        total = usdc + xyz_val + vault_val
        fig.text(0.5, y, f"TOTAL: ${total:,.2f}", fontsize=10, fontweight="bold", color="#3fb950")

        # Positions
        y -= 0.04
        fig.text(0.05, y, "POSITIONS", fontsize=12, fontweight="bold", color="#58a6ff")
        for p in xyz_positions:
            pos = p["position"]
            y -= 0.025
            lev = pos.get("leverage", {})
            lev_v = lev.get("value", "?") if isinstance(lev, dict) else lev
            fig.text(0.05, y,
                     f"{pos['coin']}: {pos['szi']} @ ${pos['entryPx']} | "
                     f"uPnL: ${pos['unrealizedPnl']} | {lev_v}x | liq: ${pos.get('liquidationPx', 'N/A')}",
                     fontsize=9, color="#c9d1d9", family="monospace")
        for p in vault_positions:
            pos = p["position"]
            y -= 0.025
            fig.text(0.05, y,
                     f"[VAULT] {pos['coin']}: {pos['szi']} @ ${pos['entryPx']} | uPnL: ${pos['unrealizedPnl']}",
                     fontsize=9, color="#8b949e", family="monospace")

        # Orders
        all_orders = (xyz_orders or []) + (native_orders or [])
        if all_orders:
            y -= 0.035
            fig.text(0.05, y, f"ORDERS ({len(all_orders)})", fontsize=12, fontweight="bold", color="#58a6ff")
            for o in all_orders[:3]:
                y -= 0.025
                side = "BUY" if o.get("side") == "B" else "SELL"
                fig.text(0.05, y, f"  {side} {o.get('sz')} {o.get('coin')} @ ${o.get('limitPx')}",
                         fontsize=9, color="#c9d1d9", family="monospace")

        # Market Metrics
        y -= 0.04
        fig.text(0.05, y, "MARKET", fontsize=12, fontweight="bold", color="#58a6ff")
        y -= 0.025
        fig.text(0.05, y, f"BRENTOIL: ${current_price:.2f}", fontsize=10, color="#c9d1d9")
        fig.text(0.35, y, f"EMA9: ${ema9:.2f}", fontsize=9, color="#58a6ff")
        fig.text(0.55, y, f"EMA21: ${ema21:.2f}", fontsize=9, color="#d2a8ff")
        fig.text(0.75, y, f"RSI: {rsi:.0f}", fontsize=9,
                 color="#f85149" if rsi > 70 else "#3fb950" if rsi < 30 else "#c9d1d9")
        y -= 0.02
        fig.text(0.05, y, f"Liquidity: {_liquidity_regime()}", fontsize=9, color="#8b949e")
        trend = "BULLISH" if ema9 > ema21 else "BEARISH"
        fig.text(0.35, y, f"Trend: {trend}", fontsize=9,
                 color="#3fb950" if trend == "BULLISH" else "#f85149")

        # Catalyst Calendar
        y -= 0.04
        fig.text(0.05, y, "CATALYSTS", fontsize=12, fontweight="bold", color="#58a6ff")
        catalysts = [
            ("Apr 6", "Trump deadline for Iran — escalation or extension"),
            ("Apr 7-13", "BRENTOIL contract roll BZM6→BZN6 ($25 backwardation)"),
            ("Weekly", "EIA petroleum inventory report (Wednesday)"),
            ("Late Apr", "Possible partial Hormuz military reopening"),
            ("Jul-Aug", "SPR exhaustion if not replenished"),
        ]
        for date, desc in catalysts:
            y -= 0.022
            fig.text(0.05, y, f"  {date}:", fontsize=9, fontweight="bold", color="#f0883e")
            fig.text(0.2, y, desc, fontsize=8, color="#c9d1d9")

        # Thesis
        y -= 0.04
        fig.text(0.05, y, "THESIS: STRONG LONG", fontsize=12, fontweight="bold", color="#3fb950")
        y -= 0.022
        fig.text(0.05, y, "10M bpd gap unfillable. Physical > paper. Druckenmiller-grade conviction.",
                 fontsize=9, color="#c9d1d9")

        # Chart (bottom half)
        if candles:
            ax = fig.add_axes([0.08, 0.05, 0.87, 0.35])
            ax.set_facecolor("#0d1117")
            times = list(range(len(closes)))
            ema9_series = ema(closes, 9)
            ema21_series = ema(closes, 21)

            ax.plot(times, closes, color="#06b6d4", linewidth=1.5, label="Price")
            if len(ema9_series) == len(times):
                ax.plot(times, ema9_series, color="#58a6ff", linewidth=0.8, label="EMA9")
            if len(ema21_series) == len(times):
                ax.plot(times, ema21_series, color="#d2a8ff", linewidth=0.8, label="EMA21")

            ax.set_title("BRENTOIL 72h", color="#c9d1d9", fontsize=10)
            ax.tick_params(colors="#8b949e", labelsize=7)
            ax.spines["bottom"].set_color("#30363d")
            ax.spines["left"].set_color("#30363d")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:.0f}"))
            ax.legend(loc="upper left", fontsize=7, facecolor="#161b22",
                     edgecolor="#30363d", labelcolor="#c9d1d9")

            # Pad y axis
            pad = (max(closes) - min(closes)) * 0.08
            ax.set_ylim(min(closes) - pad, max(closes) + pad)

        pdf.savefig(fig, facecolor=fig.get_facecolor())
        plt.close(fig)

    log.info("Report saved: %s", pdf_path)
    return pdf_path


def send_report(pdf_path: Path):
    """Send PDF to Telegram."""
    token = _keychain("bot_token")
    chat_id = _keychain("chat_id")
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    now_aest = datetime.now(timezone.utc) + timedelta(hours=10)
    period = "Morning" if now_aest.hour < 12 else "Evening"

    with open(pdf_path, "rb") as f:
        resp = requests.post(url,
            data={"chat_id": chat_id, "caption": f"{period} Report — {now_aest.strftime('%d %b %Y')}"},
            files={"document": (pdf_path.name, f, "application/pdf")},
            timeout=30)
    if resp.json().get("ok"):
        log.info("Report sent to Telegram")
    else:
        log.error("Failed to send: %s", resp.json())


def main():
    os.chdir(PROJECT_ROOT)
    path = generate_report()
    send_report(path)


if __name__ == "__main__":
    main()
