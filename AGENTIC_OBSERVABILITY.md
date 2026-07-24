# Agentic Observability

Decision record: **issue #11**. This document expands on #11 and the tracing
work that preceded it (see #7, `OTEL.md`, `monitoring/README.md`). Where #11
records the *what* and *why* as a decision, this file is the operator and talk
companion: what it answers, how the pipeline is shaped, and the queries to run.

The tracing branch already gave us solid REQUEST tracing. This is the AGENTIC
layer on top: the token, cost, cache, and re-planning signals that explain
*why the agent behaved the way it did*, not just *what endpoints it hit*.

---

## What this answers

The whole point is to move from "a request happened" to "here is why the agent
did that":

- **Did context caching actually work?** Cache-read tokens over input tokens,
  live. This is the single best demo in the talk: you watch the ratio climb as
  the shared prompt prefix gets cached.
- **What did this turn cost?** A derived USD number per turn and over time.
- **Did the agent re-plan?** Inference (model) calls per agent turn. One call is
  a straight answer; several means a tool loop or a re-plan.
- **How many tools did it reach for, and how slow were they?** Tool calls per
  turn and tool execution p95.
- **Which graph path ran?** The checkout Workflow entrypoint span plus the
  express-vs-direct branch, legible in the trace.
- **What exactly was said?** Full prompt and response content, in Loki, linked
  from the trace, without ever bloating or truncating a span.

---

## The native-vs-instrumentor insight (the important one)

ADK **already computes** the agentic signal. `google/adk/telemetry/_metrics.py`
records, against the OpenTelemetry **global meter**:

- `gen_ai.invoke_agent.inference_calls` (re-plan signal)
- `gen_ai.invoke_agent.tool_calls`
- `gen_ai.invoke_agent.duration`
- `gen_ai.invoke_workflow.duration` (the checkout graph entrypoint)
- `gen_ai.execute_tool.duration`
- `gen_ai.client.token.usage` (split by `gen_ai.token.type` = input / output)
- `gen_ai.client.operation.duration`

and puts token attributes on spans: `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens` (the
Gemini context-cache hit), `gen_ai.usage.reasoning.output_tokens`.

It exports **none of them** unless a `MeterProvider` is installed, because
without one the global meter is a no-op. So the fix is small and structural:
install a `MeterProvider` (and a `LoggerProvider` for content log events)
alongside the co-speaker's existing `TracerProvider`. One provider per signal,
no second `TracerProvider`. That lives in `backend/app/telemetry.py` (see #11).

The trap to avoid: the popular **OpenInference** instrumentor (the Phoenix /
Langfuse cookbook path) **suppresses ADK's native `gen_ai.*` spans** and
**drops the Gemini `cache_read` tokens**. Since cache hits are our headline
demo, we do the opposite of the cookbook: we send **ADK-native OTLP** straight
through the collector. (see #11)

> **Langfuse.** Langfuse is used via **Langfuse Cloud**, wired through the
> official Langfuse skill as a separate follow-up (see #11 and the Langfuse
> integration commit). The collector still fans out **native OTLP** so
> `cache_read` tokens are preserved on that path. We deliberately do **not**
> self-host Langfuse in this repo, and we do **not** use the OpenInference
> instrumentor for it.

> **Stability caveat.** Every `gen_ai.*` attribute is **Development** stability
> in the OTel semantic conventions: names can change. Treat this as
> experimental. The Langfuse-native-OTLP cache-token mapping in particular is
> **to be verified empirically** once the Cloud integration lands.

---

## Pipeline topology

```
Oja Connect backend  (telemetry.py: Tracer + Meter + Logger providers)
        │  OTLP/HTTP  :4318   (traces + metrics + logs)
        ▼
   otel-collector
        ├── traces  ──▶  Tempo        structure only:
        │                              1. batch
        │                              2. transform/strip_content  (delete bodies)
        │                              3. transform/redact_pii      (mask PII)
        ├── metrics ──▶  Prometheus   scraped off the collector's :8889 exporter
        └── logs    ──▶  Loki         FULL prompt / response content
        │
        ▼
      Grafana :3000
        Tempo + Prometheus + Loki datasources, cross-linked:
          Prometheus exemplar --(trace_id)--> Tempo
          Tempo span          --(trace_id)--> Loki (trace-to-logs)
```

Default stack: `tempo`, `otel-collector`, `prometheus`, `loki`, `grafana`.
These now live in the **root** `docker-compose.yml` alongside the app, all on
one `oja` network, so `docker compose up -d` from the repo root brings up the
whole thing. To start only the observability services (local backend dev), run
`docker compose up -d tempo otel-collector prometheus loki grafana`.

### Why content never reaches Tempo

Prompt and response bodies are captured with
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_AND_EVENT` (and the
legacy `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true`), so content rides both spans
and OTel log events. The collector then **strips the content off the Tempo
branch** (`transform/strip_content`) while the Loki logs pipeline and the opt-in
Langfuse branch keep it. So bodies reach Loki and Langfuse at full fidelity but
**never reach Tempo**. Content is on spans (not events-only) specifically so the
Langfuse cameo can render the full prompt and completion; the Tempo strip is
what keeps that content out of the trace store, because:

- **Tempo silently truncates any span attribute past 2048 bytes.** A long LLM
  response would be cut with no error and no marker. You would not know your
  data was lost. Alert on `tempo_distributor_attributes_truncated_total` to
  catch any body that still slips onto a span. (see #11)
- **Payments app.** Bodies carry buyer PII. Keeping them off the trace store
  shrinks the blast radius and the storage cost.

Belt and suspenders: the collector's Tempo branch also **deletes** any
body-bearing attribute that still rides a span
(`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`,
and the legacy `gcp.vertex.agent.llm_request` / `llm_response` /
`tool_call_args` / `tool_response`), then **masks PII** across the remaining
attribute values: card-like 13-16 digit runs, emails, and account/phone-like
10-12 digit runs. Loki keeps full fidelity and truncates rather than drops
(`max_line_size_truncate: true`). (see #11)

---

## The "why did it do that" query cookbook

### In the dashboard

Open Grafana at `http://localhost:3000`, dashboard **"Oja Connect: Agent
Observability"**:

1. **Context cache hit ratio** = `cache_read` / `input` tokens over time. Watch
   it climb as the shared prompt prefix caches. This proves caching works live.
2. **Tokens in / out / cached over time, by model.**
3. **Estimated cost** per turn and over time (derived, see below).
4. **Inference calls per turn** (the re-plan signal) and **tool calls per turn**.
5. **Tool exec p95** and **workflow duration**.
6. **Slow or high-token traces** (a Tempo / TraceQL panel). Click a row, open
   the trace, then jump to its Loki content via trace-to-logs.

> **Metric names.** ADK's native token-usage metric (`gen_ai_client_token_usage`)
> only splits **input / output**; ADK does not export `cache_read` as a metric.
> So the cache and cost panels use the metrics the in-code instrumentation
> records (implemented, see #11): `oja_llm_input_tokens`,
> `oja_llm_output_tokens`, `oja_llm_cached_input_tokens` (the cache-hit series),
> `oja_llm_cost_usd`, and `oja_llm_cost_ngn` (cost in Naira as well as USD).
> The OTLP-to-Prometheus exporter appends `_sum` / `_count` / `_bucket` to these
> histograms; the cache-ratio panel is
> `oja_llm_cached_input_tokens_sum / oja_llm_input_tokens_sum`.

### TraceQL (Tempo Explore)

```
# Structural: an agent invocation with a descendant tool span that errored.
{ name =~ "invoke_agent.*" } >> { name =~ "execute_tool.*" && status = error }

# Output tokens by model, summed over the window (needs schema v2 attributes).
{ } | select(span.gen_ai.usage.output_tokens, span.gen_ai.request.model)

# High-token or slow turns worth opening.
{ span.gen_ai.usage.output_tokens > 1000 || duration > 3s }

# Turns that hit the context cache at all.
{ span.gen_ai.usage.cache_read.input_tokens > 0 }
```

### PromQL (cache-hit ratio, once cache_read is exported as a metric)

```
sum(rate(gen_ai_client_token_usage_sum{gen_ai_token_type="cache_read"}[5m]))
  /
clamp_min(sum(rate(gen_ai_client_token_usage_sum{gen_ai_token_type="input"}[5m])), 1)
```

---

## Cost is derived, on purpose

OTel gen_ai semconv **deliberately has no cost attribute**: price is a business
concern that moves independently of the trace. So cost is **our own** number.
`estimate_cost_usd(model, input_tokens, output_tokens, cached_input_tokens)` in
`telemetry.py` computes an exact `Decimal` from a one-dict Gemini price table
(USD per 1M tokens; cached input billed at the reduced cache-read rate). It is
not a billing source of truth; it is a live-demo estimate. Update the one dict
when pricing changes. (see #11)

---

## The scale story (for the talk)

The workshop stack is single-node and light. Here is what changes at real
volume, and the traps that bite:

- **Head vs tail sampling, and the `decision_wait` trap.** Head sampling decides
  at the root before the trace finishes, so it cannot sample on "this trace was
  slow" or "this trace errored". Tail sampling can, but the tail-sampling
  processor buffers a trace only for `decision_wait` (default **30s**) before
  deciding. Agent traces routinely run **multiple minutes** (tool loops, live
  voice). A 30s wait makes a latency-based policy **systematically miss** every
  long agent trace, which are exactly the ones you care about. Fix it with a
  longer decision window or the span-ingest / `decision_wait_after_root_received`
  strategy so the clock starts from the last activity, not the first.
- **Two-tier collector for tail sampling.** Tail sampling needs every span of a
  trace to land on the **same** collector instance. That means a first tier of
  `loadbalancingexporter` with `routing_key: traceID` in front of a second tier
  running the `tailsampling` processor. A single flat pool silently makes wrong
  decisions because it only ever sees part of each trace.
- **Content storage cost (~50x).** Full prompt / response bodies dwarf span
  metadata. Keeping content on Loki (not Tempo) and truncating rather than
  dropping is the cheap, honest default. Budget for it before you turn content
  capture on in production.
- **Collector-side PII redaction is mandatory for a payments app.** Redact at
  the collector, before anything reaches a store, so a backend bug cannot leak
  a card number into a trace UI. That is why the strip + mask lives on the
  collector's Tempo branch, not only in app code. (see #11)

---

## Safety note: resumability and money-moving tools

ADK resumability can re-fire a tool **"at least once, possibly more than
once."** For a Monnify **disbursement**, a re-fire is a **double payment**. So
any money-moving tool must carry an **idempotency key** before resume is ever
enabled. **We do not use resume today**, and this observability work does not
change that. Do not enable it for a disbursement path without idempotency
first. (see #11)

---

## Honesty markers

- All `gen_ai.*` attributes are **Development** stability. Names may change.
- The exact Prometheus metric names depend on the collector's unit handling;
  verify against the metric browser (see the metric-name caveat above).
- The cost table is an editable estimate, not a billing source of truth.
- The Langfuse-native-OTLP `cache_read` mapping is **to be verified empirically**
  when the Langfuse Cloud integration lands.

---

## TODO for the in-code instrumentation follow-up

The infrastructure half (this document) makes the data *flow*. The follow-up
adds the in-code instrumentation points that *emit* the last few series. The
shared helper API already exists in `backend/app/telemetry.py` for it to call:

- `add_span_event(name, **attributes)` - point-in-time facts on the active span
  (agent-to-agent switch and why, context-cache hit, barge-in, re-plan).
- `increment_counter(name, amount=1, attributes=None)` - lazily created counter.
- `record_histogram(name, value, attributes=None)` - lazily created histogram.
- `estimate_cost_usd(model, input_tokens, output_tokens, cached_input_tokens=0)`
 - derived cost as `Decimal`.

Specifically still owed by the follow-up:

- Record **`cache_read` tokens as a metric** (ADK only puts them on spans), so
  the cache-hit-ratio and cached-token panels have data.
- Record the **derived cost** as a metric (e.g. `oja.llm.cost_usd`) via
  `estimate_cost_usd`, so the cost panels have data.
- Emit an explicit **agent-switch** span event on the flight-fare sub-agent
  handoff, and **which checkout path ran** (express vs direct fallback).
- Voice-door per-turn spans: audio-in / audio-out latency and barge-in events.
