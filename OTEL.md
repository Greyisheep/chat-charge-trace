# Observability Workshop — OpenTelemetry Tracing

This document covers the tracing setup for the **Chat, Charge, Trace** workshop.
The goal is to make the agent's behaviour visible: every conversation turn, every
tool call, every step of the checkout graph, and every external call the agent
triggers — all in one waterfall view.

---

## What is a trace?

A **trace** is a record of everything that happened to serve one request. It is
made up of **spans** — individual named operations, each with a start time, an
end time, and optional attributes (key/value pairs).

Spans nest. A parent span can have many child spans. That nesting is what
produces the waterfall view you see in Grafana — the visual representation of
"A called B, which called C".

In this project, one message sent by the user produces one trace. The trace
captures the complete journey: the LLM call, every tool the agent chose to run,
every node in the checkout graph, every external API call those tools made.

---

## Remote stack

A shared **OTEL Collector → Grafana Tempo → Grafana** stack is running for this
workshop. The URL will be shared on the day.

To connect your backend to it, set these three environment variables in your
`.env` file:

```env
OTEL_SERVICE_NAME=oja-connect-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://<shared-url>:4318
OTEL_TRACES_SAMPLER=always_on
```

Then restart the backend. Every message you send will ship its spans to the
shared collector and appear in Grafana within a second or two.

> For those comfortable with Docker Compose, a self-contained monitoring stack
> (Collector + Tempo + Grafana) lives in the `monitoring/` folder and can be
> run locally with `docker compose up -d`.

---

## Trace pipeline

```
Oja Connect backend
  (spans created here)
        |
        | OTLP/HTTP  :4318
        v
  OTEL Collector
  (receives, batches)
        |
        | OTLP/gRPC  :4317
        v
      Tempo
  (stores traces)
        |
        | Tempo datasource
        v
     Grafana
  (Explore view)
```

The backend sends spans to the Collector over HTTP. The Collector batches them
and forwards to Tempo. Grafana reads from Tempo and lets you search and explore
individual traces.

---

## Viewing traces in Grafana

1. Open Grafana at the shared URL on port `3000`
2. Click the **Explore** icon (compass) in the left sidebar
3. Select **Tempo** as the datasource
4. Switch the query type to **TraceQL**
5. Run any of the queries below

### Useful TraceQL queries

```
# Every agent turn (one per message sent)
{ name = "agent.turn" }

# Every tool call
{ name =~ "tools\\..*" }

# The full checkout pipeline
{ name =~ "checkout\\..*" }

# Just the geocoding calls
{ name = "delivery.geocode" }

# Just the Monnify calls
{ name =~ "monnify\\..*" }

# Live voice sessions
{ name = "live.session" }

# Slow turns (more than 3 seconds)
{ name = "agent.turn" } | duration > 3s

# Any span that errored
{ status = error }
```

Click any row in the results to open the waterfall for that trace.

---

## What the spans mean

When you open a trace, you will see two layers of spans: spans emitted by ADK
(the agent framework) and spans we added manually. They nest together into one
tree.

### ADK's built-in spans

ADK instruments itself with OpenTelemetry. You get these for free without writing
any code:

| Span | What it represents |
|---|---|
| `invocation` | One complete agent request cycle — input in, output out |
| `invoke_agent <name>` | ADK invoking a named agent (shop agent or flight sub-agent) |
| `call_llm` | One call to the LLM. **There are usually two per turn** — see below |
| `generate_content <model>` | The actual HTTP request to the Gemini API |
| `handle_context_caching` | ADK checking/refreshing the prompt cache |
| `execute_tool <name>` | ADK executing one tool function |
| `invoke_workflow <name>` | ADK running a Workflow graph |
| `invoke_node <name>` | ADK running one node inside a Workflow graph |

### The agentic loop — why there are two `call_llm` spans

A common source of confusion. The LLM does not reply in a single shot:

```
call_llm  (first)
  └── generate_content        ← Gemini reads the message, decides to call a tool
        └── execute_tool checkout
              └── tools.checkout
                    └── (checkout graph runs)

call_llm  (second)
  └── generate_content        ← Gemini reads the tool result, writes the reply
```

The first call is the model *thinking* — it decides which tool to use. The second
call is the model *replying* — it turns the tool result into the message the user
sees. This back-and-forth is the **agentic loop**, and it repeats for every tool
the model decides to call in a single turn.

### Our custom spans

These sit inside ADK's spans and add business-level context:

| Span | Where it sits | What it tells you |
|---|---|---|
| `agent.turn` | Root of every trace | The entire conversation turn, start to finish |
| `tools.list_products` | Inside `execute_tool` | Agent browsed the catalog |
| `tools.get_product` | Inside `execute_tool` | Agent fetched one product |
| `tools.quote_delivery` | Inside `execute_tool` | Agent priced a delivery |
| `tools.checkout` | Inside `execute_tool` | Agent ran the checkout pipeline |
| `tools.check_order_status` | Inside `execute_tool` | Agent verified an order |
| `checkout.validate_product` | Inside `invoke_node` | Graph validated the product exists |
| `checkout.geocode_destination` | Inside `invoke_node` | Graph resolved the city to coordinates |
| `checkout.flight_fare_lookup` | Inside `invoke_node` | Graph searched for a live flight fare (express only) |
| `checkout.compute_fee` | Inside `invoke_node` | Graph derived the final delivery fee |
| `checkout.create_order` | Inside `invoke_node` | Graph wrote the order to Postgres |
| `checkout.payment_event` | Inside `invoke_node` | Graph built the Monnify payment payload |
| `delivery.geocode` | Inside `checkout.geocode_destination` | HTTP call to Open-Meteo geocoding API |
| `monnify.authenticate` | Inside Monnify client | Monnify auth call |
| `monnify.initialize_transaction` | Inside Monnify client | Monnify transaction creation |
| `monnify.query_transaction` | Inside `orders.verify` | Monnify payment status check |
| `orders.create` | Inside `checkout.create_order` | Postgres write |
| `orders.verify` | Inside `tools.check_order_status` | Monnify re-verification |
| `live.session` | Root for voice turns | Entire WebSocket voice session |

### A full checkout trace

```
agent.turn
└── invocation
    └── invoke_agent OjaConnectShopAgent
        ├── call_llm                          ← model decides to call checkout
        │   └── generate_content
        │       └── execute_tool checkout
        │           └── tools.checkout
        │               (workflow dispatched by ADK below)
        ├── invoke_workflow checkout
        │   ├── invoke_node validate_product
        │   │   └── checkout.validate_product
        │   ├── invoke_node geocode_destination
        │   │   └── checkout.geocode_destination
        │   │       └── delivery.geocode
        │   ├── invoke_node standard_quote
        │   ├── invoke_node compute_fee
        │   │   └── checkout.compute_fee
        │   ├── invoke_node create_order
        │   │   └── checkout.create_order
        │   │       └── orders.create
        │   └── invoke_node payment_event
        │       └── checkout.payment_event
        └── call_llm                          ← model writes the reply
            └── generate_content
```

---

## The telemetry seam — how it works in the code

All tracing in this codebase flows through one file: `backend/app/telemetry.py`.
Everything else imports from it. This means the entire instrumentation can be
understood, changed, or extended in one place.

### Three public functions

**`@span(name, **arg_attrs)`** — a decorator that declares a span at the function
signature. `arg_attrs` maps span attribute names to function parameter names:

```python
@span("tools.get_product", product_id="product_id")
def get_product(product_id: str) -> dict:
    ...
```

When `get_product("ankara-tote")` is called, the decorator opens a span named
`tools.get_product`, sets `product_id = "ankara-tote"` on it, runs the function,
then closes the span. Works on sync functions, async coroutines, and async
generators.

**`set_span_attribute(key, value)`** — adds an attribute to the currently active
span from inside a function body. Used when the value is computed at runtime
rather than read from a parameter:

```python
@span("orders.create", amount="amount")
async def create_order(self, ..., amount: Decimal) -> Order:
    reference = "ord-" + secrets.token_hex(5)   # computed, not a parameter
    set_span_attribute("reference", reference)   # attach it to the span anyway
    ...
```

**`traced(name, **attributes)`** — a context manager for the one case where a
span covers a block of code rather than a whole function:

```python
with traced("live.session", thread_id=thread_id):
    # everything inside this block is part of the span
    ...
```

### Why context propagation works without passing anything around

When `@span("agent.turn")` opens on `transformed_run`, OpenTelemetry stores the
active span in Python's `contextvars` — a per-coroutine-task key/value store
built into the language. Every `await` and every `yield` in an async function
preserves these values automatically.

So when a tool like `checkout` runs and opens `@span("tools.checkout")`,
OpenTelemetry asks: "what span is currently active in this context?" The answer
is `agent.turn`. No explicit parent is passed — the hierarchy emerges from the
execution flow.

---

## Span attributes worth looking for in Grafana

Click any span in the waterfall to see its attributes panel on the right.

| Span | Useful attributes |
|---|---|
| `tools.get_product` | `product_id` |
| `tools.quote_delivery` | `product_id`, `city` |
| `tools.checkout` | `product_id` |
| `tools.check_order_status` | `reference` |
| `checkout.geocode_destination` | `city`, `country` |
| `checkout.flight_fare_lookup` | `city` |
| `checkout.create_order` | `reference` |
| `monnify.initialize_transaction` | `reference`, `amount` |
| `monnify.query_transaction` | `reference` |
| `orders.create` | `reference`, `amount` |
| `orders.verify` | `reference` |
| `delivery.geocode` | `city` |
| `live.session` | `thread_id` |
