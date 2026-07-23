/** Run one AG-UI stream turn and drive streaming message state updates. */

import {
  streamAguiRun,
  createAguiIds,
  buildStreamPayload,
  buildUserStreamMessage,
} from "./aguiStream";
import { openPaymentFromStreamEvent } from "./openPaymentFromStream";
import {
  isPaymentMetadataDelta,
  sanitizeStreamText,
} from "./sanitizeStreamText";
import { createThrottledTextPatch, isHiddenStreamTool } from "./streamingUtils";

/**
 * @param {object} params
 * @param {string} params.threadId
 * @param {string} params.userContent
 * @param {function} params.onPatch - (patch) => void, merges into the streaming agent message
 * @param {function} [params.onPaymentEvent] - (paymentEvent) => void
 * @param {AbortSignal} [params.signal]
 */
export async function runAguiStreamTurn({
  threadId,
  userContent,
  onPatch,
  onPaymentEvent,
  signal,
}) {
  const { runId, messageId } = createAguiIds();

  const messages = userContent
    ? [buildUserStreamMessage(userContent, messageId)]
    : [];

  const payload = buildStreamPayload({
    threadId,
    runId,
    messages,
    state: {},
    tools: [],
    context: [],
    forwardedProps: {},
  });

  const streamTools = [];
  const textPatch = createThrottledTextPatch((patch) => {
    if (patch.text != null) {
      onPatch({ ...patch, text: sanitizeStreamText(patch.text) });
    } else {
      onPatch(patch);
    }
  });

  let paymentOpened = false;
  let paymentDisplayText = null;
  let skipStreamTextDeltas = false;

  const handlePaymentEvent = (event) => {
    if (!event || paymentOpened) return;
    paymentOpened = true;
    onPaymentEvent?.(event);
    openPaymentFromStreamEvent(event);
  };

  const result = await streamAguiRun(
    payload,
    {
      onRunStarted: () => {
        onPatch({
          uiComponents: [],
          streamTools: [],
          streamStatus: "thinking",
          text: "",
        });
      },
      onUiComponents: (uiComponents) => {
        onPatch({ uiComponents: uiComponents ?? [] });
      },
      onTextDelta: (text, delta) => {
        if (skipStreamTextDeltas || isPaymentMetadataDelta(delta)) {
          return;
        }
        textPatch.push(text);
      },
      onToolStart: (ev) => {
        const name = ev.toolCallName ?? "working";
        const id = ev.toolCallId ?? name;

        if (isHiddenStreamTool(name)) {
          onPatch({ streamStatus: "tool" });
          return;
        }

        const existing = streamTools.find((t) => t.id === id);
        if (!existing) {
          streamTools.push({ id, name, status: "running" });
        }
        onPatch({
          streamStatus: "tool",
          streamTool: name,
          streamTools: [...streamTools],
        });
      },
      onToolEnd: (ev) => {
        const name = ev.toolCallName;
        if (isHiddenStreamTool(name)) {
          onPatch({
            streamStatus: streamTools.some((x) => x.status === "running")
              ? "tool"
              : "writing",
          });
          return;
        }

        const id = ev.toolCallId;
        const t = streamTools.find((x) => x.id === id);
        if (t) t.status = "done";
        const running = streamTools.find((x) => x.status === "running");
        onPatch({
          streamStatus: running ? "tool" : "writing",
          streamTool: running?.name ?? null,
          streamTools: [...streamTools],
        });
      },
      onToolResult: (_ev, parsed) => {
        if (!parsed) return;

        if (parsed.paymentEvent) {
          skipStreamTextDeltas = true;
          handlePaymentEvent(parsed.paymentEvent);
        }

        if (parsed.displayMessage) {
          paymentDisplayText = parsed.displayMessage;
          textPatch.cancel();
          onPatch({
            text: parsed.displayMessage,
            streamStatus: "writing",
          });
        }
      },
      onTextStart: () => onPatch({ streamStatus: "writing" }),
      onPaymentEvent: handlePaymentEvent,
      onRunFinished: ({
        text: finishedText,
        uiComponents: finishedUi,
        paymentEvent,
      }) => {
        textPatch.cancel();
        const rawText =
          paymentDisplayText || finishedText || textPatch.flush() || "";
        onPatch({
          text: sanitizeStreamText(rawText),
          uiComponents: finishedUi ?? [],
          isStreaming: false,
          streamStatus: null,
          streamTool: null,
          streamTools: [],
        });
        if (paymentEvent) {
          handlePaymentEvent(paymentEvent);
        }
      },
      onRunError: () => {
        textPatch.cancel();
        onPatch({
          isStreaming: false,
          streamStatus: null,
          streamTools: [],
          text: "Sorry, I hit a snag processing that. Please try again in a moment.",
        });
      },
    },
    signal,
  );

  return { ...result, threadId: result.threadId ?? threadId };
}
