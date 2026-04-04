"""Tests for common/code_tool_parser.py — AST-based Python code block parsing."""
import pytest
from common.code_tool_parser import parse_tool_calls, execute_parsed_calls, strip_code_blocks, ToolCall


# Mock registry for testing
def _mock_status():
    return {"equity": 100.0, "positions": []}


def _mock_live_price(market="all"):
    return {"prices": {"BTC": 82000.0}}


def _mock_analyze(coin):
    return {"coin": coin, "price": 108.0, "technicals": "bullish"}


def _mock_check_funding(coin):
    return {"coin": coin, "funding_rate": 0.001}


def _mock_place_trade(coin, side, size):
    return {"filled": True, "coin": coin}


MOCK_REGISTRY = {
    "status": _mock_status,
    "live_price": _mock_live_price,
    "analyze_market": _mock_analyze,
    "check_funding": _mock_check_funding,
    "place_trade": _mock_place_trade,
}

MOCK_WRITE_TOOLS = {"place_trade"}


class TestParseToolCalls:
    def test_simple_no_args(self):
        ai_output = "Let me check.\n```python\naccount = status()\n```"
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].name == "status"
        assert calls[0].args == []

    def test_single_string_arg(self):
        ai_output = '```python\nprices = live_price("BTC")\n```'
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].name == "live_price"
        assert calls[0].args == ["BTC"]

    def test_multiple_calls(self):
        ai_output = '```python\nprices = live_price("BTC")\naccount = status()\nfunding = check_funding("BRENTOIL")\n```'
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 3
        assert [c.name for c in calls] == ["live_price", "status", "check_funding"]

    def test_keyword_args(self):
        ai_output = '```python\nresult = live_price(market="xyz:GOLD")\n```'
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].kwargs == {"market": "xyz:GOLD"}

    def test_ignores_unknown_functions(self):
        ai_output = '```python\nimport os\nos.system("rm -rf /")\nstatus()\n```'
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].name == "status"

    def test_no_code_blocks(self):
        ai_output = "Here's my analysis of the market."
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert calls == []

    def test_non_python_code_block(self):
        ai_output = "```json\n{\"key\": \"value\"}\n```"
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert calls == []

    def test_syntax_error_graceful(self):
        ai_output = "```python\nthis is not valid python {{{\n```"
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert calls == []

    def test_numeric_args(self):
        ai_output = '```python\nplace_trade("BTC", "buy", 0.5)\n```'
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].args == ["BTC", "buy", 0.5]

    def test_negative_number(self):
        ai_output = '```python\nplace_trade("BTC", "sell", -1.5)\n```'
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].args[2] == -1.5

    def test_mixed_positional_and_keyword(self):
        ai_output = '```python\nanalyze_market(coin="xyz:BRENTOIL")\n```'
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].kwargs == {"coin": "xyz:BRENTOIL"}

    def test_unfenced_python(self):
        """Bare code blocks with just ``` should also be tried."""
        ai_output = "```\nstatus()\n```"
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1

    def test_multiple_code_blocks(self):
        ai_output = (
            "First:\n```python\nstatus()\n```\n"
            "Then:\n```python\nlive_price(\"BTC\")\n```"
        )
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 2

    def test_variable_expressions_skipped(self):
        """Variables as args should be skipped (not literal)."""
        ai_output = '```python\nx = "BTC"\nlive_price(x)\n```'
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # live_price(x) uses a variable, not a literal — should be skipped
        assert len(calls) == 0


class TestExecuteParsedCalls:
    def test_read_tool_executes(self):
        calls = [ToolCall(name="status")]
        results = execute_parsed_calls(calls, MOCK_REGISTRY, MOCK_WRITE_TOOLS)
        assert len(results) == 1
        assert results[0].data == {"equity": 100.0, "positions": []}
        assert results[0].error is None

    def test_write_tool_returns_pending(self):
        calls = [ToolCall(name="place_trade", args=["BTC", "buy", 0.5])]
        results = execute_parsed_calls(calls, MOCK_REGISTRY, MOCK_WRITE_TOOLS)
        assert len(results) == 1
        assert results[0].data.get("_pending") is True

    def test_unknown_tool(self):
        calls = [ToolCall(name="nonexistent")]
        results = execute_parsed_calls(calls, MOCK_REGISTRY, MOCK_WRITE_TOOLS)
        assert results[0].error == "Unknown tool: nonexistent"

    def test_positional_args_mapped(self):
        calls = [ToolCall(name="analyze_market", args=["xyz:BRENTOIL"])]
        results = execute_parsed_calls(calls, MOCK_REGISTRY, MOCK_WRITE_TOOLS)
        assert results[0].data["coin"] == "xyz:BRENTOIL"

    def test_keyword_args(self):
        calls = [ToolCall(name="live_price", kwargs={"market": "BTC"})]
        results = execute_parsed_calls(calls, MOCK_REGISTRY, MOCK_WRITE_TOOLS)
        assert results[0].data == {"prices": {"BTC": 82000.0}}


class TestStripCodeBlocks:
    def test_strips_python_block(self):
        text = "Let me check.\n```python\nstatus()\n```\nHere's what I found:"
        result = strip_code_blocks(text)
        assert "```" not in result
        assert "status()" not in result
        assert "Let me check." in result
        assert "Here's what I found:" in result

    def test_preserves_non_code(self):
        text = "No code blocks here."
        assert strip_code_blocks(text) == text

    def test_strips_multiple(self):
        text = "A\n```python\nfoo()\n```\nB\n```python\nbar()\n```\nC"
        result = strip_code_blocks(text)
        assert "foo" not in result
        assert "bar" not in result
        assert "A" in result
        assert "C" in result
