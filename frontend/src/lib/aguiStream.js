/** POST /v1/agents/stream/ SSE client (AG-UI protocol). */

import { API_BASE_URL } from "../config";
import {
  parseStateDeltaOps,
  paymentEventFromSnapshot,
  uiComponentsFromSnapshot,
} from "./parseStateDelta";
import { parseToolCallResultContent } from "./parseToolCallResult";

const STREAM_PATH = "/v1/agents/stream/";

function baseHeaders() {
  return {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
}

export function createAguiIds() {
  const uuid =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `thread_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
  const runId = `run_${Math.random().toString(36).slice(2, 10)}`;
  const messageId = `msg_${Math.random().toString(36).slice(2, 12)}`;
  return { threadId: uuid, runId, messageId };
}

/** RunAgentInput shape the backend expects. */
export function buildStreamPayload({
  threadId,
  runId,
  messages = [],
  state = {},
  tools = [],
  context = [],
  forwardedProps = {},
}) {
  return {
    threadId,
    runId,
    messages,
    state,
    tools,
    context,
    forwardedProps: forwardedProps ?? {},
  };
}

export function buildUserStreamMessage(content, messageId) {
  return {
    id: messageId,
    role: "user",
    content,
  };
}

async function readSseStream(response, onEvent) {
  if (!response.ok) {
    const errText = await response.text().catch(() => "");
    throw new Error(errText || `AG-UI stream failed (${response.status})`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body for AG-UI stream");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n");
    buffer = parts.pop() ?? "";

    for (const line of parts) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const jsonStr = trimmed.slice(5).trim();
      if (!jsonStr || jsonStr === "[DONE]") continue;
      try {
        const event = JSON.parse(jsonStr);
        onEvent(event);
      } catch {
        /* skip malformed chunks */
      }
    }
  }
}

/**
 * Run one AG-UI stream and dispatch handlers per event type.
 *
 * @param {object} payload - full RunAgentInput body
 * @param {object} handlers
 * @param {AbortSignal} [signal]
 */
export async function streamAguiRun(payload, handlers = {}, signal) {
  const url = `${API_BASE_URL}${STREAM_PATH}`;
  const response = await fetch(url, {
    method: "POST",
    headers: baseHeaders(),
    body: JSON.stringify(payload),
    signal,
  });

  let text = "";
  let uiComponents = [];
  let threadId = payload.threadId;
  let runId = payload.runId;
  let streamError = null;
  let paymentEvent = null;

  await readSseStream(response, (event) => {
    const type = event?.type;
    handlers.onRawEvent?.(event);

    switch (type) {
      case "RUN_STARTED":
        threadId = event.threadId ?? threadId;
        runId = event.runId ?? runId;
        text = "";
        uiComponents = [];
        handlers.onUiComponents?.([]);
        handlers.onRunStarted?.(event);
        break;

      case "STATE_SNAPSHOT": {
        const snap = event.snapshot ?? event.state ?? {};
        const snapComponents = uiComponentsFromSnapshot(snap);
        if (snapComponents && snapComponents.length) {
          uiComponents = snapComponents;
          handlers.onUiComponents?.(uiComponents, { source: "snapshot" });
        }
        const snapPayment = paymentEventFromSnapshot(snap);
        if (snapPayment) {
          paymentEvent = snapPayment;
          handlers.onPaymentEvent?.(snapPayment);
        }
        handlers.onStateSnapshot?.(snap);
        break;
      }

      case "TEXT_MESSAGE_START":
        handlers.onTextStart?.(event);
        break;

      case "TEXT_MESSAGE_CONTENT":
        if (typeof event.delta === "string") {
          text += event.delta;
          handlers.onTextDelta?.(text, event.delta);
        }
        break;

      case "TEXT_MESSAGE_END":
        handlers.onTextEnd?.(text);
        break;

      case "STATE_DELTA":
        if (Array.isArray(event.delta)) {
          const parsed = parseStateDeltaOps(event.delta, uiComponents);
          uiComponents = parsed.uiComponents;
          if (parsed.paymentEvent) {
            paymentEvent = parsed.paymentEvent;
            handlers.onPaymentEvent?.(parsed.paymentEvent);
          }
          handlers.onUiComponents?.(uiComponents, { source: "delta" });
          handlers.onStateDelta?.(event.delta);
        }
        break;

      case "TOOL_CALL_START":
        handlers.onToolStart?.(event);
        break;

      case "TOOL_CALL_END":
        handlers.onToolEnd?.(event);
        break;

      case "TOOL_CALL_RESULT": {
        const parsed = parseToolCallResultContent(event.content);
        if (parsed?.paymentEvent) {
          paymentEvent = parsed.paymentEvent;
          handlers.onPaymentEvent?.(parsed.paymentEvent);
        }
        if (parsed?.uiComponents?.length) {
          const merged = [...uiComponents];
          for (const cmp of parsed.uiComponents) {
            const idx = merged.findIndex((c) => c.id === cmp.id);
            if (idx >= 0) merged[idx] = cmp;
            else merged.push(cmp);
          }
          uiComponents = merged;
          handlers.onUiComponents?.(uiComponents, { source: "tool_result" });
        }
        handlers.onToolResult?.(event, parsed);
        break;
      }

      case "RUN_FINISHED":
        handlers.onRunFinished?.({
          threadId,
          runId,
          text,
          uiComponents,
          paymentEvent,
        });
        break;

      case "RUN_ERROR":
        streamError = event.message ?? event.error ?? "AG-UI run failed";
        handlers.onRunError?.(event);
        break;

      default:
        break;
    }
  });

  if (streamError) {
    throw new Error(streamError);
  }

  return { threadId, runId, text, uiComponents, paymentEvent };
}
