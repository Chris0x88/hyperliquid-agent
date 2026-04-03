"""MCP server for agent-cli — exposes trading tools via Model Context Protocol.

DESIGN PRINCIPLE: Every tool returns COMPACT, pre-rendered text.
No raw JSON arrays. No massive candle dumps. Hard character caps.
The AI gets exactly what it needs to reason — nothing more.

All tool calls are logged to data/diagnostics/tool_calls.jsonl.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Optional

from common.diagnostics import diag

# Hard cap on any tool response — prevents context blowout
_MAX_RESPONSE_CHARS = 3000


def _cap(text: str, limit: int = _MAX_RESPONSE_CHARS) -> str:
    """Hard-cap response length. Truncate with marker if over."""
    if len(text) <= limit:
        return text
    return text[:limit - 30] + "\n...(truncated to save tokens)"


def _run_hl(*args: str, timeout: int = 30) -> str:
    """Run an hl CLI command via subprocess and return stdout."""
    start = time.monotonic()
    cmd = [sys.executable, "-m", "cli.main", *args]
    tool_name = args[0] if args else "unknown"
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output = output + "\n" + result.stderr.strip() if output else result.stderr.strip()
        dur = int((time.monotonic() - start) * 1000)
        output = output or "(no output)"
        if result.returncode != 0:
            diag.log_tool_call(tool_name, args={"cmd": list(args)}, error=output[:300], duration_ms=dur)
        else:
            diag.log_tool_call(tool_name, args={"cmd": list(args)}, result=output[:200], duration_ms=dur)
        return _cap(output)
    except subprocess.TimeoutExpired:
        dur = int((time.monotonic() - start) * 1000)
        diag.log_tool_call(tool_name, args={"cmd": list(args)}, error=f"Timeout after {timeout}s", duration_ms=dur)
        return f"(timed out after {timeout}s)"
    except Exception as e:
        dur = int((time.monotonic() - start) * 1000)
        diag.log_tool_call(tool_name, args={"cmd": list(args)}, error=str(e), duration_ms=dur)
        return f"(error: {e})"


def create_mcp_server():
    """Create and configure the FastMCP server."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "hyperliquid-agent",
        instructions=(
            "HyperLiquid trading agent. Use market_context() as your PRIMARY tool — "
            "it gives you everything in one compact call. Only use other tools for "
            "specific actions (trade, log_bug) or when market_context isn't enough."
        ),
    )

    # ------------------------------------------------------------------
    # PRIMARY TOOL — start here for any trading question
    # ------------------------------------------------------------------

    @mcp.tool()
    def market_context(market: str = "xyz:BRENTOIL", budget: int = 1500) -> str:
        """Your PRIMARY tool. Returns compact market brief: price, technicals,
        position, thesis, memory — all pre-assembled and token-budgeted.

        Call this FIRST for any trading question. One call replaces 5+ other tools.

        Args:
            market: Market identifier (e.g., xyz:BRENTOIL, BTC)
            budget: Max tokens in response (default: 1500, max: 2500)
        """
        start_t = time.monotonic()
        budget = min(budget, 2500)  # hard cap
        try:
            from common.context_harness import build_thesis_context

            # Collect account state inline (scheduled_check.py has no extractable function)
            account_state = {}
            try:
                import requests as _req
                from common.account_resolver import resolve_main_wallet
                addr = resolve_main_wallet(required=True)
                url = "https://api.hyperliquid.xyz/info"

                # Native + xyz equity
                native = _req.post(url, json={"type": "clearinghouseState", "user": addr}, timeout=10).json()
                xyz = _req.post(url, json={"type": "clearinghouseState", "user": addr, "dex": "xyz"}, timeout=10).json()
                spot = _req.post(url, json={"type": "spotClearinghouseState", "user": addr}, timeout=10).json()

                native_eq = float(native.get("marginSummary", {}).get("accountValue", 0))
                xyz_eq = float(xyz.get("marginSummary", {}).get("accountValue", 0))
                spot_usdc = sum(float(b.get("total", 0)) for b in spot.get("balances", []) if b.get("coin") == "USDC")

                account_state["account"] = {
                    "total_equity": round(native_eq + xyz_eq + spot_usdc, 2),
                    "native_equity": round(native_eq, 2),
                    "xyz_equity": round(xyz_eq, 2),
                }

                # Positions
                for ap in xyz.get("assetPositions", []):
                    p = ap.get("position", ap)
                    coin = p.get("coin", "")
                    if float(p.get("szi", 0)) != 0:
                        # Get mark price from metaAndAssetCtxs
                        current_price = float(p.get("entryPx", 0))
                        try:
                            meta = _req.post(url, json={"type": "metaAndAssetCtxs", "dex": "xyz"}, timeout=10).json()
                            if isinstance(meta, list) and len(meta) >= 2:
                                universe = meta[0].get("universe", [])
                                for i, u in enumerate(universe):
                                    if coin.replace("xyz:", "") in u.get("name", ""):
                                        if i < len(meta[1]):
                                            current_price = float(meta[1][i].get("markPx", current_price))
                                        break
                        except Exception:
                            pass

                        liq = float(p.get("liquidationPx") or 0)
                        liq_dist = abs(current_price - liq) / current_price * 100 if liq > 0 and current_price > 0 else 999
                        account_state[coin] = {
                            "size": float(p["szi"]),
                            "entry": float(p["entryPx"]),
                            "current_price": current_price,
                            "upnl": round(float(p.get("unrealizedPnl", 0)), 2),
                            "liq_dist_pct": round(liq_dist, 1),
                            "leverage": float((p.get("leverage") or {}).get("value", 10)),
                        }

                # Also check native positions
                for ap in native.get("assetPositions", []):
                    p = ap.get("position", ap)
                    coin = p.get("coin", "")
                    if float(p.get("szi", 0)) != 0:
                        account_state[coin] = {
                            "size": float(p["szi"]),
                            "entry": float(p["entryPx"]),
                            "upnl": round(float(p.get("unrealizedPnl", 0)), 2),
                        }

                # Alerts
                alerts = []
                xyz_orders = _req.post(url, json={"type": "frontendOpenOrders", "user": addr, "dex": "xyz"}, timeout=10).json()
                for coin_key, pos_data in account_state.items():
                    if coin_key == "account" or not isinstance(pos_data, dict) or "size" not in pos_data:
                        continue
                    has_sl = any(o.get("orderType") == "Stop Market" and coin_key.replace("xyz:", "") in o.get("coin", "") for o in xyz_orders)
                    if not has_sl and pos_data.get("size", 0) != 0:
                        alerts.append(f"NO SL on {coin_key}")
                    if pos_data.get("liq_dist_pct", 999) < 8:
                        alerts.append(f"LOW LIQ DIST {coin_key}: {pos_data['liq_dist_pct']}%")
                account_state["alerts"] = alerts

            except Exception as e:
                account_state["account_error"] = str(e)

            # Market snapshot (technicals)
            snapshot_text = ""
            try:
                from common.market_snapshot import build_snapshot, render_snapshot
                from modules.candle_cache import CandleCache
                cache = CandleCache()
                price = 0
                # Get price from positions we just fetched
                mk = market.replace("xyz:", "")
                for key, val in account_state.items():
                    if isinstance(val, dict) and mk in key and "current_price" in val:
                        price = float(val["current_price"])
                        break
                snap = build_snapshot(market, cache, price)
                snapshot_text = render_snapshot(snap, detail="standard")
            except Exception:
                pass

            # Thesis
            thesis = None
            try:
                from common.thesis import ThesisState
                states = ThesisState.load_all("data/thesis")
                thesis_key = market.replace("xyz:", "").replace("-PERP", "").lower()
                for k, v in states.items():
                    if thesis_key in k.lower():
                        thesis = {
                            "direction": v.direction,
                            "conviction": v.conviction,
                            "effective_conviction": v.effective_conviction(),
                            "age_hours": v.age_hours(),
                            "stale": v.is_stale,
                        }
                        break
            except Exception:
                pass

            ctx = build_thesis_context(
                market=market,
                account_state=account_state,
                market_snapshot_text=snapshot_text,
                current_thesis=thesis,
                token_budget=budget,
            )

            dur = int((time.monotonic() - start_t) * 1000)
            diag.log_tool_call("market_context", args={"market": market, "budget": budget},
                             result=f"{ctx.estimated_tokens}tok {len(ctx.blocks_included)}blk",
                             duration_ms=dur)

            # Return the assembled text DIRECTLY — no JSON wrapper
            return _cap(ctx.text)
        except Exception as e:
            dur = int((time.monotonic() - start_t) * 1000)
            diag.log_tool_call("market_context", args={"market": market},
                             error=str(e), duration_ms=dur)
            return f"Error building context: {e}"

    # ------------------------------------------------------------------
    # Live data tools — compact text output
    # ------------------------------------------------------------------

    @mcp.tool()
    def account(mainnet: bool = True) -> str:
        """Get account balances and positions. Returns compact text summary.

        Args:
            mainnet: Use mainnet (default: True)
        """
        args = ["account"]
        if mainnet:
            args.append("--mainnet")
        return _run_hl(*args)

    @mcp.tool()
    def status() -> str:
        """Quick position and PnL overview. Compact text."""
        return _run_hl("status")

    # ------------------------------------------------------------------
    # Analysis tools — compact output
    # ------------------------------------------------------------------

    @mcp.tool()
    def analyze(coin: str, interval: str = "1h", days: int = 30) -> str:
        """Technical analysis: EMA, RSI, trend, volume. Returns compact summary.

        Args:
            coin: Coin symbol (e.g., BTC, BRENTOIL)
            interval: 1m, 5m, 15m, 1h, 4h, 1d
            days: Lookback days (default: 30)
        """
        import time as _time
        from modules.candle_cache import CandleCache
        from modules.data_fetcher import DataFetcher
        from modules.radar_technicals import calc_ema, calc_rsi, classify_hourly_trend, volume_ratio

        cache = CandleCache()
        end_ms = int(_time.time() * 1000)
        start_ms = end_ms - (days * 86_400_000)

        candles = cache.get_candles(coin.upper(), interval, start_ms, end_ms)
        if not candles:
            try:
                fetcher = DataFetcher(cache=cache, testnet=False)
                fetcher.backfill(coin.upper(), interval, days)
                candles = cache.get_candles(coin.upper(), interval, start_ms, end_ms)
            except Exception as e:
                return f"No data: {e}"

        if not candles:
            return "No candle data available"

        closes = [float(c.get("close", c.get("c", 0))) for c in candles if c]
        if len(closes) < 14:
            return f"Insufficient data: {len(closes)} candles (need 14+)"

        # Render as compact text, not JSON
        price = closes[-1]
        ema5 = calc_ema(closes, 5)
        ema13 = calc_ema(closes, 13)
        ema50 = calc_ema(closes, 50) if len(closes) >= 50 else None
        rsi = calc_rsi(closes, 14)
        vr = volume_ratio(candles, 5) if len(candles) > 10 else None
        try:
            trend = classify_hourly_trend(candles)
        except Exception:
            trend = "unknown"

        lines = [
            f"{coin.upper()} {interval} ({len(closes)} candles, {days}d)",
            f"Price: ${price:,.2f}",
            f"EMA5: ${ema5:,.2f} | EMA13: ${ema13:,.2f}" + (f" | EMA50: ${ema50:,.2f}" if ema50 else ""),
            f"RSI14: {rsi:.1f}" + (" OVERBOUGHT" if rsi > 70 else " OVERSOLD" if rsi < 30 else ""),
            f"Trend: {trend}",
        ]
        if vr is not None:
            lines.append(f"Volume ratio: {vr:.2f}x avg")
        return "\n".join(lines)

    @mcp.tool()
    def get_candles(coin: str, interval: str = "1h", days: int = 7) -> str:
        """Get recent candle summary. Returns OHLCV digest, NOT raw data.

        Args:
            coin: Coin symbol
            interval: 1m, 5m, 15m, 1h, 4h, 1d
            days: How many days (default: 7, max: 30)
        """
        import time as _time
        from modules.candle_cache import CandleCache
        from modules.data_fetcher import DataFetcher

        days = min(days, 30)
        cache = CandleCache()
        end_ms = int(_time.time() * 1000)
        start_ms = end_ms - (days * 86_400_000)

        candles = cache.get_candles(coin.upper(), interval, start_ms, end_ms)
        if not candles:
            try:
                fetcher = DataFetcher(cache=cache, testnet=False)
                fetcher.backfill(coin.upper(), interval, days)
                candles = cache.get_candles(coin.upper(), interval, start_ms, end_ms)
            except Exception as e:
                return f"Failed to fetch: {e}"

        if not candles:
            return "No data"

        # Return compact digest instead of raw candles
        closes = [float(c.get("close", c.get("c", 0))) for c in candles]
        highs = [float(c.get("high", c.get("h", 0))) for c in candles]
        lows = [float(c.get("low", c.get("l", 0))) for c in candles]

        lines = [
            f"{coin.upper()} {interval} — {len(candles)} candles ({days}d)",
            f"Latest: ${closes[-1]:,.2f}",
            f"High: ${max(highs):,.2f} | Low: ${min(lows):,.2f}",
            f"Range: ${max(highs) - min(lows):,.2f} ({(max(highs) - min(lows)) / closes[-1] * 100:.1f}%)",
            f"Open→Close: ${closes[0]:,.2f} → ${closes[-1]:,.2f} ({(closes[-1] - closes[0]) / closes[0] * 100:+.2f}%)",
        ]

        # Show last 10 candles as compact OHLC
        last_n = candles[-10:]
        lines.append(f"\nLast {len(last_n)} candles (O→C | H | L):")
        for c in last_n:
            o = float(c.get("open", c.get("o", 0)))
            h = float(c.get("high", c.get("h", 0)))
            l = float(c.get("low", c.get("l", 0)))
            cl = float(c.get("close", c.get("c", 0)))
            arrow = "↑" if cl >= o else "↓"
            lines.append(f"  {arrow} ${o:,.2f}→${cl:,.2f} | H${h:,.2f} L${l:,.2f}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Memory tools — compact, bounded
    # ------------------------------------------------------------------

    @mcp.tool()
    def agent_memory(query_type: str = "recent", limit: int = 10) -> str:
        """Agent memory: learnings and observations. Compact text output.

        Args:
            query_type: "recent" for latest events, "playbook" for knowledge
            limit: Max events (default: 10, max: 20)
        """
        from modules.memory_guard import MemoryGuard

        limit = min(limit, 20)
        guard = MemoryGuard()
        if query_type == "playbook":
            playbook = guard.load_playbook()
            d = playbook.to_dict()
            # Render compact
            lines = ["Playbook:"]
            for k, v in d.items():
                if isinstance(v, list):
                    lines.append(f"  {k}: {len(v)} items")
                    for item in v[:5]:
                        lines.append(f"    - {str(item)[:100]}")
                else:
                    lines.append(f"  {k}: {str(v)[:100]}")
            return _cap("\n".join(lines))
        else:
            events = guard.read_events(limit=limit)
            lines = [f"Recent events ({len(events)}):"]
            for e in events:
                d = e.to_dict()
                ts = d.get("timestamp", "?")[:16]
                etype = d.get("event_type", "?")
                title = d.get("title", d.get("description", "?"))[:80]
                lines.append(f"  [{ts}] {etype}: {title}")
            return _cap("\n".join(lines))

    @mcp.tool()
    def trade_journal(limit: int = 10) -> str:
        """Recent trade records. Compact text.

        Args:
            limit: Max entries (default: 10, max: 20)
        """
        from modules.journal_guard import JournalGuard

        limit = min(limit, 20)
        guard = JournalGuard()
        entries = guard.read_entries(limit=limit)
        if not entries:
            return "No journal entries."
        lines = [f"Trade journal ({len(entries)} entries):"]
        for e in entries:
            d = e.to_dict()
            coin = d.get("coin", "?")
            side = d.get("side", "?")
            pnl = d.get("pnl", "?")
            reason = str(d.get("reason", ""))[:60]
            lines.append(f"  {coin} {side} | PnL: {pnl} | {reason}")
        return _cap("\n".join(lines))

    # ------------------------------------------------------------------
    # Action tools — compact confirmations
    # ------------------------------------------------------------------

    @mcp.tool()
    def trade(instrument: str, side: str, size: float) -> str:
        """Place order. Returns confirmation or error.

        Args:
            instrument: e.g., ETH-PERP, BTC-PERP, xyz:BRENTOIL
            side: "buy" or "sell"
            size: Order size in contracts
        """
        return _run_hl("trade", instrument, side, str(size))

    @mcp.tool()
    def log_bug(title: str, description: str, severity: str = "medium") -> str:
        """Report a bug. Goes to data/bugs.md for Claude Code to fix.

        Args:
            title: Short bug title
            description: What's wrong
            severity: low, medium, high, critical
        """
        from pathlib import Path
        from datetime import datetime, timezone

        bugs_path = Path("data/bugs.md")
        bugs_path.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        valid = ["low", "medium", "high", "critical"]
        sev = severity.lower() if severity.lower() in valid else "medium"

        entry = f"\n## [{sev.upper()}] {title}\n- **Reported:** {now}\n- **Status:** open\n- **Description:** {description}\n"

        if not bugs_path.exists():
            bugs_path.write_text("# Bugs & Issues\n\nTracked bugs for Claude Code to investigate and fix.\n" + entry)
        else:
            with open(bugs_path, "a") as f:
                f.write(entry)

        diag.log_tool_call("log_bug", args={"title": title, "severity": sev})
        return f"Bug logged: [{sev.upper()}] {title}"

    @mcp.tool()
    def log_feedback(text: str, category: str = "general") -> str:
        """Record user feedback for self-improvement.

        Args:
            text: Feedback text
            category: response_quality, tool_usage, speed, accuracy, general
        """
        from pathlib import Path
        from datetime import datetime, timezone

        feedback_path = Path("data/feedback.jsonl")
        feedback_path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "text": text[:500],
        }
        with open(feedback_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        diag.log_tool_call("log_feedback", args={"category": category})
        return f"Feedback recorded ({category})"

    # ------------------------------------------------------------------
    # Diagnostic tools — compact
    # ------------------------------------------------------------------

    @mcp.tool()
    def diagnostic_report() -> str:
        """Debug tool. Shows recent errors and tool call stats."""
        summary = diag.get_summary()
        errors = diag.get_recent_errors(limit=3)

        lines = [
            f"Uptime: {summary['uptime_seconds']}s",
            f"Tool calls: {summary['total_tool_calls']}",
            f"Errors: {summary['total_errors']}",
        ]
        if summary['errors']:
            lines.append("Error sources:")
            for src, cnt in summary['errors'].items():
                lines.append(f"  {src}: {cnt}")
        if errors:
            lines.append("Last errors:")
            for e in errors:
                d = e.get('data', {})
                lines.append(f"  {d.get('source', d.get('tool', '?'))}: {d.get('message', d.get('error', '?'))[:80]}")
        return "\n".join(lines)

    @mcp.tool()
    def daemon_status() -> str:
        """Daemon health: tier, strategies, PnL, risk gate."""
        return _run_hl("daemon", "status")

    # ------------------------------------------------------------------
    # Rarely-used tools — still available but not primary
    # ------------------------------------------------------------------

    @mcp.tool()
    def strategies() -> str:
        """List available trading strategies. Compact summary."""
        from cli.strategy_registry import STRATEGY_REGISTRY

        lines = [f"Strategies ({len(STRATEGY_REGISTRY)}):"]
        for name, info in STRATEGY_REGISTRY.items():
            desc = info.get("description", "")[:60]
            lines.append(f"  {name}: {desc}")
        return _cap("\n".join(lines))

    @mcp.tool()
    def setup_check() -> str:
        """Validate environment — SDK, keys, network."""
        import os
        from cli.keystore import list_keystores

        issues = []
        ok = []
        try:
            import hyperliquid  # noqa: F401
            ok.append("SDK installed")
        except ImportError:
            issues.append("SDK missing")

        has_key = bool(os.environ.get("HL_PRIVATE_KEY"))
        keystores = list_keystores()
        if has_key:
            ok.append("Key: env var")
        elif keystores:
            ok.append(f"Key: keystore ({len(keystores)})")
        else:
            issues.append("No private key")

        testnet = os.environ.get("HL_TESTNET", "true").lower()
        ok.append(f"Network: {'testnet' if testnet == 'true' else 'mainnet'}")

        return ("OK: " + ", ".join(ok) + "\n" + ("Issues: " + ", ".join(issues) if issues else "No issues"))

    @mcp.tool()
    def cache_stats() -> str:
        """Show cached historical data summary."""
        from modules.candle_cache import CandleCache
        cache = CandleCache()
        stats = cache.stats()
        lines = ["Cache:"]
        for k, v in stats.items():
            lines.append(f"  {k}: {v}")
        return _cap("\n".join(lines))

    @mcp.tool()
    def run_strategy(
        strategy: str,
        instrument: str = "ETH-PERP",
        tick: int = 10,
        max_ticks: Optional[int] = None,
        mock: bool = False,
        dry_run: bool = False,
        mainnet: bool = False,
    ) -> str:
        """Start a trading strategy.

        Args:
            strategy: Strategy name
            instrument: Trading instrument
            tick: Seconds between ticks
            max_ticks: Stop after N ticks
            mock: Simulated data
            dry_run: No real orders
            mainnet: Use mainnet
        """
        args = ["run", strategy, "-i", instrument, "-t", str(tick)]
        if max_ticks is not None:
            args.extend(["--max-ticks", str(max_ticks)])
        if mock:
            args.append("--mock")
        if dry_run:
            args.append("--dry-run")
        if mainnet:
            args.append("--mainnet")
        return _run_hl(*args, timeout=max(60, (max_ticks or 10) * tick + 30))

    @mcp.tool()
    def daemon_start(tier: str = "watch", mock: bool = False, max_ticks: Optional[int] = None) -> str:
        """Start the daemon.

        Args:
            tier: watch, rebalance, or opportunistic
            mock: Simulated mode
            max_ticks: Stop after N ticks
        """
        args = ["daemon", "start", "--tier", tier]
        if mock:
            args.append("--mock")
        if max_ticks is not None:
            args.extend(["--max-ticks", str(max_ticks)])
        return _run_hl(*args, timeout=max(60, (max_ticks or 5) * 60 + 30))

    # ------------------------------------------------------------------
    # THESIS UPDATE — closes the feedback loop
    # ------------------------------------------------------------------

    @mcp.tool()
    def update_thesis(
        market: str,
        direction: str,
        conviction: float,
        summary: str,
        invalidation_note: str = "",
    ) -> str:
        """Update thesis conviction for a market. Writes to data/thesis/.

        Call this after analyzing market conditions to persist your updated view.
        The heartbeat reads thesis files every 2 minutes and adjusts execution.

        Args:
            market: Market identifier (e.g., xyz:BRENTOIL, BTC-PERP)
            direction: long, short, or neutral
            conviction: 0.0 to 1.0 (0=no conviction, 1=maximum)
            summary: Brief thesis summary (1-2 sentences)
            invalidation_note: Optional note on what would invalidate this thesis
        """
        start = time.monotonic()
        try:
            from common.thesis import ThesisState
            from pathlib import Path

            # Validate inputs
            if direction not in ("long", "short", "neutral"):
                return "Error: direction must be long, short, or neutral"
            conviction = max(0.0, min(1.0, conviction))

            # Normalize market name for filename
            fname = market.replace(":", "_").lower() + "_state.json"
            thesis_dir = Path("data/thesis")
            thesis_dir.mkdir(parents=True, exist_ok=True)
            path = thesis_dir / fname

            # Load existing or create new
            old_conviction = 0.0
            if path.exists():
                existing = json.loads(path.read_text())
                old_conviction = existing.get("conviction", 0.0)
                existing["direction"] = direction
                existing["conviction"] = conviction
                existing["thesis_summary"] = summary
                existing["last_evaluation_ts"] = int(time.time() * 1000)
                if invalidation_note:
                    conditions = existing.get("invalidation_conditions", [])
                    if invalidation_note not in conditions:
                        conditions.append(invalidation_note)
                    existing["invalidation_conditions"] = conditions
            else:
                existing = {
                    "market": market,
                    "direction": direction,
                    "conviction": conviction,
                    "thesis_summary": summary,
                    "invalidation_conditions": [invalidation_note] if invalidation_note else [],
                    "evidence_for": [],
                    "evidence_against": [],
                    "recommended_leverage": 5.0,
                    "recommended_size_pct": 0.1,
                    "weekend_leverage_cap": 3.0,
                    "allow_tactical_trades": True,
                    "tactical_notes": "",
                    "last_evaluation_ts": int(time.time() * 1000),
                    "snapshot_ref": "",
                    "notes": "",
                    "take_profit_price": 0.0,
                }

            path.write_text(json.dumps(existing, indent=2))

            dur = int((time.monotonic() - start) * 1000)
            diag.log_tool_call("update_thesis", dur, True)
            return (
                f"Thesis updated: {market}\n"
                f"  Conviction: {old_conviction:.2f} → {conviction:.2f}\n"
                f"  Direction: {direction}\n"
                f"  Summary: {summary[:100]}"
            )
        except Exception as e:
            dur = int((time.monotonic() - start) * 1000)
            diag.log_tool_call("update_thesis", dur, False, str(e))
            return f"Error updating thesis: {e}"

    # ------------------------------------------------------------------
    # LIVE PRICE — quick price check without heavy context
    # ------------------------------------------------------------------

    @mcp.tool()
    def live_price(markets: str = "all") -> str:
        """Get current prices. Lightweight — use instead of market_context for quick checks.

        Args:
            markets: Comma-separated markets (e.g., "BTC,xyz:BRENTOIL") or "all" for watchlist
        """
        start = time.monotonic()
        try:
            import requests as _req

            prices = {}

            # Default clearinghouse (BTC, ETH, etc.)
            resp = _req.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "allMids"},
                timeout=10,
            )
            if resp.status_code == 200:
                mids = resp.json()
                for coin, mid in mids.items():
                    prices[coin] = float(mid)

            time.sleep(0.3)

            # XYZ clearinghouse (BRENTOIL, GOLD, SILVER, etc.)
            resp = _req.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "allMids", "dex": "xyz"},
                timeout=10,
            )
            if resp.status_code == 200:
                xyz_mids = resp.json()
                for coin, mid in xyz_mids.items():
                    # API already returns keys like "xyz:BRENTOIL" — don't double-prefix
                    prices[coin] = float(mid)

            if not prices:
                return "Error: could not fetch prices from HL API"

            # Filter to requested markets
            if markets != "all":
                requested = [m.strip() for m in markets.split(",")]
                filtered = {}
                for req in requested:
                    # Try exact match first, then case-insensitive
                    if req in prices:
                        filtered[req] = prices[req]
                    else:
                        for k, v in prices.items():
                            if k.lower() == req.lower() or k.lower().endswith(req.lower()):
                                filtered[k] = v
                                break
                prices = filtered

            # Format compactly
            from common.watchlist import get_watchlist_coins
            watchlist = get_watchlist_coins()
            if markets == "all":
                # Show watchlist only, not all 200+ markets
                prices = {k: v for k, v in prices.items() if k in watchlist}

            lines = []
            for coin, mid in sorted(prices.items()):
                if mid >= 1000:
                    lines.append(f"{coin}: ${mid:,.0f}")
                elif mid >= 1:
                    lines.append(f"{coin}: ${mid:,.2f}")
                else:
                    lines.append(f"{coin}: ${mid:.6f}")

            dur = int((time.monotonic() - start) * 1000)
            diag.log_tool_call("live_price", dur, True)
            return " | ".join(lines) if lines else "No matching markets found"
        except Exception as e:
            dur = int((time.monotonic() - start) * 1000)
            diag.log_tool_call("live_price", dur, False, str(e))
            return f"Error fetching prices: {e}"

    return mcp
