# Stage 3: Agentic tracing, the payoff (20 min, Claret)

## Goal

The thesis, made visible. A waterfall says 200 OK while an agent loops,
re-plans, and burns tokens. This stage shows the signals that actually explain
**why the agent did what it did, and what it cost**, live, in Naira.

This is the climax. Slow down here.

## Pre-flight

- Grafana at http://localhost:3000, dashboard **"Oja Connect: Agent
  Observability"** (URL: `/d/oja-agent-obs`).
- Set the time range to **Last 30 minutes**, refresh **10s**.
- Drive 3 or 4 turns beforehand so every panel has data. Then during the stage
  you drive more to make the panels MOVE live.
- Know these panels by number: 1 cache ratio, 2 tokens, 3/4a cost, 4b inference
  calls per turn, 5 tool calls per turn, 6 tool p95 + workflow, 7 slow/high
  token traces, 8 Conversations.

## Script

### 1. The frame (1 min)

- "APM was built for services that either work or throw. An agent can loop,
  call the wrong tool, or overthink, and still return a healthy 200 in normal
  latency. So we need different numbers."

### 2. Did the cache work? (5 min, the headline)

- Panel **1, Context cache hit ratio** (`oja_llm_cached_input_tokens_sum /
  oja_llm_input_tokens_sum`).
- Explain: we run App-level context caching so the big stable prompt prefix is
  cached. The question is whether it is actually working.
- **Drive it live:** start a NEW conversation (cold cache), do 3 or 4 turns in
  the same thread. Watch the ratio **climb from near zero toward the cache
  hit rate** as the shared prefix gets cached across turns.
- Land it: **"That climbing line is money. Cached input tokens are billed at a
  fraction of the rate."** Cross-reference panel 3/4a: cost per turn, shown in
  **USD and Naira** (`oja_llm_cost_ngn`). "This conversation cost about X Naira,
  and the cache is why it is not more."
- The deeper point: OpenTelemetry has no cost attribute at all; cost is always
  tokens times a price table, computed downstream. And the popular
  instrumentor path silently DROPS the Gemini cache-read tokens, so most teams
  cannot even see this. We send ADK-native telemetry precisely to keep it.

### 3. Did it change its mind? (5 min)

- Panel **4b, Inference calls per agent turn.** One model call is a straight
  answer. Several means a tool loop or a re-plan.
- **Drive it live:** ask something that forces work, for example an **express
  ("fly it") delivery quote to London**. That fans out to a live flight-fare
  lookup and back, so the turn takes multiple model calls and tool calls. Watch
  **4b and panel 5 (tool calls per turn) jump.**
- Land it: **"That spike is the agent re-planning, as a number you can chart and
  alert on. A waterfall would just show a slightly longer green bar."**
- Bonus, open the trace for that express turn in Tempo: you can see the
  **workflow route** (express vs standard) and an **agent.handoff** event where
  it delegated to the flight-fare sub-agent. Decisions as observable events.

### 4. Follow one buyer (4 min)

- Panel **8, Conversations.** Each row is one turn (one message). Every turn
  carries `gen_ai.conversation.id` (the thread id).
- Paste a conversation id into the **Conversation-id** dashboard variable to
  collapse the table to just that buyer's conversation, turn by turn. Click a
  turn to open its trace, then trace-to-logs into the exact prompt and response.
- Land it: **"Per-conversation observability, entirely in the Grafana stack you
  already run. No new vendor."**

### 5. The one thing Grafana cannot do, and the plus (3 min, optional)

- Grafana truncates prompt bodies at 2048 bytes. If you want the FULL prompt and
  completion rendered nicely, that is the one gap.
- If you enabled the Langfuse overlay
  (`docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d`),
  open the SAME trace in Langfuse Cloud: structure-only in Grafana, full content
  in Langfuse, side by side. Same native OTel spans, fanned out to both.
- Frame it correctly: **Grafana is the primary surface and answers almost
  everything. Langfuse is a plus for reading the payload, not a dependency.** If
  the overlay is not running, just say this; do not scramble to start it live.

### 6. Restate the thesis (2 min)

- "Latency and 200s tell you the plumbing is fine. These numbers, cache hits,
  cost per turn, calls per turn, the route it took, tell you whether the AGENT
  is fine. That is agentic observability, and almost none of it needed a new
  tool. ADK already computes it. We just turned it on and pointed it somewhere."

## Key points

- Cache-hit ratio is the best single live demo; it is money you can watch.
- Inference-calls-per-turn is "did it re-plan" as a metric.
- Route and handoff are decisions as events.
- Per-conversation is a Grafana capability, not a Langfuse one.
- Cost is derived (tokens times price), in USD and Naira.

## The aha moment

The cache ratio climbing as you drive turns, next to the cost panel. The room
watches the system get cheaper in real time, and understands that a waterfall
would have shown them nothing.

## If it breaks

- **A panel says No data:** the OTLP-to-Prometheus exporter suffixes metric
  names (`_sum`, `_count`). Open the Prometheus metric browser and check the
  name; the panel notes call this out. Have a screenshot of a populated
  dashboard as a fallback.
- **The cache ratio does not climb:** make sure you are reusing ONE thread id
  across turns (a new thread is a cold cache each time). If it still will not
  move, show the pre-driven data and explain the mechanic.
- **Langfuse overlay not up:** skip section 5 entirely; the Grafana story is
  complete without it. Never start the heavy overlay live under time pressure.
