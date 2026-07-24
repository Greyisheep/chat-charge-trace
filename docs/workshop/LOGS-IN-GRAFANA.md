# Logs in Grafana (the prompt/response content)

The full prompt and response content is captured as OpenTelemetry **log events**
and sent to **Loki**. This is where "what exactly was said" lives (Tempo holds
structure only; it truncates bodies at 2048 bytes, so content is deliberately
kept off traces and in Loki).

## See them in Grafana

1. http://localhost:3000 -> left nav -> **Explore**.
2. Datasource dropdown (top left) -> **Loki**.
3. Query:
   ```
   {service_name="oja-connect-backend"}
   ```
4. Run. Each row is one log record. Click a row to expand it.

## What each log record carries

The content and the correlation keys are on every record:

| Field | What |
|---|---|
| `gen_ai_input_messages` | the prompt sent to the model |
| `gen_ai_output_messages` | the model's response |
| `gen_ai_system_instructions` | the system prompt |
| `gen_ai_tool_definitions` | the tools offered that call |
| `gen_ai_usage_input_tokens` / `output_tokens` / `cache_read_input_tokens` | token counts |
| `trace_id`, `span_id` | link back to the exact trace / operation |
| `gen_ai_conversation_id` | the conversation (the AG-UI threadId) |
| `user_id` | the door / user |
| `gen_ai_agent_name`, `gen_ai_response_finish_reasons` | which agent, why it stopped |

## Useful filters (paste into the Loki query)

```
# one conversation's content, all turns
{service_name="oja-connect-backend"} | gen_ai_conversation_id="PASTE_THREAD_ID"

# a single trace's content
{service_name="oja-connect-backend"} | trace_id="PASTE_TRACE_ID"

# only turns where the model stopped for a non-normal reason
{service_name="oja-connect-backend"} | gen_ai_response_finish_reasons!="STOP"
```

## The jump that ties traces to logs

From **Explore -> Tempo**, open a trace, click a span, and use **"Logs for this
span"** (trace-to-logs). Grafana carries the `trace_id` into a Loki query and
shows you the exact prompt and response for that operation. This is the
"structure in Tempo, content in Loki, one click between them" flow.

## Why content is here and not on the trace

- Tempo silently truncates any span attribute past 2048 bytes. A long prompt
  would be cut with no error. Loki takes a 256KB line and truncates rather than
  drops. So bodies belong in Loki.
- For a payments app, keeping bodies off the trace store also shrinks the PII
  blast radius (and the collector redacts card/email/account patterns on the
  branches that keep content).

If you want the content rendered even more readably (side by side with the
trace, threaded by conversation), that is what the optional **Langfuse** view
adds. See `OBSERVABILITY-MAP.md`.
