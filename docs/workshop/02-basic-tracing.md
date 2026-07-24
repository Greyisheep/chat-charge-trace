# Stage 2: Basic tracing (15 min, Kruse)

## Goal

Open the black box with the standard stack: OpenTelemetry into Grafana Tempo.
Show that you can now see **what ran and how long**. This is the honest baseline
that Stage 3 will then push past.

## Pre-flight

- Grafana at http://localhost:3000.
- Have driven at least one or two agent turns recently so there are fresh traces.
- Know two trace IDs or be ready to search; do a turn live so the trace is warm.

## Script

### 1. Where the data comes from (3 min)

- The backend emits OpenTelemetry: traces, metrics, and logs, over OTLP to a
  collector. The collector fans them out: **traces to Tempo, metrics to
  Prometheus, logs to Loki**, all visible in Grafana.
- ADK (the agent framework) speaks OTel natively, so a lot of this is "turn it
  on," not "write it from scratch." Name that honestly; it is a feature.
- One command brought this whole stack up next to the app
  (`docker compose up --build`), same network, so the agent's spans sit in the
  same system as everything else.

### 2. A turn as a trace (6 min)

- Drive one agent turn in the app (for example "tell me about the suya spice
  box").
- In Grafana, go to **Explore -> Tempo**, run a search, open the newest trace.
- Walk the waterfall: the agent turn at the top, the model call, the tool calls
  (get_product, quote_delivery), the geocode, the workflow. Point out the
  span for the checkout graph when you drive a purchase.
- This answers **what ran and in what order, and how long each step took.**

### 3. Trace to logs (4 min)

- Open a span, use **trace-to-logs** to jump into Loki and show the full prompt
  and response content that belongs to that trace.
- Teaching point: the bodies live in Loki, not on the trace, on purpose. Tempo
  truncates any span attribute past 2048 bytes silently. Stage 4 comes back to
  why that matters at scale.

### 4. The honest limit (2 min)

- "This is real and useful. It tells me WHAT happened. But look at this trace:
  it is a green 200. It does not tell me the agent looped three times, or that
  this turn cost more than it should, or whether the cache even worked. A
  waterfall cannot answer WHY the agent behaved the way it did. That is where
  Claret takes over."

## Key points

- OTel to collector to Tempo/Prometheus/Loki is the standard, boring, correct
  spine.
- ADK emits spans natively; you mostly enable and route them.
- A trace answers "what ran"; it does not answer "why."

## The aha moment

The clean 200-OK trace that hides a problem. Set up the tension: everything
looks healthy, and you still cannot answer the questions that matter.

## If it breaks

- **No traces showing:** confirm the collector is up
  (`docker compose ps`), then drive a fresh turn and search Tempo again;
  ingestion has a few seconds of lag.
- **Trace-to-logs shows nothing:** the content pipeline may lag; fall back to
  the trace waterfall alone, the "what ran" point stands without the log jump.
- Keep this stage tight. It is the setup for the punchline, not the punchline.
