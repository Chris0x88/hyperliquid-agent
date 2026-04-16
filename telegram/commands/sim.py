"""/sim — shadow (paper) account state for sub-system 5.

Shows the running paper account balance, open shadow positions with
unrealized PnL, and recent closed shadow trades. Deterministic — reads
the shadow ledger JSON/JSONL files directly. No AI.

Telegram ALSO gets pushed live alerts on every shadow open/close via
the sub-system 5 iterator's ctx.alerts path; this command is the
on-demand "what's the state right now?" view.
"""
from __future__ import annotations


SHADOW_POSITIONS_JSON = "data/strategy/oil_botpattern_shadow_positions.json"
SHADOW_TRADES_JSONL = "data/strategy/oil_botpattern_shadow_trades.jsonl"
SHADOW_BALANCE_JSON = "data/strategy/oil_botpattern_shadow_balance.json"
OIL_BOTPATTERN_CONFIG_JSON = "data/config/oil_botpattern.json"


def cmd_sim(token: str, chat_id: str, args: str) -> None:
    """Show shadow (paper) account state + positions + recent trades."""
    import json
    from pathlib import Path

    from trading.oil.paper import (
        balance_from_dict,
        new_balance,
        position_from_dict,
    )
    from telegram.bot import tg_send

    def _read_json(path: str) -> dict | list | None:
        p = Path(path)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    # Config: shadow mode on/off + seed balance
    cfg = _read_json(OIL_BOTPATTERN_CONFIG_JSON) or {}
    decisions_only = bool(cfg.get("decisions_only", False))
    master_enabled = bool(cfg.get("enabled", False))
    seed = float(cfg.get("shadow_seed_balance_usd", 100_000.0))
    sl_pct = float(cfg.get("shadow_sl_pct", 2.0))
    tp_pct = float(cfg.get("shadow_tp_pct", 5.0))

    # Balance
    bal_raw = _read_json(SHADOW_BALANCE_JSON)
    if isinstance(bal_raw, dict):
        balance = balance_from_dict(bal_raw, default_seed=seed)
    else:
        balance = new_balance(seed)

    # Open positions
    pos_raw = _read_json(SHADOW_POSITIONS_JSON)
    positions: list = []
    if isinstance(pos_raw, dict):
        positions = [
            position_from_dict(p)
            for p in (pos_raw.get("positions") or [])
        ]

    # Recent trades (last 10)
    trades: list[dict] = []
    trades_path = Path(SHADOW_TRADES_JSONL)
    if trades_path.exists():
        try:
            with trades_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            trades = []

    # Render
    lines = ["🌓 *Sub-system 5 shadow (paper) account*", ""]
    if master_enabled and decisions_only:
        lines.append("*Mode:* 🟡 SHADOW (decisions_only=true, no real orders)")
    elif master_enabled and not decisions_only:
        lines.append("*Mode:* 🔴 LIVE (real orders enabled)")
    else:
        lines.append("*Mode:* ⚫ DISABLED (master kill switch OFF)")
    lines.append("")

    pnl_delta = balance.current_balance_usd - balance.seed_balance_usd
    pnl_sign = "+" if pnl_delta >= 0 else "−"
    lines.append("*Account:*")
    lines.append(f"  Seed:    ${balance.seed_balance_usd:,.0f}")
    lines.append(
        f"  Current: ${balance.current_balance_usd:,.0f}  "
        f"({pnl_sign}${abs(pnl_delta):,.0f}, {balance.pnl_pct:+.2f}%)"
    )
    lines.append(
        f"  Trades:  {balance.closed_trades} closed  "
        f"({balance.wins}W / {balance.losses}L, WR {balance.win_rate:.0%})"
    )
    lines.append(f"  SL/TP:   {sl_pct:.1f}% / {tp_pct:.1f}%")
    if balance.last_updated_at:
        lines.append(f"  Updated: {balance.last_updated_at[:19]} UTC")
    lines.append("")

    if positions:
        lines.append(f"*Open shadow positions ({len(positions)}):*")
        for p in positions:
            mark_str = ""
            if p.last_mark_price:
                unreal_sign = "+" if p.unrealized_pnl_usd >= 0 else "−"
                mark_str = (
                    f" | mark {p.last_mark_price:,.2f} "
                    f"{unreal_sign}${abs(p.unrealized_pnl_usd):,.0f}"
                )
            lines.append(
                f"  {p.side.upper()} {p.instrument} @ {p.entry_price:,.2f} "
                f"size={p.size:,.4f} lev={p.leverage}x"
            )
            lines.append(
                f"    sl={p.stop_price:,.2f} tp={p.tp_price:,.2f} "
                f"edge={p.edge:.2f}{mark_str}"
            )
        lines.append("")
    else:
        lines.append("*Open shadow positions:* none")
        lines.append("")

    if trades:
        lines.append(f"*Recent closed trades (last {min(5, len(trades))}):*")
        for t in trades[-5:][::-1]:
            side = str(t.get("side", "?")).upper()
            inst = t.get("instrument", "?")
            pnl = float(t.get("realised_pnl_usd", 0.0))
            roe = float(t.get("roe_pct", 0.0))
            reason = t.get("exit_reason", "?")
            hold = float(t.get("hold_hours", 0.0))
            emoji = "🟢" if pnl > 0 else "🔴"
            sign = "+" if pnl >= 0 else "−"
            lines.append(
                f"  {emoji} {side} {inst}  {reason}  "
                f"{sign}${abs(pnl):,.0f} ({roe:+.2f}%)  hold {hold:.1f}h"
            )
    else:
        lines.append("*Recent closed trades:* none")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)
