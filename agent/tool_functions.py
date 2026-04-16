"""Unified tool core — pure functions returning dicts.

Single source of truth for all tool logic. Consumed by:
- AI agent (via code_tool_parser → tool_renderers.render_for_ai)
- Telegram commands (via tool_renderers.render_for_telegram) [future]
- agent_tools.py (thin wrappers for backward compat)

Every function returns a dict. No formatting, no Telegram, no AI concerns.
"""
from __future__ import annotations

import difflib
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("tools")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HL_API = "https://api.hyperliquid.xyz/info"


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _hl_post(payload: dict) -> Any:
    try:
        return requests.post(_HL_API, json=payload, timeout=10).json()
    except Exception:
        return {}


def _resolve_main_wallet() -> Optional[str]:
    from common.account_resolver import resolve_main_wallet
    return resolve_main_wallet(required=False)


def _coin_matches(universe_name: str, target: str) -> bool:
    """Handle xyz: prefix normalization for coin matching."""
    bare_uni = universe_name.replace("xyz:", "") if universe_name.startswith("xyz:") else universe_name
    bare_tgt = target.replace("xyz:", "") if target.startswith("xyz:") else target
    return bare_uni.upper() == bare_tgt.upper()


# ═══════════════════════════════════════════════════════════════════════
# READ Tools
# ═══════════════════════════════════════════════════════════════════════

def status() -> dict:
    """Account equity, open positions with entry/uPnL/leverage/liq, spot balances."""
    from common.account_state import fetch_registered_account_state

    bundle = fetch_registered_account_state()
    if not bundle.get("accounts"):
        return {"error": "No wallet configured"}

    return {
        "equity": round(float(bundle["account"]["total_equity"]), 2),
        "positions": [
            {
                "coin": p["coin"],
                "direction": "LONG" if float(p["size"]) > 0 else "SHORT",
                "size": abs(float(p["size"])),
                "entry_px": float(p["entry"]),
                "upnl": float(p["upnl"]),
                "leverage": p["leverage"],
                "liquidation_px": float(p["liq"]) if p.get("liq") and p["liq"] != "N/A" else None,
                "dex": p["dex"],
                "account": p.get("account_label", p.get("account_role")),
            }
            for p in bundle.get("positions", [])
        ],
        "spot": [
            {"coin": bal["coin"], "total": bal["total"], "account": row["label"]}
            for row in bundle.get("accounts", [])
            for bal in row.get("spot_balances", [])
        ],
    }


def live_price(market: str = "all") -> dict:
    """Current mid prices for watched markets or a specific one."""
    mids = _hl_post({"type": "allMids"})
    mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
    mids.update(mids_xyz)

    if market.lower() != "all":
        for k, v in mids.items():
            if market.lower() in k.lower():
                return {"prices": {k: float(v)}}
        return {"error": f"No price found for '{market}'"}

    from common.watchlist import get_watchlist_coins
    watchlist = get_watchlist_coins()
    prices = {}
    for k in watchlist:
        if k in mids:
            prices[k] = float(mids[k])
    return {"prices": prices}


def analyze_market(coin: str) -> dict:
    """Technicals: trend, S/R, ATR, BBands, volume, signals."""
    try:
        from engines.data.candle_cache import CandleCache
        from engines.analysis.market_snapshot import build_snapshot, render_snapshot, render_signal_summary

        mids = _hl_post({"type": "allMids"})
        mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
        mids.update(mids_xyz)
        price = float(mids.get(coin, 0))
        if not price:
            return {"error": f"No price data for {coin}"}

        cache = CandleCache()
        snap = build_snapshot(coin, cache, price)
        technicals_text = render_snapshot(snap, detail="full")
        signals_text = render_signal_summary(snap)
        return {
            "coin": coin,
            "price": price,
            "technicals": technicals_text,
            "signals": signals_text,
        }
    except Exception as e:
        return {"error": f"Analysis error: {e}"}


def market_brief(market: str) -> dict:
    """Full market context: price, technicals, position, thesis, memory."""
    try:
        from common.account_state import fetch_registered_account_state
        from agent.context_harness import build_thesis_context

        account_state = fetch_registered_account_state()

        snapshot_text = None
        try:
            from engines.data.candle_cache import CandleCache
            from engines.analysis.market_snapshot import build_snapshot, render_snapshot
            mids = _hl_post({"type": "allMids"})
            mids_xyz = _hl_post({"type": "allMids", "dex": "xyz"})
            mids.update(mids_xyz)
            price = float(mids.get(market, 0))
            if price:
                cache = CandleCache()
                snap = build_snapshot(market, cache, price)
                snapshot_text = render_snapshot(snap, detail="standard")
        except Exception:
            pass

        result = build_thesis_context(
            market=market,
            account_state=account_state,
            market_snapshot_text=snapshot_text,
            token_budget=1500,
        )
        return {"market": market, "brief": result.text}
    except Exception as e:
        return {"error": f"Error building market brief: {e}"}


def check_funding(coin: str) -> dict:
    """Funding rates, OI, volume for a market."""
    bare = coin.replace("xyz:", "") if coin.startswith("xyz:") else coin
    lookup_variants = {bare, f"xyz:{bare}", coin, coin.upper(), bare.upper()}

    for dex in ['', 'xyz']:
        payload: dict = {"type": "metaAndAssetCtxs"}
        if dex:
            payload["dex"] = dex
        data = _hl_post(payload)
        if isinstance(data, list) and len(data) >= 2:
            universe = data[0].get("universe", [])
            ctxs = data[1]
            for i, ctx in enumerate(ctxs):
                name = universe[i].get("name", "") if i < len(universe) else ""
                if name in lookup_variants or name.replace("xyz:", "") in lookup_variants:
                    funding = float(ctx.get("funding", 0))
                    oi = float(ctx.get("openInterest", 0))
                    vol = float(ctx.get("dayNtlVlm", 0))
                    mark = float(ctx.get("markPx", 0))
                    prev = float(ctx.get("prevDayPx", 0))
                    change = ((mark - prev) / prev * 100) if prev > 0 else 0
                    display = name.replace("xyz:", "") if name.startswith("xyz:") else name
                    return {
                        "coin": display,
                        "price": mark,
                        "change_24h_pct": round(change, 2),
                        "funding_rate": funding,
                        "funding_ann_pct": round(funding * 100 * 24 * 365, 1),
                        "oi": oi,
                        "volume_24h": vol,
                    }

    return {"error": f"No funding data for {coin}"}


def get_orders() -> dict:
    """All open orders (trigger, limit, stop) across both clearinghouses."""
    addr = _resolve_main_wallet()
    if not addr:
        return {"error": "No wallet configured"}

    orders = []
    for dex in ['', 'xyz']:
        payload: dict = {"type": "openOrders", "user": addr}
        if dex:
            payload["dex"] = dex
        raw = _hl_post(payload) or []
        for o in raw:
            orders.append({
                "coin": o.get("coin", "?"),
                "side": "BUY" if o.get("side") == "B" else "SELL",
                "size": o.get("sz"),
                "price": o.get("limitPx"),
                "type": o.get("orderType", "limit"),
            })
    return {"orders": orders}


def trade_journal(limit: int = 10) -> dict:
    """Recent trade records with PnL."""
    trades_path = _PROJECT_ROOT / "data" / "research" / "trades"
    if not trades_path.exists():
        return {"entries": []}

    files = sorted(trades_path.glob("*.json"), reverse=True)[:limit]
    entries = []
    for f in files:
        try:
            t = json.loads(f.read_text())
            entries.append({
                "timestamp": t.get("timestamp", f.stem)[:10],
                "coin": t.get("coin", "?"),
                "side": t.get("side", "?"),
                "size": t.get("size", "?"),
                "price": t.get("price", "?"),
                "pnl": t.get("pnl", "?"),
            })
        except Exception:
            pass
    return {"entries": entries}


def thesis_state(market: str = "all") -> dict:
    """Current thesis conviction, direction, age for markets."""
    thesis_dir = _PROJECT_ROOT / "data" / "thesis"
    if not thesis_dir.exists():
        return {"theses": {}}

    results = {}
    for path in thesis_dir.glob("*_state.json"):
        try:
            data = json.loads(path.read_text())
            mkt = data.get("market", path.stem.replace("_state", ""))
            if market != "all" and not _coin_matches(mkt, market):
                continue
            results[mkt] = {
                "direction": data.get("direction", "flat"),
                "conviction": data.get("conviction", 0),
                "summary": data.get("thesis_summary", ""),
                "updated_at": data.get("updated_at", ""),
            }
        except Exception:
            pass
    return {"theses": results}


def daemon_health() -> dict:
    """Daemon status: tier, tick count, strategies, risk gate."""
    try:
        state_path = _PROJECT_ROOT / "data" / "daemon" / "daemon_state.json"
        if not state_path.exists():
            return {"error": "Daemon state file not found"}
        data = json.loads(state_path.read_text())
        return {
            "tier": data.get("tier", "unknown"),
            "tick": data.get("tick", 0),
            "gate": data.get("gate", "unknown"),
            "last_tick_at": data.get("last_tick_at", ""),
            "strategies": data.get("active_strategies", []),
        }
    except Exception as e:
        return {"error": f"Daemon health error: {e}"}


# ═══════════════════════════════════════════════════════════════════════
# WRITE Tools (require approval in AI context)
# ═══════════════════════════════════════════════════════════════════════

def place_trade(coin: str, side: str, size: float) -> dict:
    """Place a market order. Only called after user approval."""
    try:
        from cli.hl_adapter import DirectHLProxy
        proxy = DirectHLProxy()
        is_buy = side.lower() in ("buy", "long", "b")
        result = proxy.market_order(coin=coin, is_buy=is_buy, sz=float(size))
        return {"filled": True, "coin": coin, "side": side, "size": size, "result": str(result)}
    except Exception as e:
        return {"error": f"Trade failed: {e}"}


def update_thesis(market: str, direction: str, conviction: float, summary: str = "") -> dict:
    """Update thesis conviction file. Only called after user approval."""
    try:
        thesis_dir = _PROJECT_ROOT / "data" / "thesis"
        thesis_dir.mkdir(parents=True, exist_ok=True)

        safe_name = market.replace(":", "_").replace("/", "_")
        path = thesis_dir / f"{safe_name}_state.json"
        if path.exists():
            data = json.loads(path.read_text())
            old_conviction = data.get("conviction", 0)
        else:
            data = {"market": market}
            old_conviction = 0

        data["direction"] = direction
        data["conviction"] = conviction
        if summary:
            data["thesis_summary"] = summary
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data["last_evaluation_ts"] = int(time.time() * 1000)

        path.write_text(json.dumps(data, indent=2) + "\n")
        return {
            "updated": True,
            "market": market,
            "direction": direction,
            "old_conviction": old_conviction,
            "new_conviction": conviction,
        }
    except Exception as e:
        return {"error": f"Thesis update failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════
# General Tools — codebase, memory, web, shell
# ═══════════════════════════════════════════════════════════════════════

_MEMORY_DIR = _PROJECT_ROOT / "data" / "agent_memory"
_BLOCKED_COMMANDS = {"rm -rf", "rm -r /", "mkfs", "dd if=", "> /dev/", "shutdown", "reboot", "halt"}

# ── Harness helpers ──────────────────────────────────────────────────

_MAX_DIFF_LINES = 80  # Cap diff output to keep tool results reasonable


def _compute_diff(path: str, old_content: str, new_content: str) -> str:
    """Compute a unified diff between old and new content, capped at _MAX_DIFF_LINES."""
    diff_lines = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))
    if not diff_lines:
        return "(no changes)"
    if len(diff_lines) > _MAX_DIFF_LINES:
        diff_lines = diff_lines[:_MAX_DIFF_LINES]
        diff_lines.append(f"\n... truncated ({len(diff_lines)} lines shown)\n")
    return "".join(diff_lines)


def _auto_test(changed_path: str) -> Optional[dict]:
    """Run pytest if a .py file was changed. Returns test summary or None.

    Harness pattern from Codex/nano-claude-code: feed test results back to
    the model so it can self-correct without a human pointing out failures.
    """
    if not changed_path.endswith(".py"):
        return None
    try:
        result = subprocess.run(
            [str(_PROJECT_ROOT / ".venv" / "bin" / "python"), "-m", "pytest",
             "tests/", "-x", "-q", "--tb=short", "--no-header"],
            capture_output=True, text=True, timeout=60,
            cwd=str(_PROJECT_ROOT),
        )
        # Cap output
        stdout = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout
        stderr = result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr
        return {
            "passed": result.returncode == 0,
            "returncode": result.returncode,
            "output": stdout.strip(),
            "errors": stderr.strip() if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "output": "pytest timed out (60s)", "errors": ""}
    except FileNotFoundError:
        return None  # No venv/pytest — skip silently
    except Exception as e:
        log.debug("Auto-test skipped: %s", e)
        return None


def read_file(path: str) -> dict:
    """Read a file from the project. Path relative to project root."""
    try:
        target = (_PROJECT_ROOT / path).resolve()
        if not str(target).startswith(str(_PROJECT_ROOT)):
            return {"error": f"Path outside project: {path}"}
        if not target.exists():
            return {"error": f"File not found: {path}"}
        if target.stat().st_size > 100_000:
            content = target.read_text()[:100_000]
            return {"path": path, "content": content, "truncated": True}
        return {"path": path, "content": target.read_text()}
    except Exception as e:
        return {"error": f"read_file failed: {e}"}


def search_code(pattern: str, path: str = ".") -> dict:
    """Grep the codebase for a pattern. Returns matching lines."""
    import subprocess
    try:
        target = (_PROJECT_ROOT / path).resolve()
        if not str(target).startswith(str(_PROJECT_ROOT)):
            return {"error": f"Path outside project: {path}"}
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.md", "--include=*.json",
             "-I", pattern, str(target)],
            capture_output=True, text=True, timeout=15,
        )
        lines = result.stdout.strip().split("\n")[:50]  # cap at 50 matches
        # Strip project root prefix for cleaner output
        root_str = str(_PROJECT_ROOT) + "/"
        lines = [l.replace(root_str, "") for l in lines if l.strip()]
        return {"pattern": pattern, "matches": lines, "count": len(lines)}
    except subprocess.TimeoutExpired:
        return {"error": "Search timed out (15s limit)"}
    except Exception as e:
        return {"error": f"search_code failed: {e}"}


def list_files(pattern: str) -> dict:
    """List files matching a glob pattern relative to project root."""
    try:
        matches = sorted(str(p.relative_to(_PROJECT_ROOT)) for p in _PROJECT_ROOT.glob(pattern)
                        if p.is_file() and ".venv" not in str(p) and "__pycache__" not in str(p))
        return {"pattern": pattern, "files": matches[:100], "count": len(matches)}
    except Exception as e:
        return {"error": f"list_files failed: {e}"}


def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web using DuckDuckGo (via ddgs package). No API key needed.

    Note: was previously importing the legacy `duckduckgo_search` package which
    was renamed to `ddgs` upstream. The legacy package now silently returns
    empty results, which is why the audit reported "web search broken".
    """
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return {
            "query": query,
            "results": [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href") or r.get("url", ""),
                    "snippet": r.get("body") or r.get("description", ""),
                }
                for r in results
            ],
        }
    except ImportError:
        return {"error": "ddgs not installed. Run: pip install ddgs"}
    except Exception as e:
        return {"error": f"web_search failed: {e}"}


# Per NORTH_STAR P10 / Critical Rule 11: agent memory files are
# AGENT-WRITABLE via memory_write + the dream cycle. Without a read
# cap, a runaway dream that writes a 100KB MEMORY.md or topic file
# would inflate the agent's tool result on the next read. The cap
# is generous (20KB ≈ 5000 tokens) — any reasonable memory file
# fits without truncation, but a runaway is bounded.
_MEMORY_READ_CAP = 20_000


def _read_memory_capped(path) -> str:
    """Read a memory file with the P10 hard cap. Returns the (possibly
    truncated) text. Truncation is marked inline so the agent knows it
    happened."""
    text = path.read_text()
    if len(text) > _MEMORY_READ_CAP:
        return text[:_MEMORY_READ_CAP] + "\n\n[... TRUNCATED at 20KB cap per NORTH_STAR P10 — file is too large, investigate.]"
    return text


def memory_read(topic: str = "index") -> dict:
    """Read agent memory. 'index' returns MEMORY.md, otherwise reads topic file.

    Hard-bounded per NORTH_STAR P10 / Critical Rule 11: each file is
    capped at 20KB before being returned to the caller. The cap protects
    against agent-writable inputs (memory_write, dream cycle) inflating
    tool results unbounded.
    """
    try:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        if topic == "index" or topic == "all":
            index_path = _MEMORY_DIR / "MEMORY.md"
            if not index_path.exists():
                return {"topic": "index", "content": "(empty — no memories yet)"}
            return {"topic": "index", "content": _read_memory_capped(index_path)}
        topic_path = _MEMORY_DIR / f"{topic}.md"
        if not topic_path.exists():
            # List available topics
            available = [f.stem for f in _MEMORY_DIR.glob("*.md") if f.name != "MEMORY.md"]
            return {"error": f"Topic '{topic}' not found. Available: {', '.join(available) or '(none)'}"}
        return {"topic": topic, "content": _read_memory_capped(topic_path)}
    except Exception as e:
        return {"error": f"memory_read failed: {e}"}


def memory_write(topic: str, content: str) -> dict:
    """Write to agent memory. Creates/updates a topic file and the index."""
    try:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        topic_path = _MEMORY_DIR / f"{topic}.md"
        topic_path.write_text(content)
        # Update index
        index_path = _MEMORY_DIR / "MEMORY.md"
        topics = sorted(f.stem for f in _MEMORY_DIR.glob("*.md") if f.name != "MEMORY.md")
        index_lines = ["# Agent Memory\n", "Topic files maintained by the embedded AI agent.\n"]
        for t in topics:
            first_line = (_MEMORY_DIR / f"{t}.md").read_text().split("\n")[0].strip("# ").strip()
            index_lines.append(f"- [{t}.md]({t}.md) — {first_line[:80]}")
        index_path.write_text("\n".join(index_lines) + "\n")
        return {"topic": topic, "status": "saved", "index_updated": True}
    except Exception as e:
        return {"error": f"memory_write failed: {e}"}


def edit_file(path: str, old_str: str, new_str: str) -> dict:
    """Edit a file by replacing old_str with new_str. Claude Code pattern.

    Harness improvements:
    - Returns unified diff so the model sees exactly what changed
    - Auto-runs pytest if a .py file was edited, feeding results back
    """
    try:
        target = (_PROJECT_ROOT / path).resolve()
        if not str(target).startswith(str(_PROJECT_ROOT)):
            return {"error": f"Path outside project: {path}"}
        if not target.exists():
            return {"error": f"File not found: {path}"}
        content = target.read_text()
        if old_str not in content:
            return {"error": f"old_str not found in {path}"}
        count = content.count(old_str)
        if count > 1:
            return {"error": f"old_str matches {count} times in {path} — must be unique"}
        new_content = content.replace(old_str, new_str, 1)
        # Create backup before editing
        backup_path = target.with_suffix(target.suffix + ".bak")
        backup_path.write_text(content)
        target.write_text(new_content)

        # Compute diff for model awareness
        diff = _compute_diff(path, content, new_content)

        result = {
            "path": path,
            "status": "edited",
            "replacements": 1,
            "backup": str(backup_path.relative_to(_PROJECT_ROOT)),
            "diff": diff,
        }

        # Auto-test: run pytest if .py file changed
        test_result = _auto_test(path)
        if test_result is not None:
            result["auto_test"] = test_result
            if not test_result["passed"]:
                result["status"] = "edited_tests_failing"

        return result
    except Exception as e:
        return {"error": f"edit_file failed: {e}"}


def run_bash(command: str) -> dict:
    """Run a shell command in the project directory. 30s timeout.

    Harness: auto-runs pytest when the command appears to modify .py files
    (sed, tee, write operations). Feeds test results back to the model.
    """
    try:
        for blocked in _BLOCKED_COMMANDS:
            if blocked in command:
                return {"error": f"Blocked command pattern: {blocked}"}
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=30, cwd=str(_PROJECT_ROOT),
        )
        output = result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout
        stderr = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr
        resp = {
            "command": command,
            "returncode": result.returncode,
            "stdout": output,
            "stderr": stderr,
        }

        # Auto-test if the command likely modifies Python files
        _PY_MODIFY_HINTS = (".py", "sed ", "tee ", ">>", "> ", "mv ", "cp ")
        if any(hint in command for hint in _PY_MODIFY_HINTS):
            test_result = _auto_test("dummy.py")  # force trigger
            if test_result is not None:
                resp["auto_test"] = test_result

        return resp
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out (30s): {command}"}
    except Exception as e:
        return {"error": f"run_bash failed: {e}"}


def get_errors(limit: int = 10) -> dict:
    """Get recent agent errors from diagnostics log."""
    try:
        errors_file = _PROJECT_ROOT / "data" / "diagnostics" / "errors.jsonl"
        if not errors_file.exists():
            return {"errors": [], "count": 0}
        lines = errors_file.read_text().strip().split("\n")
        recent = []
        for line in lines[-limit:]:
            try:
                entry = json.loads(line)
                recent.append({
                    "time": entry.get("ts", ""),
                    "event": entry.get("event", ""),
                    "details": str(entry.get("data", ""))[:200],
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return {"errors": recent, "count": len(recent)}
    except Exception as e:
        return {"error": f"get_errors failed: {e}"}


def get_feedback(limit: int = 10) -> dict:
    """Get recent user feedback from /feedback command."""
    try:
        feedback_file = _PROJECT_ROOT / "data" / "feedback.jsonl"
        if not feedback_file.exists():
            return {"feedback": [], "count": 0}
        lines = feedback_file.read_text().strip().split("\n")
        recent = []
        for line in lines[-limit:]:
            try:
                entry = json.loads(line)
                recent.append({
                    "time": entry.get("timestamp", ""),
                    "text": entry.get("text", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return {"feedback": recent, "count": len(recent)}
    except Exception as e:
        return {"error": f"get_feedback failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════

TOOL_REGISTRY: Dict[str, Any] = {
    "status": status,
    "live_price": live_price,
    "analyze_market": analyze_market,
    "market_brief": market_brief,
    "check_funding": check_funding,
    "get_orders": get_orders,
    "trade_journal": trade_journal,
    "thesis_state": thesis_state,
    "daemon_health": daemon_health,
    "place_trade": place_trade,
    "update_thesis": update_thesis,
    "read_file": read_file,
    "search_code": search_code,
    "list_files": list_files,
    "web_search": web_search,
    "memory_read": memory_read,
    "memory_write": memory_write,
    "edit_file": edit_file,
    "run_bash": run_bash,
    "get_errors": get_errors,
    "get_feedback": get_feedback,
    # Back-compat aliases
    "account_summary": status,
}

WRITE_TOOLS = {"place_trade", "update_thesis", "memory_write", "edit_file", "run_bash"}

# Tool descriptions for system prompt injection
TOOL_DESCRIPTIONS = {
    "status": "Account equity, positions, spot balances",
    "live_price": "Current prices for watched markets or specific market",
    "analyze_market": "Technical analysis: trend, S/R, ATR, BBands, signals",
    "market_brief": "Full market context: price, technicals, thesis, memory",
    "check_funding": "Funding rate, OI, volume for a market",
    "get_orders": "All open orders across clearinghouses",
    "trade_journal": "Recent trade history with PnL",
    "thesis_state": "Current thesis conviction and direction",
    "daemon_health": "Daemon status: tier, tick, strategies",
    "place_trade": "Place a market order (requires approval)",
    "update_thesis": "Update thesis conviction (requires approval)",
    "read_file": "Read any project file",
    "search_code": "Grep the codebase for a pattern",
    "list_files": "List files matching a glob pattern",
    "web_search": "Search the web (DuckDuckGo)",
    "memory_read": "Read agent memory files",
    "memory_write": "Write to agent memory (requires approval)",
    "edit_file": "Edit a file by string replacement (requires approval)",
    "run_bash": "Run a shell command (requires approval)",
    "get_errors": "Recent agent errors from diagnostics",
    "get_feedback": "Recent user feedback from /feedback",
}
