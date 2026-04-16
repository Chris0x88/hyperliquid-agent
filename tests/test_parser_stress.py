"""Comprehensive stress test for AST-based code tool parser.

Tests realistic free model failures:
- Indentation variations
- Extra text in code blocks
- Missing/wrong fence formatting
- Multiple calls, chained calls, type hints
- Hallucinated function names
- Various argument types (literals, lists, dicts, booleans, None, strings)
- Mixed valid/invalid in one block
- Edge cases (empty blocks, only imports, very long strings, etc.)
"""
import sys
import pytest
from pathlib import Path

# Add parent to path so we can import from common
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.code_tool_parser import parse_tool_calls, execute_parsed_calls, ToolCall


# Mock registry matching the spec
MOCK_REGISTRY = {
    "status": lambda: {"market": "all", "time": 1234567890},
    "live_price": lambda market="all": {"market": market, "price": 50000},
    "analyze_market": lambda coin: {"coin": coin, "analysis": "bullish"},
    "check_funding": lambda coin: {"coin": coin, "funding_rate": 0.001},
    "get_orders": lambda: {"orders": []},
    "trade_journal": lambda limit=10: {"trades": [], "limit": limit},
    "thesis_state": lambda market="all": {"market": market, "thesis": "long"},
    "place_trade": lambda coin, side, size: {"coin": coin, "side": side, "size": size, "status": "pending"},
}


class TestParserFailureModes:
    """Test each failure mode with realistic LLM outputs."""

    def test_1_indentation_variations(self):
        """Free models sometimes indent code inside markdown."""
        ai_output = """Here's the status:

```python
    status()
    live_price("BTC")
```

Done."""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 2
        assert calls[0].name == "status"
        assert calls[1].name == "live_price"
        print("✓ Test 1 (indentation): PASS")

    def test_2_extra_text_in_code_blocks(self):
        """Models mix comments and explanations with code."""
        ai_output = """Let me check the market:

```python
# First, get the status
status()

# Then check BTC price
live_price("BTC")

# Done!
```

Analysis follows..."""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 2
        assert calls[0].name == "status"
        assert calls[1].name == "live_price"
        assert calls[1].args == ["BTC"]
        print("✓ Test 2 (extra text/comments): PASS")

    def test_3_no_fencing(self):
        """Some models write inline without code fences."""
        ai_output = """Call status() and live_price("BTC") to check."""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # Should NOT parse inline code without fences
        assert len(calls) == 0
        print("✓ Test 3 (no fencing): PASS - correctly rejected")

    def test_4_wrong_fence_language(self):
        """Test various fence formats: Python (capital P), py, empty."""
        test_cases = [
            ('```Python\nstatus()\n```', "capital P"),
            ('```py\nlive_price("BTC")\n```', "lowercase py"),
            ('```\nanalyze_market("BTC")\n```', "no language"),
        ]
        for ai_output, desc in test_cases:
            calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
            assert len(calls) == 1, f"Failed for {desc}"
            print(f"  ✓ Variant '{desc}': PASS")
        print("✓ Test 4 (wrong fence language): PASS")

    def test_5_multiple_calls_one_line(self):
        """Multiple calls on one line."""
        ai_output = """```python
status(); live_price("BTC")
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 2
        assert calls[0].name == "status"
        assert calls[1].name == "live_price"
        print("✓ Test 5 (multiple calls one line): PASS")

    def test_6_fstring_args_rejected(self):
        """f-strings should be rejected (not literal)."""
        coin = "BTC"
        ai_output = f"""```python
live_price(f"xyz:{{coin}}")
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # f-string is JoinedStr in AST, not a Constant — should be rejected
        assert len(calls) == 0
        print("✓ Test 6 (f-string rejected): PASS")

    def test_7_dict_literal_args(self):
        """Dict literals as positional arguments."""
        ai_output = '''```python
analyze_market({"coin": "BTC"})
```'''
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # Dict as positional arg — parser should accept it as a literal
        assert len(calls) == 1
        assert calls[0].name == "analyze_market"
        assert calls[0].args == [{"coin": "BTC"}]
        print("✓ Test 7 (dict literal args): PASS")

    def test_8_chained_calls_rejected(self):
        """Chained calls like analyze_market(check_funding("BTC").coin) should be rejected."""
        ai_output = '''```python
result = analyze_market(check_funding("BTC").coin)
```'''
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # check_funding("BTC").coin is not a literal — it's an Attribute access on a Call result
        assert len(calls) == 0
        print("✓ Test 8 (chained calls rejected): PASS")

    def test_9_type_hint_assignment(self):
        """Assignment with type hint: result: dict = status()"""
        ai_output = """```python
result: dict = status()
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # Type hint shouldn't affect parsing — status() is still called
        assert len(calls) == 1
        assert calls[0].name == "status"
        print("✓ Test 9 (type hint assignment): PASS")

    def test_10_hallucinated_function_names(self):
        """Hallucinated function names should be rejected."""
        ai_output = """```python
status()
get_market_data("BTC")
fetch_price("BTC")
live_price("ETH")
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # Only status() and live_price() are in registry
        assert len(calls) == 2
        assert calls[0].name == "status"
        assert calls[1].name == "live_price"
        print("✓ Test 10 (hallucinated names rejected): PASS")

    def test_11_mixed_valid_invalid_one_block(self):
        """Some calls valid, some hallucinated in one block."""
        ai_output = """```python
status()
unknown_function()
live_price("BTC")
get_data("ETH")
analyze_market("BTC")
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # Only valid names parsed
        assert len(calls) == 3
        assert [c.name for c in calls] == ["status", "live_price", "analyze_market"]
        print("✓ Test 11 (mixed valid/invalid): PASS")

    def test_12_empty_code_block(self):
        """Empty code block."""
        ai_output = """```python
```

Let me try again."""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 0
        print("✓ Test 12 (empty code block): PASS")

    def test_13_only_imports(self):
        """Code block with only imports."""
        ai_output = """```python
import json
from datetime import datetime
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 0
        print("✓ Test 13 (only imports): PASS")

    def test_14_boolean_and_none_args(self):
        """Boolean and None arguments."""
        ai_output = """```python
place_trade("BTC", True, None)
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # place_trade expects (coin, side, size) — we're passing (coin, bool, None)
        # Parser should accept them as literals, execution layer can validate
        assert len(calls) == 1
        assert calls[0].args == ["BTC", True, None]
        print("✓ Test 14 (boolean and None args): PASS")

    def test_15_very_long_string_args(self):
        """Very long string arguments (500+ chars)."""
        long_string = "x" * 500
        ai_output = f'''```python
status()
analyze_market("{long_string}")
```'''
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 2
        assert calls[1].args[0] == long_string
        print("✓ Test 15 (very long string args): PASS")

    def test_16_nested_function_calls_rejected(self):
        """Nested function calls like live_price(get_coin_name()) should be rejected."""
        ai_output = """```python
live_price(get_coin_name())
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # get_coin_name() is a Call node, not a literal
        assert len(calls) == 0
        print("✓ Test 16 (nested function calls rejected): PASS")

    def test_17_list_args(self):
        """List arguments."""
        ai_output = """```python
analyze_market(["BTC", "ETH"])
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].args == [["BTC", "ETH"]]
        print("✓ Test 17 (list args): PASS")

    def test_18_keyword_arguments(self):
        """Keyword arguments."""
        ai_output = """```python
live_price(market="BTC")
trade_journal(limit=5)
thesis_state(market="BTC")
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 3
        assert calls[0].kwargs == {"market": "BTC"}
        assert calls[1].kwargs == {"limit": 5}
        assert calls[2].kwargs == {"market": "BTC"}
        print("✓ Test 18 (keyword arguments): PASS")

    def test_19_mixed_positional_keyword(self):
        """Mixed positional and keyword arguments."""
        ai_output = """```python
place_trade("BTC", "long", 1.5)
place_trade(coin="ETH", side="short", size=0.5)
place_trade("ADA", side="long", size=2)
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 3
        assert calls[0].args == ["BTC", "long", 1.5]
        assert calls[1].kwargs == {"coin": "ETH", "side": "short", "size": 0.5}
        assert calls[2].args == ["ADA"]
        assert calls[2].kwargs == {"side": "long", "size": 2}
        print("✓ Test 19 (mixed positional/keyword): PASS")

    def test_20_negative_numbers(self):
        """Negative number arguments."""
        ai_output = """```python
place_trade("BTC", "long", -1.5)
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].args == ["BTC", "long", -1.5]
        print("✓ Test 20 (negative numbers): PASS")

    def test_21_float_args(self):
        """Float arguments."""
        ai_output = """```python
place_trade("BTC", "long", 0.001)
place_trade("ETH", "short", 3.14159)
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 2
        assert calls[0].args == ["BTC", "long", 0.001]
        assert calls[1].args == ["ETH", "short", 3.14159]
        print("✓ Test 21 (float args): PASS")

    def test_22_integer_args(self):
        """Integer arguments."""
        ai_output = """```python
trade_journal(limit=100)
trade_journal(5)
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 2
        assert calls[0].kwargs == {"limit": 100}
        assert calls[1].args == [5]
        print("✓ Test 22 (integer args): PASS")

    def test_23_multiple_code_blocks(self):
        """Multiple code blocks in one AI output."""
        ai_output = """First block:

```python
status()
```

Second block:

```python
live_price("BTC")
analyze_market("ETH")
```

Done."""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 3
        assert [c.name for c in calls] == ["status", "live_price", "analyze_market"]
        print("✓ Test 23 (multiple code blocks): PASS")

    def test_24_whitespace_variations(self):
        """Various whitespace patterns around code blocks."""
        test_cases = [
            ("```python\nstatus()\n```", "no blank lines"),
            ("```python\n\nstatus()\n\n```", "blank lines inside"),
            ("```python  \nstatus()\n  ```", "spaces in fence"),
        ]
        for ai_output, desc in test_cases:
            calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
            assert len(calls) == 1, f"Failed for {desc}"
            print(f"  ✓ Variant '{desc}': PASS")
        print("✓ Test 24 (whitespace variations): PASS")

    def test_25_attribute_access_function_name(self):
        """Function called via attribute: tools.status()"""
        ai_output = """```python
tools.status()
obj.live_price("BTC")
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # Parser should extract attribute name: status, live_price
        assert len(calls) == 2
        assert calls[0].name == "status"
        assert calls[1].name == "live_price"
        print("✓ Test 25 (attribute access function name): PASS")

    def test_26_syntax_error_blocks(self):
        """Code blocks with syntax errors."""
        ai_output = """```python
status(
live_price("BTC"
analyze_market("ETH")
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        # Syntax error should be caught, block skipped
        assert len(calls) == 0
        print("✓ Test 26 (syntax error blocks): PASS")

    def test_27_complex_nested_dict(self):
        """Complex nested dict with mixed types."""
        ai_output = '''```python
analyze_market({"nested": {"key": "value", "num": 42}, "list": [1, 2, 3]})
```'''
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].args[0] == {
            "nested": {"key": "value", "num": 42},
            "list": [1, 2, 3],
        }
        print("✓ Test 27 (complex nested dict): PASS")

    def test_28_empty_list_dict(self):
        """Empty list and dict arguments."""
        ai_output = """```python
analyze_market([])
analyze_market({})
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 2
        assert calls[0].args == [[]]
        assert calls[1].args == [{}]
        print("✓ Test 28 (empty list/dict): PASS")

    def test_29_dict_with_numeric_keys(self):
        """Dict with numeric keys (should work as literals)."""
        ai_output = """```python
analyze_market({1: "one", 2: "two"})
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        assert len(calls) == 1
        assert calls[0].args == [{1: "one", 2: "two"}]
        print("✓ Test 29 (dict with numeric keys): PASS")

    def test_30_realistic_messy_output(self):
        """Realistic messy free model output combining multiple issues."""
        ai_output = """Here's what I recommend:

First, let me check the market status:

```python
# Get current status
status()

# Check BTC and ETH prices
live_price(market="BTC")
live_price("ETH")
```

Then analyze the markets:

```Python
analyze_market("BTC")
fetch_price("BTC")  # This might not work
analyze_market({"coin": "ETH", "depth": 10})
```

Finally, place a trade:

```py
place_trade("BTC", "long", 1.5)
```

That's my analysis!"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)

        # Count valid calls (not hallucinated fetch_price)
        valid_names = {c.name for c in calls}
        assert "fetch_price" not in valid_names, "Hallucinated function was parsed!"
        assert "status" in valid_names
        assert "live_price" in valid_names
        assert "analyze_market" in valid_names
        assert "place_trade" in valid_names

        # Check specific calls
        # Note: There are TWO analyze_market calls (one with string, one with dict)
        assert len(calls) == 6
        assert calls[0].name == "status"
        assert calls[1].name == "live_price"
        assert calls[1].kwargs == {"market": "BTC"}
        assert calls[2].name == "live_price"
        assert calls[2].args == ["ETH"]
        assert calls[3].name == "analyze_market"
        assert calls[3].args == ["BTC"]
        assert calls[4].name == "analyze_market"
        assert calls[4].args == [{"coin": "ETH", "depth": 10}]
        assert calls[5].name == "place_trade"

        print("✓ Test 30 (realistic messy output): PASS")


class TestExecutionWithMockRegistry:
    """Test execution against the mock registry."""

    def test_execute_valid_calls(self):
        """Execute valid calls against mock registry."""
        ai_output = """```python
status()
live_price("BTC")
analyze_market("ETH")
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        results = execute_parsed_calls(calls, MOCK_REGISTRY, write_tools=set())

        assert len(results) == 3
        assert all(r.error is None for r in results)
        assert results[0].name == "status"
        assert results[1].name == "live_price"
        assert results[2].name == "analyze_market"
        print("✓ Test execute valid calls: PASS")

    def test_execute_with_kwargs(self):
        """Execute calls with keyword arguments."""
        ai_output = """```python
live_price(market="BTC")
trade_journal(limit=20)
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        results = execute_parsed_calls(calls, MOCK_REGISTRY, write_tools=set())

        assert len(results) == 2
        assert all(r.error is None for r in results)
        print("✓ Test execute with kwargs: PASS")

    def test_execute_unknown_tool(self):
        """Attempt to execute unknown tool (after registry filtering)."""
        # This shouldn't happen in normal flow because parse_tool_calls filters
        # But test the execute path anyway
        from agent.code_tool_parser import ToolCall

        calls = [ToolCall(name="nonexistent", args=[], kwargs={})]
        results = execute_parsed_calls(calls, MOCK_REGISTRY, write_tools=set())

        assert len(results) == 1
        assert results[0].error is not None
        assert "Unknown tool" in results[0].error
        print("✓ Test execute unknown tool: PASS")

    def test_execute_write_tools_pending(self):
        """Write tools should return pending status."""
        ai_output = """```python
place_trade("BTC", "long", 1.5)
```"""
        calls = parse_tool_calls(ai_output, MOCK_REGISTRY)
        results = execute_parsed_calls(
            calls,
            MOCK_REGISTRY,
            write_tools={"place_trade"}
        )

        assert len(results) == 1
        assert results[0].data.get("_pending") is True
        assert results[0].error is None
        print("✓ Test execute write tools pending: PASS")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
