# Calendar Context

Multi-resolution temporal awareness system for trading decisions. Defined in `common/calendar.py` with private data files in `data/calendar/`.

## Why It Exists

Trading decisions need temporal anchoring. A check during thin weekend liquidity requires different behavior than during US market peak hours. The calendar provides this context automatically so the AI agent and daemon always know "what time it is" in market terms.

## Layers

Eight resolution layers from intraday to multi-decade:

| Layer | Cadence | Examples |
|-------|---------|---------|
| Session | Intraday | Asia/Europe/US open, volume profile, overnight |
| Daily | Key times | Asia open, EU open, US open, settlements |
| Weekly | Weekday norms | Weekend risk, market open/close |
| Monthly/Quarterly | Events | OPEC, Fed, earnings, option expiry, contract rolls |
| Annual/Seasonal | Seasonal | Easter, Christmas, CNY, summer doldrums, tax season |
| 4-Year Political | Cycle | Election cycles, administration policy shifts |
| 4-Year Halving | BTC cycle | Halving season map |
| Credit Cycle | Long-wave | Position in the long-wave credit cycle |

## Session Identification

`SessionInfo` dataclass identifies the current trading session:

- **name**: `asia`, `europe`, `us`, `overnight`, `weekend`
- **phase**: `pre_open`, `open`, `peak`, `close`, `after_hours`
- **volume_profile**: `thin`, `normal`, `heavy`
- **hours_to_next_major**: countdown to next session event
- **user_likely_state**: `sleeping`, `waking`, `active`, `winding_down` (based on AEST since Chris is in Australia)

Time calculations use both US Eastern and AEST for accurate session mapping.

## Usage

`CalendarContext.get_current()` returns a compact summary (~200-300 tokens) of what matters right now. This is injected into the AI agent's context pipeline as "Step 0.5" before any analysis begins.

## Key Design Decision

The calendar recognizes that "people aren't stupid, they look 6-12 months ahead." The system trades the delta between consensus expectation and first-principles analysis, and the calendar layers help identify where that delta is most actionable.

## Data Files

- Event data lives in `data/calendar/*.json`
