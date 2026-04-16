import pytest
from telegram.agent import _parse_text_tool_calls, _strip_tool_calls


def test_parse_valid_tool_calls():
    """Test standard, valid text tool calls."""
    content = 'I should check the price. [TOOL: live_price {"market": "BTC"}] and also [TOOL: account_summary]'
    calls = _parse_text_tool_calls(content)
    
    assert len(calls) == 2
    
    assert calls[0]["function"]["name"] == "live_price"
    assert calls[0]["function"]["arguments"] == {"market": "BTC"}
    assert calls[0]["id"] == "text_live_price"
    
    assert calls[1]["function"]["name"] == "account_summary"
    assert calls[1]["function"]["arguments"] == {}


def test_parse_invalid_json():
    """Test handling of invalid JSON within tool arguments."""
    content = 'Let us see: [TOOL: analyze_market {"coin": "BTC", broken}]'
    calls = _parse_text_tool_calls(content)
    
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "analyze_market"
    # Fallback is to an empty dictionary
    assert calls[0]["function"]["arguments"] == {}


def test_parse_unknown_tool():
    """Test that unauthorized/unknown tools are ignored."""
    # Assuming "launch_nukes" is not in TOOL_DEFS
    content = '[TOOL: launch_nukes {"target": "moon"}]'
    calls = _parse_text_tool_calls(content)
    assert len(calls) == 0


def test_parse_messy_spacing():
    """Test regex resilience against weird spacing."""
    content = 'Checking... [  TOOL:   live_price   { "market" : "xyz:GOLD" }   ]'
    calls = _parse_text_tool_calls(content)
    
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "live_price"
    assert calls[0]["function"]["arguments"] == {"market": "xyz:GOLD"}


def test_strip_tool_calls():
    """Test stripping the tool calls from final responses."""
    content = 'Here is the data [TOOL: live_price {"market": "BTC"}]. Interesting!'
    stripped = _strip_tool_calls(content)
    assert stripped == 'Here is the data . Interesting!'
