import json
import logging
from pathlib import Path
from datetime import datetime, timezone
import time

log = logging.getLogger("trade_evaluator")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

def build_system_evaluations() -> str:
    """Build a deterministic evaluation of trading setups to inject into live context."""
    results = []
    
    # Evaluate Short WTI
    short_wti = _evaluate_short_wti()
    if short_wti:
        results.append(short_wti)
    
    # Surface imminent calendar events
    cal_alerts = _evaluate_calendar_alerts()
    if cal_alerts:
        results.append(cal_alerts)
        
    if results:
        return "\n".join(results)
    return ""

def _evaluate_short_wti() -> str:
    """Evaluate the 17-step Oil Short Consideration checklist deterministically."""
    
    # 1. Long-only rule / botpattern subsystem
    bot_config_path = _PROJECT_ROOT / "data" / "config" / "oil_botpattern.json"
    if not bot_config_path.exists():
        return "[SYSTEM EVALUATION: SHORT WTI -> NO_GO. Reason: oil_botpattern config missing.]"
        
    try:
        config = json.loads(bot_config_path.read_text())
    except Exception as e:
        return f"[SYSTEM EVALUATION: SHORT WTI -> NO_GO. Reason: failed to parse config.]"
        
    # 2. short_legs_enabled
    if not config.get("short_legs_enabled", False):
        return "[SYSTEM EVALUATION: SHORT WTI -> NO_GO. Reason: `short_legs_enabled` kill switch is OFF.]"
        
    # 3. Drawdown brakes
    state_path = _PROJECT_ROOT / "data" / "strategy" / "oil_botpattern_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            if state.get("daily_brake_tripped_at") or state.get("weekly_brake_tripped_at") or state.get("monthly_brake_tripped_at"):
                return "[SYSTEM EVALUATION: SHORT WTI -> NO_GO. Reason: Drawdown brake is active/tripped.]"
        except Exception:
            pass
            
    # 6 & 7. Classifier tag & confidence
    patterns_path = _PROJECT_ROOT / "data" / "research" / "bot_patterns.jsonl"
    if patterns_path.exists():
        try:
            lines = patterns_path.read_text().strip().split('\n')
            if lines and lines[-1]:
                latest = json.loads(lines[-1])
                classification = latest.get("classification")
                confidence = latest.get("confidence", 0)
                if classification != "bot_driven_overextension":
                    return f"[SYSTEM EVALUATION: SHORT WTI -> NO_GO. Reason: Latest bot pattern is '{classification}', requires 'bot_driven_overextension'.]"
                if confidence < 0.7:
                    return f"[SYSTEM EVALUATION: SHORT WTI -> NO_GO. Reason: Bot pattern confidence {confidence} < 0.7.]"
        except Exception:
            pass
            
    # 8. High-severity bullish catalyst pending in 24h
    catalysts_path = _PROJECT_ROOT / "data" / "news" / "catalysts.jsonl"
    if catalysts_path.exists():
        try:
            now = datetime.now(timezone.utc)
            lines = [line for line in catalysts_path.read_text().strip().split('\n') if line]
            for line in reversed(lines):
                c = json.loads(line)
                if c.get("severity", 0) >= 4 and c.get("expected_direction") in ["bull", "bullish"]:
                    if c.get("event_date"):
                        try:
                            event_time = datetime.fromisoformat(c["event_date"])
                            if event_time.tzinfo is None:
                                event_time = event_time.replace(tzinfo=timezone.utc)
                            delta = (event_time - now).total_seconds()
                            if -3600 <= delta <= 86400:
                                return f"[SYSTEM EVALUATION: SHORT WTI -> NO_GO. Reason: High-severity bullish catalyst '{c.get('category')}' pending in <24h. Macro thesis intact.]"
                        except ValueError:
                            pass
        except Exception:
            pass
            
    # 9. Supply disruption
    supply_path = _PROJECT_ROOT / "data" / "supply" / "state.json"
    if supply_path.exists():
        try:
            supply = json.loads(supply_path.read_text())
            if supply.get("active_disruption_count", 0) > 0:
                pass # Not a hard NO_GO unless it just happened, but we will defer to the catalyst checks anyway
        except Exception:
            pass
            
    return "[SYSTEM EVALUATION: SHORT WTI -> NO_GO. Reason: Defaulting to NO_GO. Trade setup is not presently qualified deterministically.]"


def _evaluate_calendar_alerts() -> str:
    """Surface imminent calendar events (next 3 days) as deterministic system alerts."""
    from datetime import timedelta

    calendar_dir = _PROJECT_ROOT / "data" / "calendar"
    if not calendar_dir.exists():
        return ""

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=3)
    alerts = []

    # Check rollover calendars
    for rollfile in ["brent_rollover.json"]:
        path = calendar_dir / rollfile
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            for entry in data.get("brent_futures", []):
                ltd = entry.get("last_trading")
                if ltd:
                    try:
                        dt = datetime.fromisoformat(ltd).replace(tzinfo=timezone.utc)
                        days_until = (dt - now).days
                        if -1 <= days_until <= 3:
                            contract = entry.get("contract", "?")
                            if days_until <= 0:
                                alerts.append(f"⚠️ BRENT ROLL {contract} — LAST TRADING TODAY/PAST DUE")
                            else:
                                alerts.append(f"📅 BRENT ROLL {contract} last trading in {days_until}d ({ltd})")
                    except ValueError:
                        pass
        except Exception:
            pass

    # Check quarterly/annual for high-impact events
    for calfile in ["quarterly.json", "annual.json"]:
        path = calendar_dir / calfile
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            for ev in data.get("events", []):
                if ev.get("impact") not in ("high", "critical"):
                    continue
                date_str = ev.get("date")
                if not date_str:
                    continue
                try:
                    dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
                    days_until = (dt - now).days
                    if -1 <= days_until <= 3:
                        name = ev.get("name", "?")
                        if days_until <= 0:
                            alerts.append(f"⚠️ {name} — TODAY/PAST ({date_str})")
                        else:
                            alerts.append(f"📅 {name} in {days_until}d ({date_str})")
                except ValueError:
                    pass
        except Exception:
            pass

    if not alerts:
        return ""

    return "[CALENDAR ALERTS: " + " | ".join(alerts) + "]"
