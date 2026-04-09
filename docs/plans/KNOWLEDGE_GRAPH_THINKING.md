# Knowledge Graph Thinking Regime — Plan

> **Status:** Proposed. Plan only — no code yet.
> **Date:** 2026-04-09
> **Trigger:** Chris asked: *"I was inspired by thinking regimes of InfraNodus
> knowledge graphs.... I think we should incorporate and manage systems like
> that too, that at least guide LLMs for how to think etc.. How to learn....
> What our style and considerations are etc..."*
> **Horizon:** Horizon 2 (12-24 months) per `NORTH_STAR.md`

---

## What this is

A **graph-structured meta-cognitive layer** that sits between
`agent/AGENT.md` (which says WHO the agent is and what tools it has) and
the LIVE CONTEXT injection (which says WHAT is true right now). The
thinking regime says **HOW** to reason about the current context.

It is *not* a knowledge base for the agent to query. It is *not* a
retrieval-augmented generation index. It is a **meta-cognitive structure**
that says: "when you encounter a decision context of type X, here are the
concepts that should be active, here are the relationships between them,
here's the order to consider them in."

The result is reasoning that is **legible, auditable, and tunable** — we
can read the agent's traversal of the graph and see why it concluded what
it concluded, then adjust the graph structure if the reasoning was wrong.

---

## Why this matters for THIS project

Three concrete pain points it addresses:

### 1. The agent's reasoning is currently flat
`agent/AGENT.md` is a long markdown document the agent reads end-to-end on
every session. It contains rules, tools, formatting guidelines, signal
interpretation hints. It is comprehensive but **flat** — there's no
structure that says "for an oil short decision, walk through THESE concepts
in THIS order." The agent has to re-derive that walk on every prompt.

### 2. Domain knowledge is implicit
Chris's petroleum-engineering edge — supply disruptions, refinery cycles,
geopolitics, OPEC dynamics, inventory math — is captured in fragments
across the supply ledger, the catalyst rules, the wiki oil-knowledge page,
and Chris's chat history. The agent doesn't have a single coherent map of
*what concepts matter for oil*, *how they relate*, *which signals upgrade
or downgrade which others*.

### 3. The dumb-bot reality framework needs a thinking shape
The founding insight is that markets are 80% bots reacting to current
news. To trade with that reality, the agent must reason about: catalyst
proximity → bot prepositioning → magnitude of likely overshoot → liquidity
zones near entry → fade window. That's a **specific reasoning sequence**
that the agent should walk every time it considers a tactical position.
Today it has to figure out the sequence from first principles each time.

A graph-structured thinking regime makes the sequence explicit, persistent,
and improvable.

---

## How it differs from existing systems

| System | What it does | What it's NOT |
|---|---|---|
| `agent/AGENT.md` | Defines the agent persona + tool list + rules | Not structural — flat markdown |
| `agent/SOUL.md` | Defines response style + safety + loop prevention | Not domain-specific |
| Lesson corpus (FTS5) | Stores past trade post-mortems for retrieval | Examples, not concepts |
| Memory consolidation | Compresses old events into summaries | Stores facts, not reasoning shapes |
| Reflect engine | Analyzes closed trades for patterns | Backward-looking, not forward-prescriptive |
| Brutal Review Loop | Audits codebase + trading periodically | Code-level, not decision-level |
| **Knowledge graph thinking regime** | **Defines reasoning shapes for decision contexts** | **Not a knowledge base, not a fact store, not retrieval** |

The closest existing analog in the codebase is the section structure in
`agent/AGENT.md` itself — but that's static text, not a graph the agent
can walk based on context.

---

## Concrete example: an oil short decision

Today, when the agent considers an oil short, it has to:
1. Remember the long-only-oil rule (from AGENT.md)
2. Remember the `oil_botpattern` exception (from AGENT.md or memory)
3. Pull catalyst proximity (from `data/news/catalysts.jsonl`)
4. Pull supply ledger state (from `data/supply/state.json`)
5. Pull liquidity zones (from `data/heatmap/zones.jsonl`)
6. Pull bot classifier signal (from `data/research/bot_patterns.jsonl`)
7. Check past lessons (from `search_lessons` BM25 retrieval)
8. Reason about all of these together
9. Produce a recommendation

There's no explicit structure for HOW to reason about them. The agent
re-derives the structure on every call from the rules in AGENT.md plus
its own judgment.

**With a graph-structured thinking regime**, the decision context "oil
short consideration" would map to a subgraph like:

```
                    [ OIL SHORT DECISION ]
                            |
        ┌───────────────────┼───────────────────┐
        |                   |                   |
   [LEGAL CHECK]       [BOT REGIME]          [FUNDAMENTAL]
        |                   |                   |
   ┌────┼────┐         ┌────┼────┐         ┌────┼────┐
   |    |    |         |    |    |         |    |    |
[long  [oil [tier]  [classi-[heat-[news]  [supply [thesis [funding
only   bot- check]   fier]  map] proxim]   ledger] state]  cost]
rule]  pat-                                                    
       tern                                                    
       sub                                                     
       sys]                                                    
                                                               
        ↓                   ↓                   ↓
   PASS/FAIL          OVERSHOOT-LIKELY     UPGRADE/DOWNGRADE
        ↓                   ↓                   ↓
        └───────────────────┼───────────────────┘
                            ↓
                  [SIZE FROM L0–L5 LADDER]
                            ↓
                  [SUGGESTION TO USER]
```

Each node is a concept the agent must check. Each edge is a relationship
(e.g. "supply_ledger.physical_offline_total > 1.5M bbl/day → upgrade
fundamental score → downgrade short conviction"). The agent walks the
graph in a defined order, checks each node against live context, and
produces a structured reasoning trace.

The graph itself is a YAML or JSON file that humans can read and edit.
When Chris realizes "we should also check OPEC meeting proximity in this
walk," he adds a node to the YAML and the next agent invocation includes
it in the walk. **No code change. No prompt rewrite. No model retrain.**

---

## Architecture sketch

### Storage
- `docs/plans/thinking_graphs/<context_id>.yaml` — one file per decision context
- `docs/plans/thinking_graphs/_concepts.yaml` — shared concept definitions
  (re-used across contexts)
- `docs/plans/thinking_graphs/_relationships.yaml` — shared edge templates

### Module
- `modules/thinking_regime.py` — pure logic
  - Loads YAML graphs
  - Resolves concepts and relationships against live context
  - Walks a graph in topologically sorted order (root → leaves)
  - Produces a structured `ReasoningTrace` object

### Agent integration
- `cli/agent_runtime.py:build_system_prompt()` gets a new section
  injected: `## REASONING REGIME` followed by the relevant graph for the
  current decision context, rendered as a checklist
- Decision context is inferred from the user's message + LIVE CONTEXT
  (e.g. "user is asking about an oil position" → load the oil decision graph)

### Telegram surface
- `/regime` — show the active reasoning graphs
- `/regime <context>` — show one graph
- `/regime add <context> <node>` — add a concept to a graph
- `/regime trace <decision_id>` — show the agent's last walk for a decision

### Storage of walks
Every walk gets persisted to `docs/plans/thinking_graphs/walks.jsonl` (append-only,
naturally — per NORTH_STAR P9). Future analysis: which walks correlated
with profitable trades? Which nodes were most predictive? Which edges
should be reweighted?

This is the part that addresses Chris's "guide LLMs for how to learn"
ask: the walks become training signal for the structure of the graph
itself, not just for the agent's decisions.

---

## Wedges

This is a Horizon 2 plan. Not implemented yet. Wedge plan when greenlit:

### Wedge 1 — Concept catalog + one decision context
- Write `docs/plans/thinking_graphs/_concepts.yaml` with 20-40 concepts covering
  the existing oil reasoning surface (catalyst proximity, supply state,
  bot classification, liquidity zones, lesson recall, conviction sizing,
  drawdown brakes, etc.)
- Write `docs/plans/thinking_graphs/oil_short_decision.yaml` as the first
  context graph
- Pure data, no code

### Wedge 2 — Loader + traversal module
- `modules/thinking_regime.py` — pure logic loader + walker
- Tests: load YAML, resolve concept references, topological sort, walk in
  order, produce a `ReasoningTrace`

### Wedge 3 — Agent prompt injection
- New section in `build_system_prompt()` that injects the relevant graph
  rendered as a checklist
- Decision-context inference: pattern match user messages against
  registered contexts
- Tests: prompt assembly, context detection

### Wedge 4 — Walk persistence + Telegram surface
- Persist walks to `walks.jsonl`
- `/regime` Telegram commands per the surface above
- 5-surface registration

### Wedge 5 — Graph editing in Telegram
- `/regime add`, `/regime remove`, `/regime weight` for live graph editing
  from the phone
- Append-only edit log so graph evolution is auditable

### Wedge 6 — Walk analysis (the "learn" piece)
- For each walk that resulted in a closed trade, correlate which nodes
  were active with the trade outcome
- Produce a weekly `/regime stats` report showing which concepts most
  predicted wins vs losses
- This is the meta-learning loop — the graph improves itself based on
  trade outcomes, but only ever within bounded edits (per the L0–L5
  contract — the graph **structure** still requires a human tap to
  change)

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Graph becomes a maintenance burden | Limit to 3-5 decision contexts max. Don't try to model every reasoning shape. The graph is for *high-leverage* decisions, not for routine ones. |
| Agent ignores the graph and reasons freely | Test by asking the agent to produce a trace. If the trace doesn't reference graph nodes, the prompt injection isn't strong enough. |
| Graph contradicts AGENT.md | Make graphs ADDITIVE — they layer on top of AGENT.md, never replace its rules. Conflicts default to AGENT.md. |
| Graph becomes a substitute for thinking | The graph is a *checklist*, not a *script*. The agent still produces narrative reasoning; the graph just ensures it covered the right concepts. |
| Premature optimization | Start with ONE context (oil short decision) and iterate. Don't model BTC, gold, silver until oil shorts are working well. |

---

## Why InfraNodus specifically inspired this

InfraNodus represents text as a graph where concepts are nodes and
relationships are edges, then computes which concepts are central, which
are bridges, and which are isolated. The insight is that **structure
matters as much as content** — a coherent thought has a navigable graph
shape, an incoherent one doesn't.

The trading agent's reasoning today has CONTENT (the rules, the tools,
the live context) but no STRUCTURE — every prompt re-derives the shape.
Borrowing the InfraNodus framing: give the agent's reasoning a graph
shape, and the shape becomes editable, auditable, and improvable
independently of the content.

This is not about replicating InfraNodus the product. It's about
borrowing the *idea* that structure-as-data is a valid way to guide a
language model.

---

## Definition of done (for the whole plan)

- One decision context ("oil short consideration") has a graph
- The agent uses the graph in its reasoning on real decisions
- Chris can edit the graph via Telegram and see the change reflected
  in the next decision
- A walk log accumulates over time, ready for the wedge 6 meta-learning
  analysis
- The structure does NOT need a human tap for parameter tuning (edge
  weights) but DOES need a human tap for structural changes (new nodes,
  new contexts) — per the L0–L5 contract

---

## What this plan deliberately does NOT do

- Does NOT replace `agent/AGENT.md`. Layer on top.
- Does NOT introduce a graph database. YAML files + Python dict walking.
- Does NOT use embeddings or vector search. The graph is symbolic.
- Does NOT auto-rewrite itself. Edits are explicit.
- Does NOT become the primary source of agent reasoning. The agent
  still has full freedom — the graph is a checklist, not a script.

---

## Versioning

Same convention as MASTER_PLAN.md and NORTH_STAR.md. Archive + rewrite
when the design shifts.

> Past versions: see `docs/plans/archive/`.
