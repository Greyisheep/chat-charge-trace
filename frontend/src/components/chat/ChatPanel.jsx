/** Chat panel: message list, streaming turns, composer, verified-order notes. */

import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { fetchProducts } from "../../lib/api";
import { createAguiIds } from "../../lib/aguiStream";
import { runAguiStreamTurn } from "../../lib/runAguiStreamTurn";
import {
  cancelSpeech,
  isSpeechSynthesisSupported,
  speak,
} from "../../lib/speech";
import { LiveVoiceSession, isNativeVoiceEnabled } from "../../lib/liveVoice";
import { normalizeAguiComponents } from "../../lib/normalizeComponents";
import { openPaymentFromStreamEvent } from "../../lib/openPaymentFromStream";
import { paymentEventFromSnapshot } from "../../lib/parseStateDelta";
import ChatComposer from "./ChatComposer";
import ChatEmptyState from "./ChatEmptyState";
import MessageBubble from "./MessageBubble";

const VOICE_OUTPUT_KEY = "oja-voice-output";

let localIdCounter = 0;
function nextLocalId(prefix) {
  localIdCounter += 1;
  return `${prefix}_${Date.now()}_${localIdCounter}`;
}

function SpeakerOnIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M11 5 6 9H2v6h4l5 4V5Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ExpandIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CollapseIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 9h5V4M20 9h-5V4M4 15h5v5M20 15h-5v5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SpeakerOffIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M11 5 6 9H2v6h4l5 4V5Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="m17 9 4 4M21 9l-4 4"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const ChatPanel = forwardRef(function ChatPanel(
  { className = "", onLoadingChange, expanded = false, onToggleExpanded },
  ref,
) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [guardPulse, setGuardPulse] = useState(false);
  // Product names feed the composer's local ghost-text suggester. Reuses the
  // same catalog source as the grid; no second hardcoded copy.
  const [productNames, setProductNames] = useState([]);
  const [voiceOutput, setVoiceOutput] = useState(() => {
    try {
      return localStorage.getItem(VOICE_OUTPUT_KEY) === "1";
    } catch {
      return false;
    }
  });

  // Native live-voice session state (issue #6). Only meaningful when the
  // VITE_VOICE_NATIVE flag is on; otherwise the mic stays the browser floor.
  const [liveActive, setLiveActive] = useState(false);
  const [liveConnecting, setLiveConnecting] = useState(false);
  const [liveFailed, setLiveFailed] = useState(false);
  const [liveNotice, setLiveNotice] = useState(null);

  const threadIdRef = useRef(createAguiIds().threadId);
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const loadingRef = useRef(false);
  const lastSentRef = useRef(null);
  const pulseTimerRef = useRef(null);
  const voiceOutputRef = useRef(voiceOutput);

  const liveSessionRef = useRef(null);
  const liveActiveRef = useRef(false);
  // Accumulators for the two live transcript bubbles in flight.
  const liveUserRef = useRef({ id: null, text: "" });
  const liveAgentRef = useRef({ id: null, text: "" });

  // Let the host (App) mirror streaming state, e.g. to dim the product grid.
  useEffect(() => {
    onLoadingChange?.(loading);
  }, [loading, onLoadingChange]);

  // Pull product names once for the composer suggester.
  useEffect(() => {
    let cancelled = false;
    fetchProducts()
      .then((list) => {
        if (cancelled) return;
        setProductNames(list.map((p) => p?.name).filter(Boolean));
      })
      .catch(() => {
        /* suggester simply falls back to intent phrases */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Coarse conversation hint from the most recent agent message: after a
  // delivery quote, bias toward buying; after a verified order, bias toward a
  // status check. Small and read-only, so it is cheap to thread down.
  const contextHint = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i];
      if (m.role !== "agent") continue;
      const text = (m.text || "").toLowerCase();
      if (!text) continue;
      if (text.includes("payment verified") || text.includes("order status"))
        return "verified";
      if (/deliver|delivery|quote|shipping|fly|flight|naira|₦/.test(text))
        return "quote";
      return null;
    }
    return null;
  }, [messages]);

  // Clear any pending pulse timer on unmount.
  useEffect(() => {
    return () => {
      if (pulseTimerRef.current) window.clearTimeout(pulseTimerRef.current);
    };
  }, []);

  /**
   * Brief border pulse on the panel: shown when a send is ignored by the
   * single-flight guard so the user sees why nothing happened.
   */
  const triggerGuardPulse = useCallback(() => {
    setGuardPulse(false);
    window.requestAnimationFrame(() => {
      setGuardPulse(true);
      if (pulseTimerRef.current) window.clearTimeout(pulseTimerRef.current);
      pulseTimerRef.current = window.setTimeout(
        () => setGuardPulse(false),
        650,
      );
    });
  }, []);

  useEffect(() => {
    voiceOutputRef.current = voiceOutput;
  }, [voiceOutput]);

  // Stop any in-progress speech if the panel unmounts.
  useEffect(() => {
    return () => cancelSpeech();
  }, []);

  const toggleVoiceOutput = useCallback(() => {
    setVoiceOutput((prev) => {
      const next = !prev;
      voiceOutputRef.current = next;
      try {
        localStorage.setItem(VOICE_OUTPUT_KEY, next ? "1" : "0");
      } catch {
        /* ignore storage failures */
      }
      if (!next) cancelSpeech();
      return next;
    });
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const patchMessage = useCallback((messageId, patch) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, ...patch } : m)),
    );
  }, []);

  const appendAgentNote = useCallback((text) => {
    setMessages((prev) => [
      ...prev,
      {
        id: nextLocalId("note"),
        role: "agent",
        text,
        timestamp: new Date(),
        isStreaming: false,
        uiComponents: [],
        streamTools: [],
      },
    ]);
  }, []);

  // Append a message and return its generated id, so live callbacks can patch
  // the same bubble as more transcript / ui frames arrive.
  const appendMessage = useCallback((message) => {
    const id =
      message.id ?? nextLocalId(message.role === "user" ? "user" : "agent");
    setMessages((prev) => [...prev, { ...message, id }]);
    return id;
  }, []);

  // --- Native live voice (issue #6) -------------------------------------
  // These map the live socket frames onto the exact chat / card / payment
  // paths the text channel already uses, so a spoken turn looks identical.

  const finalizeLiveAgent = useCallback(() => {
    if (liveAgentRef.current.id) {
      patchMessage(liveAgentRef.current.id, {
        isStreaming: false,
        streamStatus: null,
      });
      liveAgentRef.current = { id: null, text: "" };
    }
  }, [patchMessage]);

  const handleLiveTranscript = useCallback(
    ({ role, text, final }) => {
      if (!text && !final) return;
      if (role === "user") {
        // A new user utterance finalizes any assistant bubble still streaming
        // (the manager already flushed the assistant audio for barge-in).
        if (!liveUserRef.current.id) {
          finalizeLiveAgent();
          const id = appendMessage({
            role: "user",
            text: text ?? "",
            timestamp: new Date(),
          });
          liveUserRef.current = { id, text: text ?? "" };
        } else {
          liveUserRef.current.text += text ?? "";
          patchMessage(liveUserRef.current.id, {
            text: liveUserRef.current.text,
          });
        }
        if (final) liveUserRef.current = { id: null, text: "" };
        return;
      }
      // assistant
      if (!liveAgentRef.current.id) {
        const id = appendMessage({
          role: "agent",
          text: text ?? "",
          timestamp: new Date(),
          isStreaming: true,
          streamStatus: "writing",
          streamTools: [],
          uiComponents: [],
        });
        liveAgentRef.current = { id, text: text ?? "" };
      } else {
        liveAgentRef.current.text += text ?? "";
        patchMessage(liveAgentRef.current.id, {
          text: liveAgentRef.current.text,
        });
      }
    },
    [appendMessage, patchMessage, finalizeLiveAgent],
  );

  const handleLiveUi = useCallback(
    (components) => {
      const normalized = normalizeAguiComponents(components);
      if (normalized.length === 0) return;
      if (!liveAgentRef.current.id) {
        const id = appendMessage({
          role: "agent",
          text: "",
          timestamp: new Date(),
          isStreaming: true,
          streamStatus: "writing",
          streamTools: [],
          uiComponents: normalized,
        });
        liveAgentRef.current = { id, text: "" };
      } else {
        patchMessage(liveAgentRef.current.id, { uiComponents: normalized });
      }
    },
    [appendMessage, patchMessage],
  );

  const handleLivePaymentEvent = useCallback((paymentEvent) => {
    // Reuse the same normalize + open path the text stream uses, so the
    // Monnify modal opens identically whether the order came by voice or type.
    const normalized = paymentEventFromSnapshot({ payment_event: paymentEvent });
    if (normalized) openPaymentFromStreamEvent(normalized);
  }, []);

  const handleLiveTurnComplete = useCallback(() => {
    finalizeLiveAgent();
  }, [finalizeLiveAgent]);

  const revertToFloor = useCallback(
    (notice) => {
      liveActiveRef.current = false;
      setLiveActive(false);
      setLiveConnecting(false);
      setLiveFailed(true);
      finalizeLiveAgent();
      liveUserRef.current = { id: null, text: "" };
      if (liveSessionRef.current) {
        try {
          liveSessionRef.current.close();
        } catch {
          /* no-op */
        }
        liveSessionRef.current = null;
      }
      setLiveNotice(notice || "Live voice unavailable, using basic voice.");
    },
    [finalizeLiveAgent],
  );

  const stopLive = useCallback(() => {
    liveActiveRef.current = false;
    setLiveActive(false);
    setLiveConnecting(false);
    finalizeLiveAgent();
    liveUserRef.current = { id: null, text: "" };
    if (liveSessionRef.current) {
      try {
        liveSessionRef.current.close();
      } catch {
        /* no-op */
      }
      liveSessionRef.current = null;
    }
  }, [finalizeLiveAgent]);

  const startLive = useCallback(async () => {
    if (liveActiveRef.current || liveConnecting) return;
    setLiveNotice(null);
    setLiveConnecting(true);
    cancelSpeech(); // never let the floor TTS and the live audio overlap
    const session = new LiveVoiceSession();
    liveSessionRef.current = session;
    try {
      await session.connect(threadIdRef.current, {
        onTranscript: handleLiveTranscript,
        onPaymentEvent: handleLivePaymentEvent,
        onUi: handleLiveUi,
        onTurnComplete: handleLiveTurnComplete,
        onError: () =>
          revertToFloor("Live voice unavailable, using basic voice."),
        onClose: () =>
          revertToFloor("Live voice unavailable, using basic voice."),
      });
      liveActiveRef.current = true;
      setLiveActive(true);
      setLiveConnecting(false);
    } catch {
      liveSessionRef.current = null;
      setLiveConnecting(false);
      revertToFloor("Live voice unavailable, using basic voice.");
    }
  }, [
    liveConnecting,
    handleLiveTranscript,
    handleLivePaymentEvent,
    handleLiveUi,
    handleLiveTurnComplete,
    revertToFloor,
  ]);

  const toggleLive = useCallback(() => {
    if (liveActiveRef.current) stopLive();
    else startLive();
  }, [startLive, stopLive]);

  // Tear the live session down if the panel unmounts.
  useEffect(() => {
    return () => {
      if (liveSessionRef.current) {
        try {
          liveSessionRef.current.close();
        } catch {
          /* no-op */
        }
        liveSessionRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const handleVerified = (event) => {
      const reference = event?.detail?.reference;
      appendAgentNote(
        reference
          ? `Payment verified for order ${reference}. Thank you for shopping with Oja Connect!`
          : "Payment verified. Thank you for shopping with Oja Connect!",
      );
    };
    window.addEventListener("order-verified", handleVerified);
    return () => window.removeEventListener("order-verified", handleVerified);
  }, [appendAgentNote]);

  const sendMessage = useCallback(
    async (rawText) => {
      const text = (rawText ?? "").trim();
      if (!text) return;

      // Single-flight guard: exactly one agent turn in flight. Every send
      // (composer, cards, chips, voice) funnels through here, so gating here
      // covers them all. While a turn streams, further sends are ignored:
      // no queueing, no aborting. An identical repeat of the in-flight ask
      // is a deduped silent no-op; any other ignored send pulses the panel
      // border so the user sees why nothing happened.
      if (loadingRef.current) {
        if (text !== lastSentRef.current) triggerGuardPulse();
        return;
      }
      // Set synchronously (not via effect) so a rapid double click cannot
      // race past the guard before React re-renders.
      loadingRef.current = true;
      lastSentRef.current = text;

      // A new turn starts: silence any reply still being spoken.
      cancelSpeech();

      const userMessage = {
        id: nextLocalId("user"),
        role: "user",
        text,
        timestamp: new Date(),
      };
      const agentMessageId = nextLocalId("agent");
      const agentMessage = {
        id: agentMessageId,
        role: "agent",
        text: "",
        timestamp: new Date(),
        isStreaming: true,
        streamStatus: "thinking",
        streamTools: [],
        streamTool: null,
        uiComponents: [],
      };

      setMessages((prev) => [...prev, userMessage, agentMessage]);
      setInput("");
      setLoading(true);

      let finalText = "";
      try {
        await runAguiStreamTurn({
          threadId: threadIdRef.current,
          userContent: text,
          onPatch: (patch) => {
            if (typeof patch.text === "string") finalText = patch.text;
            patchMessage(agentMessageId, patch);
          },
        });
        // Speak only the settled assistant text, once, when voice mode is on.
        if (voiceOutputRef.current && finalText.trim()) {
          speak(finalText);
        }
      } catch (error) {
        patchMessage(agentMessageId, {
          isStreaming: false,
          streamStatus: null,
          streamTools: [],
          text:
            error?.message && !/failed to fetch/i.test(error.message)
              ? `Something went wrong: ${error.message}`
              : "I could not reach the shop right now. Make sure the backend is running, then try again.",
        });
      } finally {
        loadingRef.current = false;
        lastSentRef.current = null;
        setLoading(false);
      }
    },
    [patchMessage, triggerGuardPulse],
  );

  const insertPrompt = useCallback((text) => {
    setInput(text);
    window.setTimeout(() => {
      const el = inputRef.current;
      if (el) {
        el.focus();
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
      }
    }, 0);
  }, []);

  useImperativeHandle(ref, () => ({ insertPrompt, sendMessage }), [
    insertPrompt,
    sendMessage,
  ]);

  const handleUiAction = useCallback(
    (action) => {
      if (action?.type === "send" && action.text) {
        sendMessage(action.text);
      }
    },
    [sendMessage],
  );

  return (
    <div
      className={`flex h-full min-h-0 flex-col bg-surface ${
        guardPulse ? "turn-guard-pulse" : ""
      } ${className}`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-line bg-white px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-ink">Market assistant</h2>
          <p className="text-xs text-ink-muted">
            Browse, ask, and buy in one conversation
          </p>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          {/* Desktop-only width toggle. Hidden on mobile, where the panel is a
              full-screen bottom sheet and width does not apply. */}
          {onToggleExpanded ? (
            <button
              type="button"
              onClick={onToggleExpanded}
              aria-label={expanded ? "Collapse chat" : "Expand chat"}
              aria-pressed={expanded}
              title={expanded ? "Collapse chat" : "Expand chat"}
              className="hidden h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border border-line text-ink-muted transition-all hover:bg-surface-alt active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 lg:flex"
            >
              {expanded ? <CollapseIcon /> : <ExpandIcon />}
            </button>
          ) : null}
          {isSpeechSynthesisSupported ? (
            <button
              type="button"
              onClick={toggleVoiceOutput}
              aria-label="Turn voice replies on/off"
              aria-pressed={voiceOutput}
              title={voiceOutput ? "Voice replies on" : "Voice replies off"}
              className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border transition-all active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                voiceOutput
                  ? "border-brand bg-brand text-white hover:bg-brand-hover"
                  : "border-line text-ink-muted hover:bg-surface-alt"
              }`}
            >
              {voiceOutput ? <SpeakerOnIcon /> : <SpeakerOffIcon />}
            </button>
          ) : null}
        </div>
      </div>

      <div
        ref={scrollRef}
        className="chat-scroll min-h-0 flex-1 overflow-y-auto px-4 py-4"
      >
        {messages.length === 0 ? (
          <ChatEmptyState onSuggestion={sendMessage} />
        ) : (
          messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              onUiAction={handleUiAction}
              uiDisabled={loading}
            />
          ))
        )}
      </div>

      <div className="border-t border-line bg-surface px-4 pb-3 pt-3">
        {liveNotice ? (
          <div
            role="status"
            className="mb-2 flex items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800"
          >
            <span className="min-w-0">{liveNotice}</span>
            <button
              type="button"
              onClick={() => setLiveNotice(null)}
              aria-label="Dismiss notice"
              className="flex-shrink-0 rounded px-1 font-medium text-amber-700 hover:text-amber-900"
            >
              Dismiss
            </button>
          </div>
        ) : null}
        <ChatComposer
          input={input}
          setInput={setInput}
          onSend={() => sendMessage(input)}
          onVoiceSend={sendMessage}
          loading={loading}
          inputRef={inputRef}
          productNames={productNames}
          contextHint={contextHint}
          nativeVoice={isNativeVoiceEnabled && !liveFailed}
          liveActive={liveActive}
          liveConnecting={liveConnecting}
          onToggleLive={toggleLive}
        />
      </div>
    </div>
  );
});

export default ChatPanel;
