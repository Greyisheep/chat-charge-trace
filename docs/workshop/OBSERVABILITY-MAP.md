# What we turned on with ADK (and how to read it)

The one idea: **ADK already COMPUTES the agentic telemetry. We did not write the
metrics or spans. We turned them on and pointed them at a collector.** Three
moves did it, then two of our own additions, then how to read all of it in
Grafana and Langfuse.

---

## 1. The env flips (repo-root `.env`, documented in `.env.example`)

These change ADK's telemetry behavior. They are plain environment variables, not
code:

| Var | What it turns on |
|---|---|
| `ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN=2` | The `invoke_workflow` entrypoint span + duration metric (our checkout graph) and the current span shape |
| `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` | The current `gen_ai.*` semantic conventions |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_AND_EVENT` | Capture the actual prompt and response content |
| `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true` | Same content on the legacy span attributes (fed to Langfuse) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `..._METRICS_ENDPOINT` / `..._LOGS_ENDPOINT` | Where traces / metrics / logs go (the collector) |

## 2. The providers (`backend/app/telemetry.py`)

We install a global **MeterProvider** (OTLP + `PeriodicExportingMetricReader`)
and a global **LoggerProvider**. This is the whole unlock: ADK computes its
metrics against the global meter, but **without a MeterProvider that meter is a
no-op and nothing leaves the process.** Installing it is what makes the numbers
appear. (One provider per signal, alongside the existing TracerProvider.)

## 3. ADK features we enabled (`backend/app/agent/adk_app.py`, `shop_agent.py`)

These PRODUCE the interesting signal:

- **`ContextCacheConfig`** (App-level context caching) -> produces the
  `cache_read` tokens, the cache-hit demo.
- **`GlobalInstructionPlugin`**, **`ContextFilterPlugin(num_invocations_to_keep=20)`**,
  **`ReflectAndRetryToolPlugin`** (we subclass it to emit retry telemetry).
- **`BuiltInPlanner`** with a bounded thinking budget on the shop agent.

---

## What ADK then emits (this is what Kruse's spans AND the metrics come from)

**SPANS (traces -> Tempo).** Kruse's waterfall is these:
`invoke_agent {name}`, `invoke_workflow {name}`, `execute_tool {name}`,
`generate_content {model}`. Attributes include `gen_ai.agent.name`,
`gen_ai.conversation.id`, `gen_ai.request.model`,
`gen_ai.response.finish_reasons`, and token counts
(`gen_ai.usage.input_tokens`, `output_tokens`, `cache_read.input_tokens`,
`reasoning.output_tokens`).

**METRICS (-> Prometheus, at the collector's `:8889`).** All `gen_ai_*`:
- `gen_ai_invoke_agent_inference_calls` (the "did it re-plan" signal)
- `gen_ai_invoke_agent_tool_calls`
- `gen_ai_invoke_agent_duration`, `gen_ai_invoke_workflow_duration`,
  `gen_ai_execute_tool_duration`
- `gen_ai_client_token_usage` (split input / output)

**LOGS (content -> Loki).** The full prompt and response ride as OTel log events:
`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`,
`gen_ai.tool.definitions`, each carrying `trace_id`, `span_id`,
`gen_ai.conversation.id`, and `user_id`.

---

## What WE added on top (NOT ADK-native)

Because ADK puts `cache_read` on spans (not as a metric) and has no cost concept:

- `oja_llm_input_tokens`, `oja_llm_output_tokens`, **`oja_llm_cached_input_tokens`**
  (the cache-hit series), **`oja_llm_cost_usd`**, **`oja_llm_cost_ngn`** (cost in
  Naira and USD). Recorded by an ADK `after_model_callback` in
  `backend/app/agent/telemetry_hooks.py`.
- Decision events: `route.chosen` / `route.reason` (checkout graph),
  `agent.handoff` (to the flight sub-agent), `tool.retry`, and voice per-turn
  events (`backend/app/agent/checkout_graph.py`, `telemetry_hooks.py`,
  `backend/api/live_router.py`).

---

## The IDs you are seeing, and how they connect

| ID | Is | Use it to |
|---|---|---|
| `threadId` = `gen_ai.conversation.id` | one conversation (stable across its turns) | follow one buyer end to end |
| `trace_id` | one turn (one message) | open that turn's full trace |
| `span_id` | one operation inside a turn | pinpoint a single model or tool call |

A conversation = many turns (traces) sharing one `conversation.id`. Each turn's
trace links to its content logs in Loki by `trace_id`.

---

## How to use Grafana (http://localhost:3000)

**The dashboard:** "Oja Connect: Agent Observability" (`/d/oja-agent-obs`). The
panels: cache-hit ratio, tokens, cost (USD + NGN), inference-calls-per-turn,
tool-calls-per-turn, tool p95, and the **Conversations** panel (paste a
conversation id to drill into one buyer).

**Explore -> Tempo** (traces / TraceQL):
```
# one conversation's turns
{ span.gen_ai.conversation.id = "PASTE_THREAD_ID" }
# an agent turn with a tool call that errored
{ name =~ "invoke_agent.*" } >> { name =~ "execute_tool.*" && status = error }
# slow or expensive turns
{ span.gen_ai.usage.output_tokens > 1000 || duration > 3s }
```

**Explore -> Loki** (the content logs, prompt + response):
```
{service_name="oja-connect-backend"}
```
Each line carries `trace_id`, `gen_ai_conversation_id`, `user_id`, so you can
filter by conversation or jump from a trace.

**Explore -> Prometheus** (raw metrics): type `gen_ai_` or `oja_llm_` to browse.

**The two jumps that tie it together:**
- **Trace to logs:** open a span in Tempo, click through to its Loki content.
- **Exemplars:** on a Prometheus panel, click a data point to open a
  representative trace.

---

## Langfuse (the opt-in PLUS) — currently ON

The same native OTel spans also fan out to **Langfuse Cloud**
(`us.cloud.langfuse.com`), with full prompt/response content and turns grouped
into **Sessions** (we map `conversation.id` -> Langfuse session id).

- **View it:** log into the Langfuse project. **Traces** = per turn.
  **Sessions** = a whole conversation, turn by turn, with the full prompt and
  completion rendered (the one thing Grafana truncates at 2048 bytes).
- **It is a plus, not a dependency.** Grafana answers almost everything; Langfuse
  is the nice payload reader. Enable/disable is a compose flag:
  ```
  docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d
  ```
- **Why native OTLP and not the usual Langfuse cookbook:** the popular
  OpenInference instrumentor suppresses ADK's native spans and drops the Gemini
  `cache_read` tokens. We send ADK-native OTLP straight through so those survive.

---

## One-line summary to share

ADK computes agentic telemetry natively (spans, token/call metrics, content
logs). We turned it on with a few env vars plus a MeterProvider, kept the signals
the usual instrumentor throws away, and added cost (USD + Naira) and the
cache-hit metric on top. Traces go to Tempo, metrics to Prometheus, content to
Loki, all in Grafana; Langfuse Cloud is an optional full-content view.
