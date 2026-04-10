# Constitution — How We Build

> Rules of conduct, not vision. NORTH_STAR says what we're building and why.
> This document says HOW we build and what we don't do.
> Approved 2026-04-11.

---

## 1. We build apps and embed intelligence into them

We don't build AI agents and wrap apps around them. That's Anthropic's
game, not ours. We build a trading application — data pipelines,
protection chains, risk gates, thesis contracts, daemon ticks — and
embed expert-trained models and machine learning systems natively into
the app to bring it alive.

The models live inside the app. Their outputs, their connections to the
outside world, their ability to act — all bounded by the app's
structure. But within those bounds, they're fully intelligent. The app
grounds the AI; it doesn't muzzle it.

General-purpose AI (Claude Code, Opus sessions) helps write the code
and conduct research. It doesn't run the system day to day. Day-to-day
operations run on specialised, embedded intelligence that grows with
the user and the data.

## 2. The app grows from a small spawn point

This isn't a general-purpose platform. It starts small — one market,
one thesis, manual authority, WATCH tier — and grows as the user's
confidence and data accumulate. Every capability exists in code before
it activates in production. Activation is deliberate: kill switches,
tier promotion, delegation.

Code that isn't wired yet is in development. It waits for data, for
tier promotion, for the user's go-ahead. It is never deleted without
explicit approval.

## 3. The harness is the value

The trading harness — trade evaluator, protection chain, conviction
engine, calendar system, supply ledger, bot classifier — is the
codified domain expertise. It IS the product. Models come and go.
The harness persists, grows, and compounds.

The harness provides deterministic truth: "this setup is GO/NO_GO",
"drawdown brakes are active", "WTI rolls in 2 days". The AI receives
this truth and synthesises it with its own intelligence — it
interprets, challenges, advises, acts. Both are valuable. Neither
dominates.

Over time, an LLM can be trained on the harness itself — absorbing
the domain expertise into model weights. But financial transactions
always flow through deterministic code, because you cannot hallucinate
money movements. The harness bounds outputs; the AI enriches inputs.

Agents are only useful when results are predictable and repeatable.
Code is exactly that. We place huge emphasis on the harness because
it makes the AI's outputs predictable and repeatable. This is
different from how most of the world builds AI apps. We're not
wrapping a general agent in domain chrome — we're building domain-
expert infrastructure and embedding AI natively into it.

## 4. Open source and free — no subscription lock-in

The system runs without ongoing payments to any AI provider. Session
tokens today, local models tomorrow, OpenRouter free tier as fallback.
The architecture never locks into a provider. When free credits expire,
the system downgrades gracefully — smaller models, fewer LLM calls,
more deterministic paths — but never stops working.

## 5. Cheap models for mechanical work, premium for judgment

Background tasks (tool dispatch, dream, compaction, lesson authoring,
triage classification) use the cheapest adequate model. The final
synthesis — the judgment call the user reads and acts on — uses the
model the user selected. This is architecture, not cost-cutting: the
app is smart enough that mechanical tasks don't need expensive models.

## 6. Never delete, always preserve

Disable rather than delete. Archive rather than overwrite. Append
rather than edit. Gate behind kill switches. Fix broken things, park
obsolete things with resume conditions. Git history is not a
substitute for keeping code accessible.

## 7. Every surface tells the truth

Commands that crash lie. Dashboards showing "Online" when the daemon
is dead lie. Tool lists with phantom functions make the AI hallucinate.
Every user-facing surface reflects the actual system state. When
something isn't ready, say so clearly — never show a traceback.

## 8. Alerts on transitions, not steady state

The user's attention is scarce. Alert when something changes. Be
silent when nothing has.

## 9. Data flows complete end-to-end

Every pipeline needs a writer and a reader that agree on the path and
format. A writer nobody reads is waste. A reader nobody writes to is
a lie.

## 10. Fix the thing, not the surroundings

When fixing a bug, change only the code related to that bug. Scope
creep causes regressions. The codebase is load-bearing and running on
real money.
