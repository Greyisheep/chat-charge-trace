# Cheat-sheet (one page, glance at this during the talk)

## Start / stop

```bash
docker compose up --build -d        # bring up the whole stack (app + observability)
docker compose ps                   # all services healthy/up?
docker compose logs -f backend      # tail backend if something is off
docker compose down                 # stop (keeps data; never use -v on stage)
./scripts/reset-demo.sh             # wipe orders + sessions for a clean demo
```

Langfuse cameo (optional, only if you show Stage 3 section 5):
```bash
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d
```

## URLs

| What | URL |
|---|---|
| App (shop + chat) | http://localhost:5173 |
| Grafana dashboard | http://localhost:3000/d/oja-agent-obs |
| Backend health | http://localhost:8000/api/products (9 products) |

Grafana time range: **Last 30 min**, refresh **10s**.

## Demo drives (the exact things to do live)

| Stage | Drive | What to watch |
|---|---|---|
| 0 Hook | "I want the suya spice box, ship to Lagos" -> confirm -> pay in Monnify popup | "Payment verified" |
| 3 Cache | ONE thread, 3-4 turns in a row | Panel 1 cache ratio **climbs** |
| 3 Re-plan | "Can you fly an ankara tote to London?" (express) | Panels 4b + 5 **spike**; trace shows route=express + agent.handoff |
| 3 Conversation | paste a thread id into the **Conversation-id** var | Panel 8 collapses to that buyer's turns |
| 1 Voice | click mic ("Start live voice"), speak; type name/email when asked | agent gets it right; typed field lands in the same session |

Cache tip: the ratio only climbs if you reuse **one** thread id. A new thread is
a cold cache.

## Dashboard panels

1 cache-hit ratio, 2 tokens in/out/cached, 3+4a cost (USD + NGN),
4b inference calls/turn (re-plan), 5 tool calls/turn, 6 tool p95 + workflow,
7 slow/high-token traces, 8 Conversations.

## TraceQL (Explore -> Tempo)

```
{ span.gen_ai.conversation.id = "<thread-id>" }          # one conversation's turns
{ name =~ "invoke_agent.*" } >> { name =~ "execute_tool.*" && status = error }   # tool errored
{ span.gen_ai.usage.output_tokens > 1000 || duration > 3s }   # slow or heavy turns
```

## Key metrics (collector :8889, Prometheus)

`oja_llm_cached_input_tokens_sum` (cache hits), `oja_llm_cost_usd_sum`,
`oja_llm_cost_ngn_sum`, `gen_ai_invoke_agent_inference_calls_*` (re-plan),
`gen_ai_invoke_agent_tool_calls_*`. Exporter suffixes histograms with
`_sum` / `_count` / `_bucket`.

## If it breaks (one-liners)

- **Monnify popup / wifi:** play the pre-recorded purchase clip, move on.
- **Voice:** skip live voice, describe it, use the text door.
- **Panel says No data:** metric name has a `_sum`/`_seconds` suffix; adjust in
  the Prometheus browser. Fall back to a screenshot.
- **Cache not climbing:** you are on a new thread each turn; reuse one thread.
- **Langfuse not up:** skip Stage 3 section 5; Grafana story is complete alone.
