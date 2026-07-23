/** Chat panel: message list, streaming turns, composer, verified-order notes. */

import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { createAguiIds } from "../../lib/aguiStream";
import { runAguiStreamTurn } from "../../lib/runAguiStreamTurn";
import {
  cancelSpeech,
  isSpeechSynthesisSupported,
  speak,
} from "../../lib/speech";
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
  { className = "", onLoadingChange },
  ref,
) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [guardPulse, setGuardPulse] = useState(false);
  const [voiceOutput, setVoiceOutput] = useState(() => {
    try {
      return localStorage.getItem(VOICE_OUTPUT_KEY) === "1";
    } catch {
      return false;
    }
  });

  const threadIdRef = useRef(createAguiIds().threadId);
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const loadingRef = useRef(false);
  const lastSentRef = useRef(null);
  const pulseTimerRef = useRef(null);
  const voiceOutputRef = useRef(voiceOutput);

  // Let the host (App) mirror streaming state, e.g. to dim the product grid.
  useEffect(() => {
    onLoadingChange?.(loading);
  }, [loading, onLoadingChange]);

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
        {isSpeechSynthesisSupported ? (
          <button
            type="button"
            onClick={toggleVoiceOutput}
            aria-label="Turn voice replies on/off"
            aria-pressed={voiceOutput}
            title={
              voiceOutput ? "Voice replies on" : "Voice replies off"
            }
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
        <ChatComposer
          input={input}
          setInput={setInput}
          onSend={() => sendMessage(input)}
          onVoiceSend={sendMessage}
          loading={loading}
          inputRef={inputRef}
        />
      </div>
    </div>
  );
});

export default ChatPanel;
