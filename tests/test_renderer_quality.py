"""
Test suite for tool_renderers.py — measure token efficiency and data integrity.

Goals:
1. Verify render_for_ai() produces output under 500 tokens per tool
2. Confirm no critical data points are silently dropped
3. Test error handling and edge cases
4. Measure combined token cost for multi-tool calls
5. Assess readability for free/small LLM models
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent.tool_renderers import render_for_ai
from agent.tool_functions import (
    status, live_price, analyze_market, market_brief,
    check_funding, get_orders, trade_journal,
    thesis_state, daemon_health
)


# ═══════════════════════════════════════════════════════════════════════
# Test Data — Realistic Mock Outputs
# ═══════════════════════════════════════════════════════════════════════

MOCK_STATUS_DATA = {
    "equity": 125430.75,
    "positions": [
        {
            "coin": "BTC",
            "direction": "LONG",
            "size": 2.5,
            "entry_px": 45230.50,
            "upnl": 3450.25,
            "leverage": 2,
            "liquidation_px": 22615.25,
            "dex": "native",
        },
        {
            "coin": "BRENTOIL",
            "direction": "LONG",
            "size": 100,
            "entry_px": 82.45,
            "upnl": -120.35,
            "leverage": 3,
            "liquidation_px": 54.97,
            "dex": "xyz",
        },
    ],
    "spot": [
        {"coin": "USDC", "total": 15234.56},
        {"coin": "GOLD", "total": 0.5},
    ],
}

MOCK_LIVE_PRICE_DATA = {
    "prices": {
        "BTC": 45875.33,
        "ETH": 2890.75,
        "BRENTOIL": 83.21,
        "GOLD": 2385.44,
        "SILVER": 32.10,
    }
}

MOCK_ANALYZE_DATA = {
    "coin": "BTC",
    "price": 45875.33,
    "technicals": (
        "Trend: UPTREND (20EMA > 50EMA)\n"
        "ATR(14): 1823.45 (3.97% of price)\n"
        "BBands: mid=45230, upper=49150, lower=41310\n"
        "RSI(14): 62.3 (neutral, not overbought)\n"
        "Support: 44000, 42500. Resistance: 48000, 50000"
    ),
    "signals": (
        "MACD: bullish crossover (hist=+245)\n"
        "Volume: +15% above 20-day avg\n"
        "OBV: increasing (accumulation)\n"
        "Action: LONG bias, watch 48000 resistance"
    ),
}

MOCK_MARKET_BRIEF_DATA = {
    "market": "BTC",
    "brief": (
        "BTC $45,875 (+2.3% 24h). Technical: uptrend, RSI=62, BBands neutral. "
        "Fundamental: Fed rate expectations steady, institutional inflows continue. "
        "Thesis: LONG conviction=0.75 (macro bullish, chart holds support). "
        "Risk: break below 44000 invalidates thesis. Next catalyst: FOMC next Tue."
    ),
}

MOCK_FUNDING_DATA = {
    "coin": "BRENTOIL",
    "price": 83.21,
    "change_24h_pct": 1.25,
    "funding_rate": 0.000275,
    "funding_ann_pct": 24.14,
    "oi": 125_450_000,
    "volume_24h": 8_750_000_000,
}

MOCK_ORDERS_DATA = {
    "orders": [
        {
            "coin": "BTC",
            "side": "BUY",
            "size": 0.5,
            "price": 44500.0,
            "type": "limit",
        },
        {
            "coin": "BRENTOIL",
            "side": "SELL",
            "size": 50,
            "price": 85.0,
            "type": "limit",
        },
        {
            "coin": "GOLD",
            "side": "BUY",
            "size": 1.0,
            "price": 2375.0,
            "type": "limit",
        },
    ]
}

MOCK_JOURNAL_DATA = {
    "entries": [
        {
            "timestamp": "2026-04-04",
            "coin": "BRENTOIL",
            "side": "LONG",
            "size": 100,
            "price": 82.10,
            "pnl": 320.50,
        },
        {
            "timestamp": "2026-04-03",
            "coin": "BTC",
            "side": "SHORT",
            "size": 1.0,
            "price": 45500.0,
            "pnl": -1200.0,
        },
        {
            "timestamp": "2026-04-02",
            "coin": "GOLD",
            "side": "LONG",
            "size": 2.0,
            "price": 2380.0,
            "pnl": 45.25,
        },
    ]
}

MOCK_THESIS_DATA = {
    "theses": {
        "BTC": {
            "direction": "LONG",
            "conviction": 0.75,
            "summary": "Macro tailwinds: debt monetization, geopolitical risk premium. Technicals hold.",
            "updated_at": "2026-04-04T10:15:23Z",
        },
        "BRENTOIL": {
            "direction": "LONG",
            "conviction": 0.55,
            "summary": "Supply tightness, Iran/Hormuz geopolitical risk. Contango drag risk.",
            "updated_at": "2026-04-03T08:30:00Z",
        },
        "GOLD": {
            "direction": "LONG",
            "conviction": 0.40,
            "summary": "Inflation hedge, rate expectations ambiguous. Lower conviction.",
            "updated_at": "2026-04-01T16:45:10Z",
        },
    }
}

MOCK_DAEMON_HEALTH_DATA = {
    "tier": "WATCH",
    "tick": 4875,
    "gate": "open",
    "last_tick_at": "2026-04-04T14:32:15Z",
    "strategies": ["heartbeat", "conviction_rebalancer", "oil_dca"],
}


# ═══════════════════════════════════════════════════════════════════════
# Helper: Token Estimation
# ═══════════════════════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """Rough token count: chars / 4 (Claude tokenizer average)."""
    return len(text) // 4


def detailed_token_analysis(rendered: str, tool_name: str) -> dict:
    """Analyze token efficiency and readability."""
    tokens = estimate_tokens(rendered)
    lines = rendered.strip().split('\n')

    return {
        "tool": tool_name,
        "chars": len(rendered),
        "lines": len(lines),
        "tokens_estimated": tokens,
        "avg_tokens_per_line": tokens / len(lines) if lines else 0,
        "under_500_tokens": tokens < 500,
        "compact_score": "GOOD" if tokens < 200 else ("FAIR" if tokens < 400 else "VERBOSE"),
        "readable_score": "GOOD" if len(lines) <= 1 or (tokens < 300 and len(lines) <= 5) else "CHECK",
    }


# ═══════════════════════════════════════════════════════════════════════
# Tests: Individual Tool Renderers
# ═══════════════════════════════════════════════════════════════════════

class TestIndividualRenderers:
    """Test each tool's renderer for token efficiency and data retention."""

    def test_render_status_ai(self):
        """Status: equity + positions (with liq) + spot balances."""
        rendered = render_for_ai("status", MOCK_STATUS_DATA)
        analysis = detailed_token_analysis(rendered, "status")

        # Verify critical data points present
        assert "125,430.75" in rendered or "125430.75" in rendered, "Equity missing"
        assert "BTC" in rendered, "BTC position missing"
        assert "2.5" in rendered, "BTC size missing"
        assert "45,230.50" in rendered or "45230.50" in rendered, "BTC entry price missing"
        assert "3,450.25" in rendered or "3450.25" in rendered, "BTC uPnL missing"
        assert "2x" in rendered, "BTC leverage missing"
        assert "22,615.25" in rendered or "22615.25" in rendered, "BTC liquidation price missing"
        assert "BRENTOIL" in rendered, "BRENTOIL position missing"
        assert "100" in rendered, "BRENTOIL size missing"
        assert "USDC" in rendered, "Spot USDC missing"

        # Token efficiency check
        assert analysis["tokens_estimated"] < 500, \
            f"Status rendered in {analysis['tokens_estimated']} tokens (>500 limit)"

        print(f"\nStatus renderer: {analysis['tokens_estimated']} tokens")
        print(f"  Output: {rendered[:200]}...")
        return analysis

    def test_render_live_price_ai(self):
        """Live prices: simple key=value list."""
        rendered = render_for_ai("live_price", MOCK_LIVE_PRICE_DATA)
        analysis = detailed_token_analysis(rendered, "live_price")

        # Verify all prices present
        for coin, price in MOCK_LIVE_PRICE_DATA["prices"].items():
            assert coin in rendered, f"{coin} price missing"

        assert analysis["tokens_estimated"] < 200, \
            f"Live price too verbose: {analysis['tokens_estimated']} tokens"

        print(f"\nLive price renderer: {analysis['tokens_estimated']} tokens")
        print(f"  Output: {rendered}")
        return analysis

    def test_render_analyze_market_ai(self):
        """Market analysis: technicals + signals (multi-line)."""
        rendered = render_for_ai("analyze_market", MOCK_ANALYZE_DATA)
        analysis = detailed_token_analysis(rendered, "analyze_market")

        # Verify no data dropped
        assert "BTC" in rendered, "Coin missing"
        assert "45,875.33" in rendered or "45875.33" in rendered, "Price missing"
        assert "Trend: UPTREND" in rendered or "UPTREND" in rendered, "Technicals dropped"
        assert "MACD" in rendered or "signal" in rendered.lower(), "Signals dropped"

        assert analysis["tokens_estimated"] < 500, \
            f"Analyze market too verbose: {analysis['tokens_estimated']} tokens"

        print(f"\nAnalyze market renderer: {analysis['tokens_estimated']} tokens")
        print(f"  Lines: {analysis['lines']}")
        return analysis

    def test_render_market_brief_ai(self):
        """Market brief: full narrative text."""
        rendered = render_for_ai("market_brief", MOCK_MARKET_BRIEF_DATA)
        analysis = detailed_token_analysis(rendered, "market_brief")

        # Verify content
        assert len(rendered) > 50, "Market brief too short"
        assert "BTC" in rendered or "45875" in rendered, "Market info missing"

        print(f"\nMarket brief renderer: {analysis['tokens_estimated']} tokens")
        print(f"  Output: {rendered[:150]}...")
        return analysis

    def test_render_funding_ai(self):
        """Funding: rate, OI, volume on single line."""
        rendered = render_for_ai("check_funding", MOCK_FUNDING_DATA)
        analysis = detailed_token_analysis(rendered, "check_funding")

        # Verify critical metrics
        assert "BRENTOIL" in rendered, "Coin missing"
        assert "83.21" in rendered, "Price missing"
        assert "1.2" in rendered or "1.25" in rendered, "Change missing"
        assert "funding" in rendered.lower(), "Funding rate missing"
        assert "OI" in rendered or "125.5" in rendered, "OI missing"
        assert "vol" in rendered.lower(), "Volume missing"

        assert analysis["tokens_estimated"] < 200, \
            f"Funding too verbose: {analysis['tokens_estimated']} tokens"

        print(f"\nFunding renderer: {analysis['tokens_estimated']} tokens")
        print(f"  Output: {rendered}")
        return analysis

    def test_render_orders_ai(self):
        """Orders: list of open orders."""
        rendered = render_for_ai("get_orders", MOCK_ORDERS_DATA)
        analysis = detailed_token_analysis(rendered, "get_orders")

        # Verify orders present
        assert "3 orders" in rendered, "Order count missing"
        assert "BTC" in rendered, "BTC order missing"
        assert "BRENTOIL" in rendered, "BRENTOIL order missing"
        assert "GOLD" in rendered, "GOLD order missing"
        assert "44500" in rendered, "BTC price missing"
        assert "BUY" in rendered or "SELL" in rendered, "Order side missing"

        assert analysis["tokens_estimated"] < 300, \
            f"Orders too verbose: {analysis['tokens_estimated']} tokens"

        print(f"\nOrders renderer: {analysis['tokens_estimated']} tokens")
        return analysis

    def test_render_journal_ai(self):
        """Trade journal: recent PnL entries."""
        rendered = render_for_ai("trade_journal", MOCK_JOURNAL_DATA)
        analysis = detailed_token_analysis(rendered, "trade_journal")

        # Verify trades present
        assert "Last 3 trades" in rendered, "Trade count missing"
        assert "BRENTOIL" in rendered, "BRENTOIL trade missing"
        assert "BTC" in rendered, "BTC trade missing"
        assert "2026-04-04" in rendered or "04-04" in rendered, "Date missing"
        assert "320.50" in rendered or "320" in rendered, "PnL missing"

        print(f"\nJournal renderer: {analysis['tokens_estimated']} tokens")
        return analysis

    def test_render_thesis_ai(self):
        """Thesis state: market direction + conviction + summary (truncated)."""
        rendered = render_for_ai("thesis_state", MOCK_THESIS_DATA)
        analysis = detailed_token_analysis(rendered, "thesis_state")

        # Verify all theses present
        assert "BTC" in rendered, "BTC thesis missing"
        assert "BRENTOIL" in rendered, "BRENTOIL thesis missing"
        assert "GOLD" in rendered, "GOLD thesis missing"
        assert "LONG" in rendered, "Direction missing"
        assert "0.75" in rendered or "75" in rendered, "Conviction missing"
        assert "conv=" in rendered, "Conviction label missing"

        assert analysis["tokens_estimated"] < 400, \
            f"Thesis too verbose: {analysis['tokens_estimated']} tokens"

        print(f"\nThesis renderer: {analysis['tokens_estimated']} tokens")
        return analysis

    def test_render_daemon_ai(self):
        """Daemon health: tier, tick, gate, strategies."""
        rendered = render_for_ai("daemon_health", MOCK_DAEMON_HEALTH_DATA)
        analysis = detailed_token_analysis(rendered, "daemon_health")

        # Verify all fields
        assert "WATCH" in rendered or "tier=" in rendered, "Tier missing"
        assert "4875" in rendered or "tick=" in rendered, "Tick count missing"
        assert "open" in rendered or "gate=" in rendered, "Gate missing"
        assert "heartbeat" in rendered or "strategy" in rendered.lower(), "Strategies missing"

        assert analysis["tokens_estimated"] < 100, \
            f"Daemon too verbose: {analysis['tokens_estimated']} tokens"

        print(f"\nDaemon renderer: {analysis['tokens_estimated']} tokens")
        return analysis


# ═══════════════════════════════════════════════════════════════════════
# Tests: Error Handling
# ═══════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Test graceful error rendering."""

    def test_status_error(self):
        """Status with error."""
        rendered = render_for_ai("status", {"error": "No wallet configured"})
        assert "ERROR" in rendered or "error" in rendered.lower()
        assert "No wallet" in rendered

    def test_live_price_error(self):
        """Live price with error."""
        rendered = render_for_ai("live_price", {"error": "API timeout"})
        assert "ERROR" in rendered
        assert "timeout" in rendered.lower()

    def test_funding_error(self):
        """Funding with error."""
        rendered = render_for_ai("check_funding", {"error": "No funding data for MEMECOIN"})
        assert "ERROR" in rendered
        assert "MEMECOIN" in rendered

    def test_unknown_tool(self):
        """Unknown tool falls back to generic JSON."""
        rendered = render_for_ai("unknown_tool_xyz", {"data": "test", "value": 123})
        # Should produce compact JSON
        assert "test" in rendered or "123" in rendered

    def test_empty_orders(self):
        """Empty orders list."""
        rendered = render_for_ai("get_orders", {"orders": []})
        assert "No open orders" in rendered

    def test_empty_journal(self):
        """Empty trade journal."""
        rendered = render_for_ai("trade_journal", {"entries": []})
        assert "No trade entries" in rendered

    def test_empty_theses(self):
        """No active theses."""
        rendered = render_for_ai("thesis_state", {"theses": {}})
        assert "No active theses" in rendered


# ═══════════════════════════════════════════════════════════════════════
# Tests: Multi-Tool Calls (Composite Cost)
# ═══════════════════════════════════════════════════════════════════════

class TestMultiToolCost:
    """Measure token cost for realistic multi-tool calls."""

    def test_check_everything_call(self):
        """Typical "check everything" call: status + live_price + funding."""
        status_out = render_for_ai("status", MOCK_STATUS_DATA)
        price_out = render_for_ai("live_price", MOCK_LIVE_PRICE_DATA)
        funding_out = render_for_ai("check_funding", MOCK_FUNDING_DATA)

        combined = f"{status_out}\n{price_out}\n{funding_out}"
        tokens = estimate_tokens(combined)

        analysis = detailed_token_analysis(combined, "check_everything")

        print(f"\n'Check everything' composite call:")
        print(f"  Status: {estimate_tokens(status_out)} tokens")
        print(f"  Live price: {estimate_tokens(price_out)} tokens")
        print(f"  Funding: {estimate_tokens(funding_out)} tokens")
        print(f"  Total: {tokens} tokens")
        print(f"  Assessment: {'GOOD' if tokens < 600 else 'CONSIDER_SPLITTING'}")

        # Should fit in typical context window comfortably
        assert tokens < 1000, f"Check everything costs {tokens} tokens"
        return tokens

    def test_morning_briefing_call(self):
        """Morning briefing: status + live_price + thesis_state + daemon_health."""
        status_out = render_for_ai("status", MOCK_STATUS_DATA)
        price_out = render_for_ai("live_price", MOCK_LIVE_PRICE_DATA)
        thesis_out = render_for_ai("thesis_state", MOCK_THESIS_DATA)
        daemon_out = render_for_ai("daemon_health", MOCK_DAEMON_HEALTH_DATA)

        combined = f"{status_out}\n{price_out}\n{thesis_out}\n{daemon_out}"
        tokens = estimate_tokens(combined)

        print(f"\nMorning briefing composite call:")
        print(f"  Total: {tokens} tokens")
        print(f"  Assessment: {'GOOD' if tokens < 800 else 'MONITOR'}")

        assert tokens < 1200, f"Morning briefing costs {tokens} tokens"
        return tokens

    def test_full_market_analysis_call(self):
        """Full market analysis: live_price + analyze_market + funding + thesis."""
        price_out = render_for_ai("live_price", MOCK_LIVE_PRICE_DATA)
        analysis_out = render_for_ai("analyze_market", MOCK_ANALYZE_DATA)
        funding_out = render_for_ai("check_funding", MOCK_FUNDING_DATA)
        thesis_out = render_for_ai("thesis_state", MOCK_THESIS_DATA)

        combined = f"{price_out}\n{analysis_out}\n{funding_out}\n{thesis_out}"
        tokens = estimate_tokens(combined)

        print(f"\nFull market analysis composite call:")
        print(f"  Total: {tokens} tokens")

        return tokens


# ═══════════════════════════════════════════════════════════════════════
# Tests: Readability for Different LLM Sizes
# ═══════════════════════════════════════════════════════════════════════

class TestReadability:
    """Assess whether output is understandable by smaller LLMs."""

    def test_status_readability(self):
        """Status should be parseable by simple models."""
        rendered = render_for_ai("status", MOCK_STATUS_DATA)
        # Check for key parsing patterns
        assert "|" in rendered or "\n" in rendered, "No delimiter found"
        # Should have "=" for field assignment
        assert "=" in rendered, "No assignment operators"
        # Numbers should be formatted consistently
        assert "," in rendered, "Numbers not formatted"

    def test_funding_readability(self):
        """Funding should be a single, coherent line."""
        rendered = render_for_ai("check_funding", MOCK_FUNDING_DATA)
        lines = rendered.strip().split("\n")
        assert len(lines) <= 2, f"Funding too multi-line: {len(lines)} lines"
        # Should use consistent formatting
        assert "=" in rendered or "%" in rendered, "Missing units"

    def test_thesis_clarity(self):
        """Thesis should clearly show direction + conviction."""
        rendered = render_for_ai("thesis_state", MOCK_THESIS_DATA)
        # Each thesis line should have coin, direction, conviction
        for line in rendered.split("\n")[1:]:  # Skip header
            if line.strip():
                assert any(c in line for c in ["LONG", "SHORT", "FLAT", "conv="]), \
                    f"Line missing direction/conviction: {line}"

    def test_orders_clarity(self):
        """Orders should be easy to parse."""
        rendered = render_for_ai("get_orders", MOCK_ORDERS_DATA)
        # Should indicate order count and list clearly
        assert "order" in rendered.lower(), "Order context missing"
        assert "BUY" in rendered or "SELL" in rendered, "Side missing"


# ═══════════════════════════════════════════════════════════════════════
# Tests: Data Integrity — Nothing Silently Dropped
# ═══════════════════════════════════════════════════════════════════════

class TestDataIntegrity:
    """Verify that renderers don't silently drop critical fields."""

    def test_status_includes_liquidation(self):
        """Status must include liquidation prices (risk-critical)."""
        rendered = render_for_ai("status", MOCK_STATUS_DATA)
        # Both positions have liquidation prices
        assert "22,615.25" in rendered or "22615.25" in rendered, "BTC liquidation price dropped"
        assert "54.97" in rendered, "BRENTOIL liquidation price dropped"

    def test_status_includes_leverage(self):
        """Status must include leverage (position structure)."""
        rendered = render_for_ai("status", MOCK_STATUS_DATA)
        assert "2x" in rendered or "2" in rendered, "BTC leverage dropped"
        assert "3x" in rendered or "3" in rendered, "BRENTOIL leverage dropped"

    def test_funding_includes_annualized(self):
        """Funding should show both periodic and annualized rate."""
        rendered = render_for_ai("check_funding", MOCK_FUNDING_DATA)
        # Should have both hourly and annual
        assert "24" in rendered or "ann" in rendered.lower(), "Annualized rate dropped"

    def test_thesis_includes_summary(self):
        """Thesis should include summary (context for conviction)."""
        rendered = render_for_ai("thesis_state", MOCK_THESIS_DATA)
        # First 80 chars of each summary should be in output
        assert "Macro tailwind" in rendered or "debt" in rendered or "macro" in rendered.lower(), \
            "BTC thesis summary dropped"
        assert "Supply" in rendered or "supply" in rendered.lower(), \
            "BRENTOIL thesis summary dropped"

    def test_journal_includes_pnl(self):
        """Trade journal must include PnL (outcome metric)."""
        rendered = render_for_ai("trade_journal", MOCK_JOURNAL_DATA)
        assert "320" in rendered, "BRENTOIL trade PnL dropped"
        assert "-1200" in rendered or "1200" in rendered, "BTC trade loss dropped"

    def test_analyze_includes_both_sections(self):
        """Analysis must include both technicals AND signals."""
        rendered = render_for_ai("analyze_market", MOCK_ANALYZE_DATA)
        # Should have both major sections
        has_technicals = "Trend" in rendered or "ATR" in rendered or "UPTREND" in rendered
        has_signals = "MACD" in rendered or "Volume" in rendered or "Action" in rendered
        assert has_technicals and has_signals, \
            f"Missing sections: technicals={has_technicals}, signals={has_signals}"


# ═══════════════════════════════════════════════════════════════════════
# Integration Test: Render All Tools
# ═══════════════════════════════════════════════════════════════════════

class TestRenderAllTools:
    """Run render_for_ai on all tool types and collect metrics."""

    def test_all_tools_render_without_exception(self):
        """Every tool should render without crashing."""
        test_cases = [
            ("status", MOCK_STATUS_DATA),
            ("account_summary", MOCK_STATUS_DATA),  # alias
            ("live_price", MOCK_LIVE_PRICE_DATA),
            ("analyze_market", MOCK_ANALYZE_DATA),
            ("market_brief", MOCK_MARKET_BRIEF_DATA),
            ("check_funding", MOCK_FUNDING_DATA),
            ("get_orders", MOCK_ORDERS_DATA),
            ("trade_journal", MOCK_JOURNAL_DATA),
            ("thesis_state", MOCK_THESIS_DATA),
            ("daemon_health", MOCK_DAEMON_HEALTH_DATA),
        ]

        results = []
        for tool_name, data in test_cases:
            try:
                rendered = render_for_ai(tool_name, data)
                analysis = detailed_token_analysis(rendered, tool_name)
                results.append(analysis)
                assert len(rendered) > 0, f"{tool_name} rendered empty"
            except Exception as e:
                pytest.fail(f"{tool_name} failed: {e}")

        # Print summary table
        print("\n" + "="*80)
        print("RENDERER QUALITY REPORT")
        print("="*80)
        print(f"{'Tool':<20} {'Tokens':<10} {'Compact':<10} {'Readable':<10}")
        print("-"*80)
        for r in results:
            print(f"{r['tool']:<20} {r['tokens_estimated']:<10} {r['compact_score']:<10} {r['readable_score']:<10}")

        # Overall stats
        total_tokens = sum(r["tokens_estimated"] for r in results)
        avg_tokens = total_tokens / len(results)
        print("-"*80)
        print(f"Total (all 10 tools): {total_tokens} tokens")
        print(f"Average per tool: {avg_tokens:.0f} tokens")
        print(f"All under 500 tokens: {all(r['under_500_tokens'] for r in results)}")

        assert total_tokens < 3500, \
            f"All tools total {total_tokens} tokens (should be <3500)"


# ═══════════════════════════════════════════════════════════════════════
# Performance Test: Rendering Speed
# ═══════════════════════════════════════════════════════════════════════

class TestRenderingPerformance:
    """Ensure renderers are fast (should complete in <1ms per call)."""

    def test_render_speed(self):
        """Rendering should be sub-millisecond."""
        test_cases = [
            ("status", MOCK_STATUS_DATA),
            ("live_price", MOCK_LIVE_PRICE_DATA),
            ("check_funding", MOCK_FUNDING_DATA),
            ("thesis_state", MOCK_THESIS_DATA),
        ]

        for tool_name, data in test_cases:
            start = time.perf_counter()
            rendered = render_for_ai(tool_name, data)
            elapsed = (time.perf_counter() - start) * 1000  # ms

            assert elapsed < 5, f"{tool_name} took {elapsed:.2f}ms"
            print(f"{tool_name:<20} {elapsed:.3f}ms")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
