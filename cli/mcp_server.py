"""MCP server for agent-cli — exposes trading tools via Model Context Protocol.

Fast tools (account, strategies, wallet, setup) call Python directly.
Long-running tools (run_strategy, apex_run, radar, reflect) use subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Optional


def _run_hl(*args: str, timeout: int = 30) -> str:
    """Run an hl CLI command via subprocess and return stdout."""
    cmd = [sys.executable, "-m", "cli.main", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    output = result.stdout.strip()
    if result.returncode != 0 and result.stderr:
        output = output + "\n" + result.stderr.strip() if output else result.stderr.strip()
    return output or "(no output)"


def create_mcp_server():
    """Create and configure the FastMCP server."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("hyperliquid-agent", instructions="Autonomous Hyperliquid trading daemon — 22 strategies, tiered daemon (watch/rebalance/opportunistic), historical data, backtesting.")

    # ------------------------------------------------------------------
    # Fast tools — call Python directly (no subprocess overhead)
    # ------------------------------------------------------------------

    @mcp.tool()
    def strategies() -> str:
        """List all available trading strategies with descriptions and default parameters."""
        from cli.strategy_registry import STRATEGY_REGISTRY, YEX_MARKETS

        result = {"strategies": {}, "yex_markets": {}}
        for name, info in STRATEGY_REGISTRY.items():
            result["strategies"][name] = {
                "description": info.get("description", ""),
                "type": info.get("type", ""),
                "params": {k: v for k, v in info.get("params", {}).items()},
            }
        for name, info in YEX_MARKETS.items():
            result["yex_markets"][name] = {
                "hl_coin": info.get("hl_coin", ""),
                "description": info.get("description", ""),
            }
        return json.dumps(result, indent=2)

    @mcp.tool()
    def wallet_list() -> str:
        """List saved encrypted keystores."""
        from cli.keystore import list_keystores

        keystores = list_keystores()
        return json.dumps(keystores, indent=2) if keystores else "No keystores found."

    @mcp.tool()
    def wallet_auto(save_env: bool = True) -> str:
        """Create a new wallet non-interactively (agent-friendly).

        Args:
            save_env: Save credentials to ~/.hl-agent/env for auto-detection (default: True)
        """
        import secrets
        from pathlib import Path
        from eth_account import Account
        from cli.keystore import create_keystore

        password = secrets.token_urlsafe(32)
        account = Account.create()
        ks_path = create_keystore(account.key.hex(), password)

        result = {
            "address": account.address,
            "password": password,
            "keystore": str(ks_path),
        }

        if save_env:
            env_path = Path.home() / ".hl-agent" / "env"
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text(f"HL_KEYSTORE_PASSWORD={password}\n")
            env_path.chmod(0o600)
            result["env_file"] = str(env_path)

        return json.dumps(result, indent=2)

    @mcp.tool()
    def setup_check() -> str:
        """Validate environment — SDK, keys, network."""
        import os
        from cli.keystore import list_keystores
        from cli.config import TradingConfig

        issues = []
        ok_items = []

        # SDK
        try:
            import hyperliquid  # noqa: F401
            ok_items.append("hyperliquid-python-sdk installed")
        except ImportError:
            issues.append("hyperliquid-python-sdk not installed")

        # Key
        has_env_key = bool(os.environ.get("HL_PRIVATE_KEY"))
        keystores = list_keystores()
        if has_env_key:
            ok_items.append("HL_PRIVATE_KEY set")
        elif keystores:
            ok_items.append(f"Keystore found ({len(keystores)} keys)")
        else:
            issues.append("No private key: set HL_PRIVATE_KEY or run wallet_auto")

        # Network
        testnet = os.environ.get("HL_TESTNET", "true").lower()
        ok_items.append(f"Network: {'testnet' if testnet == 'true' else 'mainnet'}")

        return json.dumps({
            "ok": ok_items,
            "issues": issues,
            "passed": len(issues) == 0,
        }, indent=2)

    @mcp.tool()
    def account(mainnet: bool = False) -> str:
        """Get Hyperliquid account state (balances, positions)."""
        # Account requires live HL connection — use subprocess for isolation
        args = ["account"]
        if mainnet:
            args.append("--mainnet")
        return _run_hl(*args)

    @mcp.tool()
    def status() -> str:
        """Show current positions, PnL, and risk state."""
        return _run_hl("status")

    # ------------------------------------------------------------------
    # Action tools — subprocess (side effects, long-running)
    # ------------------------------------------------------------------

    @mcp.tool()
    def trade(instrument: str, side: str, size: float) -> str:
        """Place a single manual order.

        Args:
            instrument: Trading pair (e.g., ETH-PERP, BTC-PERP, VXX-USDYP)
            side: Order side — "buy" or "sell"
            size: Order size in contracts
        """
        return _run_hl("trade", instrument, side, str(size))

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
        """Start autonomous trading with a strategy.

        Args:
            strategy: Strategy name (e.g., engine_mm, avellaneda_mm, momentum_breakout)
            instrument: Trading instrument (default: ETH-PERP)
            tick: Seconds between ticks (default: 10)
            max_ticks: Stop after N ticks (None = run forever)
            mock: Use mock data instead of real API
            dry_run: Log decisions without placing orders
            mainnet: Use mainnet instead of testnet
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
    def radar_run(mock: bool = False) -> str:
        """Run opportunity radar — screen HL perps for trading setups."""
        args = ["radar", "once"]
        if mock:
            args.append("--mock")
        return _run_hl(*args, timeout=60)

    @mcp.tool()
    def apex_status() -> str:
        """Get APEX orchestrator status (slots, positions, daily PnL)."""
        return _run_hl("apex", "status")

    @mcp.tool()
    def apex_run(
        mock: bool = False,
        max_ticks: Optional[int] = None,
        preset: str = "default",
        mainnet: bool = False,
    ) -> str:
        """Start APEX multi-slot orchestrator.

        Args:
            mock: Use mock data
            max_ticks: Stop after N ticks
            preset: Strategy preset (default, conservative, aggressive)
            mainnet: Use mainnet
        """
        args = ["apex", "run", "--preset", preset]
        if mock:
            args.append("--mock")
        if max_ticks is not None:
            args.extend(["--max-ticks", str(max_ticks)])
        if mainnet:
            args.append("--mainnet")
        return _run_hl(*args, timeout=max(120, (max_ticks or 10) * 60 + 30))

    @mcp.tool()
    def reflect_run(since: Optional[str] = None) -> str:
        """Run REFLECT performance review — analyze trades and generate report.

        Args:
            since: Start date for analysis (YYYY-MM-DD). Default: since last report.
        """
        args = ["reflect", "run"]
        if since:
            args.extend(["--since", since])
        return _run_hl(*args)

    # ------------------------------------------------------------------
    # Self-improvement tools — memory, journal, judge, obsidian
    # ------------------------------------------------------------------

    @mcp.tool()
    def agent_memory(query_type: str = "recent", limit: int = 20, event_type: Optional[str] = None) -> str:
        """Read agent memory — learnings, param changes, market observations.

        Args:
            query_type: "recent" for latest events, "playbook" for accumulated knowledge
            limit: Max events to return (default 20)
            event_type: Filter by type (param_change, reflect_review, notable_trade, judge_finding, session_start, session_end)
        """
        from modules.memory_guard import MemoryGuard

        guard = MemoryGuard()
        if query_type == "playbook":
            playbook = guard.load_playbook()
            return json.dumps(playbook.to_dict(), indent=2)
        else:
            events = guard.read_events(limit=limit, event_type=event_type)
            return json.dumps([e.to_dict() for e in events], indent=2)

    @mcp.tool()
    def trade_journal(date: Optional[str] = None, limit: int = 20) -> str:
        """Read trade journal — structured position records with entry/exit reasoning.

        Args:
            date: Filter by date (YYYY-MM-DD). Default: all dates.
            limit: Max entries to return (default 20)
        """
        from modules.journal_guard import JournalGuard

        guard = JournalGuard()
        entries = guard.read_entries(date=date, limit=limit)
        return json.dumps([e.to_dict() for e in entries], indent=2)

    @mcp.tool()
    def judge_report() -> str:
        """Get latest Judge evaluation — signal quality, false positive rates, recommendations."""
        from modules.judge_guard import JudgeGuard

        guard = JudgeGuard()
        report = guard.read_latest_report()
        if not report:
            return json.dumps({"status": "no_reports", "message": "No judge reports yet. Run APEX to generate."})
        return json.dumps(report.to_dict(), indent=2)

    @mcp.tool()
    def obsidian_context() -> str:
        """Read trading context from Obsidian vault — watchlists, market theses, risk preferences."""
        from modules.obsidian_reader import ObsidianReader

        reader = ObsidianReader()
        if not reader.available:
            return json.dumps({"status": "unavailable", "message": "Obsidian vault not found at ~/obsidian-vault"})
        ctx = reader.read_trading_context()
        return json.dumps(ctx.to_dict(), indent=2)

    # ------------------------------------------------------------------
    # Historical data & analytics tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def get_candles(coin: str, interval: str = "1h", days: int = 30) -> str:
        """Get historical OHLCV candles. Auto-fetches from HL if not cached.

        Args:
            coin: Coin symbol (e.g., BTC, ETH)
            interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d)
            days: How many days of history (default: 30)
        """
        import time as _time
        from modules.candle_cache import CandleCache
        from modules.data_fetcher import DataFetcher

        cache = CandleCache()
        end_ms = int(_time.time() * 1000)
        start_ms = end_ms - (days * 86_400_000)

        candles = cache.get_candles(coin.upper(), interval, start_ms, end_ms)
        if not candles:
            # Auto-fetch
            try:
                fetcher = DataFetcher(cache=cache, testnet=False)
                fetcher.backfill(coin.upper(), interval, days)
                candles = cache.get_candles(coin.upper(), interval, start_ms, end_ms)
            except Exception as e:
                return json.dumps({"error": f"Failed to fetch: {e}", "candles": []})

        return json.dumps({
            "coin": coin.upper(),
            "interval": interval,
            "count": len(candles),
            "candles": candles[:500],  # cap response size
        })

    @mcp.tool()
    def fetch_data(coin: str, interval: str = "1h", days: int = 90) -> str:
        """Fetch and cache historical candles from HL API.

        Args:
            coin: Coin symbol (e.g., BTC, ETH)
            interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d)
            days: How many days to fetch (default: 90)
        """
        from modules.candle_cache import CandleCache
        from modules.data_fetcher import DataFetcher

        cache = CandleCache()
        fetcher = DataFetcher(cache=cache, testnet=False)
        try:
            count = fetcher.backfill(coin.upper(), interval, days)
            stats = cache.stats()
            return json.dumps({"coin": coin.upper(), "interval": interval, "fetched": count, "cache_stats": stats})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def backtest(strategy: str, coin: str, interval: str = "1h", days: int = 90, capital: float = 10000) -> str:
        """Run a strategy backtest against cached historical data.

        Args:
            strategy: Strategy name from registry (e.g., power_law_btc)
            coin: Coin to backtest on (e.g., BTC)
            interval: Candle interval (default: 1h)
            days: Days of history to backtest (default: 90)
            capital: Starting capital in USD (default: 10000)
        """
        args = ["backtest", "run", "-s", strategy, "-c", coin, "-d", str(days),
                "--capital", str(capital), "--interval", interval]
        return _run_hl(*args, timeout=120)

    @mcp.tool()
    def analyze(coin: str, interval: str = "1h", days: int = 30) -> str:
        """Technical analysis snapshot — EMA, RSI, trend, volume ratio.

        Args:
            coin: Coin symbol (e.g., BTC, ETH)
            interval: Candle interval (default: 1h)
            days: Days of data to analyze (default: 30)
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
                return json.dumps({"error": f"No data available: {e}"})

        if not candles:
            return json.dumps({"error": "No candle data available"})

        closes = [float(c.get("close", c.get("c", 0))) for c in candles if c]
        if len(closes) < 14:
            return json.dumps({"error": f"Insufficient data: {len(closes)} candles (need 14+)"})

        result = {
            "coin": coin.upper(),
            "interval": interval,
            "candles": len(closes),
            "latest_price": closes[-1],
            "ema_5": calc_ema(closes, 5),
            "ema_13": calc_ema(closes, 13),
            "ema_50": calc_ema(closes, 50) if len(closes) >= 50 else None,
            "rsi_14": calc_rsi(closes, 14),
            "volume_ratio": volume_ratio(candles, 5) if len(candles) > 10 else None,
        }

        try:
            result["trend"] = classify_hourly_trend(candles)
        except Exception:
            result["trend"] = "unknown"

        return json.dumps(result)

    @mcp.tool()
    def price_at(coin: str, timestamp_ms: int) -> str:
        """Get the closest candle to a specific timestamp.

        Args:
            coin: Coin symbol (e.g., BTC)
            timestamp_ms: Unix timestamp in milliseconds
        """
        from modules.candle_cache import CandleCache

        cache = CandleCache()
        # Search in a 2-hour window around the timestamp
        window = 3_600_000 * 2
        candles = cache.get_candles(coin.upper(), "1h", timestamp_ms - window, timestamp_ms + window)

        if not candles:
            return json.dumps({"error": "No data near that timestamp"})

        # Find closest
        closest = min(candles, key=lambda c: abs(c.get("timestamp_ms", c.get("t", 0)) - timestamp_ms))
        return json.dumps({"coin": coin.upper(), "requested_ts": timestamp_ms, "candle": closest})

    @mcp.tool()
    def cache_stats() -> str:
        """Show what historical data is cached locally."""
        from modules.candle_cache import CandleCache

        cache = CandleCache()
        return json.dumps(cache.stats())

    # ------------------------------------------------------------------
    # Daemon tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def daemon_status() -> str:
        """Get daemon status — tier, strategies, PnL, risk gate."""
        return _run_hl("daemon", "status")

    @mcp.tool()
    def daemon_start(tier: str = "watch", mock: bool = False, max_ticks: Optional[int] = None) -> str:
        """Start the daemon.

        Args:
            tier: watch, rebalance, or opportunistic
            mock: Use simulated data
            max_ticks: Stop after N ticks (None = run forever)
        """
        args = ["daemon", "start", "--tier", tier]
        if mock:
            args.append("--mock")
        if max_ticks is not None:
            args.extend(["--max-ticks", str(max_ticks)])
        return _run_hl(*args, timeout=max(60, (max_ticks or 5) * 60 + 30))

    # ------------------------------------------------------------------
    # Lab tools — strategy development pipeline
    # ------------------------------------------------------------------

    @mcp.tool()
    def lab_status() -> str:
        """Get Lab status — active experiments, graduated strategies, pipeline progress."""
        from modules.lab_engine import LabEngine
        engine = LabEngine()
        return json.dumps(engine.status(), indent=2)

    @mcp.tool()
    def lab_create(market: str, strategy: str) -> str:
        """Create a new Lab experiment — tests a strategy on a market.

        The experiment progresses: hypothesis → backtest → paper_trade → graduated.
        Graduated experiments are flagged as ready for live production.

        Args:
            market: Market to test (e.g., BTC-PERP, xyz:BRENTOIL)
            strategy: Strategy name from registry
        """
        from modules.lab_engine import LabEngine
        engine = LabEngine()
        exp = engine.create_experiment(market, strategy)
        return json.dumps({
            "created": exp.experiment_id,
            "market": market,
            "strategy": strategy,
            "stage": exp.stage,
            "message": "Experiment created. Will auto-progress through backtest → paper_trade → graduated.",
        }, indent=2)

    @mcp.tool()
    def lab_discover(market: str, days: int = 90) -> str:
        """Discover a market's characteristics and auto-create matching experiments.

        Analyzes volatility, trend strength, mean reversion, volume profile,
        then creates experiments for all matching strategy archetypes.

        Args:
            market: Market to analyze (e.g., BTC-PERP, xyz:BRENTOIL)
            days: Days of historical data to analyze (default: 90)
        """
        import time as _time
        from modules.lab_engine import LabEngine
        from modules.candle_cache import CandleCache
        from modules.data_fetcher import DataFetcher

        coin = market.replace("-PERP", "").replace("xyz:", "")
        cache = CandleCache()
        end_ms = int(_time.time() * 1000)
        start_ms = end_ms - (days * 86_400_000)

        candles = cache.get_candles(coin, "1h", start_ms, end_ms)
        if not candles:
            try:
                fetcher = DataFetcher(cache=cache, testnet=False)
                fetcher.backfill(coin, "1h", days)
                candles = cache.get_candles(coin, "1h", start_ms, end_ms)
            except Exception as e:
                return json.dumps({"error": f"Failed to fetch data: {e}"})

        engine = LabEngine()
        profile = engine.discover_market(market, candles)
        experiments = engine.create_experiments_from_profile(market, profile)

        return json.dumps({
            "market": market,
            "profile": profile,
            "experiments_created": len(experiments),
            "experiments": [
                {"id": e.experiment_id, "strategy": e.strategy, "stage": e.stage}
                for e in experiments
            ],
        }, indent=2)

    # ------------------------------------------------------------------
    # Architect tools — self-improvement loop
    # ------------------------------------------------------------------

    @mcp.tool()
    def architect_status() -> str:
        """Get Architect status — pending proposals, detected patterns, improvement history."""
        from modules.architect_engine import ArchitectEngine
        engine = ArchitectEngine()
        return json.dumps(engine.status(), indent=2)

    @mcp.tool()
    def architect_detect() -> str:
        """Run Architect detection — scan evaluations for actionable patterns and generate proposals."""
        from modules.architect_engine import ArchitectEngine
        engine = ArchitectEngine()
        events = engine.tick()
        status = engine.status()
        return json.dumps({
            "events": events,
            "status": status,
        }, indent=2)

    @mcp.tool()
    def architect_approve(proposal_id: str, notes: str = "") -> str:
        """Approve an Architect proposal for implementation.

        Args:
            proposal_id: ID of the proposal to approve
            notes: Optional reviewer notes
        """
        from modules.architect_engine import ArchitectEngine
        engine = ArchitectEngine()
        success = engine.approve_proposal(proposal_id, notes)
        return json.dumps({
            "approved": success,
            "proposal_id": proposal_id,
            "message": "Proposal approved — will be applied on next config reload" if success
                       else "Proposal not found",
        })

    @mcp.tool()
    def architect_reject(proposal_id: str, notes: str = "") -> str:
        """Reject an Architect proposal.

        Args:
            proposal_id: ID of the proposal to reject
            notes: Reason for rejection
        """
        from modules.architect_engine import ArchitectEngine
        engine = ArchitectEngine()
        success = engine.reject_proposal(proposal_id, notes)
        return json.dumps({
            "rejected": success,
            "proposal_id": proposal_id,
        })

    # ------------------------------------------------------------------
    # Context Engine tool — for debugging/testing context assembly
    # ------------------------------------------------------------------

    @mcp.tool()
    def context_preview(message: str) -> str:
        """Preview what context would be assembled for a message.

        Shows what the LLM would see before answering a Telegram message.
        Useful for debugging the context engine's intent classification
        and data assembly.

        Args:
            message: The message to analyze (as if sent via Telegram)
        """
        from modules.context_engine import assemble_context, classify_intent
        intent = classify_intent(message)
        context = assemble_context(message)
        return json.dumps({
            "intent": intent,
            "context_length": len(context),
            "context": context[:3000],  # cap for readability
        }, indent=2)

    return mcp
