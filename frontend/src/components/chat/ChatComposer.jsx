/** Floating rounded composer with auto-grow textarea and voice-input mic. */

import React, { useEffect, useRef, useState } from "react";
import {
  cancelSpeech,
  createSpeechRecognizer,
  isSpeechRecognitionSupported,
} from "../../lib/speech";
import { suggestFor } from "../../lib/suggestions";

function SendIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" aria-hidden>
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M10.5889 3.577a.833.833 0 0 0-1.178 0L4.827 8.16a.833.833 0 1 0 1.178 1.179L9.167 6.178V15.833a.833.833 0 1 0 1.666 0V6.178l3.161 3.161a.833.833 0 1 0 1.178-1.178L10.59 3.577Z"
        fill="currentColor"
      />
    </svg>
  );
}

function MicIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function ChatComposer({
  input,
  setInput,
  onSend,
  onVoiceSend,
  loading = false,
  inputRef,
  placeholder = "Ask about anything in the shop",
  productNames = [],
  contextHint = null,
  nativeVoice = false,
  liveActive = false,
  liveConnecting = false,
  onToggleLive,
}) {
  const [focused, setFocused] = useState(false);
  const [listening, setListening] = useState(false);
  // While dismissed, the ghost stays hidden until the input changes again.
  const [dismissed, setDismissed] = useState(false);
  const recognizerRef = useRef(null);
  const overlayRef = useRef(null);
  const canSend = Boolean(input?.trim());

  // In native mode the mic uses getUserMedia (via the live session), so the
  // button shows even when the Web Speech recognizer is missing. In floor mode
  // it stays gated on recognizer support exactly as before.
  const showMic = nativeVoice || isSpeechRecognitionSupported;

  // Deterministic, local suggestion. Suppressed while the mic is filling the
  // textarea and while a suggestion has been explicitly dismissed. The result
  // always starts with the exact input, so the ghost tail is a plain slice.
  const suggestion =
    !listening && !dismissed && input?.trim()
      ? suggestFor(input, { products: productNames, hint: contextHint })
      : null;
  const ghostRemainder = suggestion ? suggestion.slice(input.length) : "";

  const acceptSuggestion = () => {
    if (!suggestion) return;
    setInput(suggestion);
    setDismissed(false);
    // Resize and drop the caret at the end after React applies the new value.
    window.requestAnimationFrame(() => {
      const el = inputRef?.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
      const end = suggestion.length;
      el.setSelectionRange(end, end);
      el.focus();
    });
  };

  useEffect(() => {
    return () => {
      recognizerRef.current?.stop();
    };
  }, []);

  const stopListening = () => {
    recognizerRef.current?.stop();
    setListening(false);
  };

  const startListening = () => {
    // Never let the mic pick up the agent talking to itself.
    cancelSpeech();
    if (!recognizerRef.current) {
      recognizerRef.current = createSpeechRecognizer();
    }
    const recognizer = recognizerRef.current;
    if (!recognizer) return;

    setListening(true);
    recognizer.start(
      (interim) => setInput(interim),
      (final) => {
        setListening(false);
        setInput(final);
        if (final && !loading) {
          if (onVoiceSend) onVoiceSend(final);
          else onSend();
        }
      },
      () => setListening(false),
    );
  };

  const toggleListening = () => {
    if (listening) stopListening();
    else startListening();
  };

  const handleKeyDown = (e) => {
    // Tab accepts the active ghost without moving focus.
    if (e.key === "Tab" && ghostRemainder) {
      e.preventDefault();
      acceptSuggestion();
      return;
    }
    // Escape hides the current ghost until the input changes again.
    if (e.key === "Escape" && ghostRemainder) {
      e.preventDefault();
      setDismissed(true);
      return;
    }
    // Enter still sends and must never accept the ghost.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend && !loading) onSend();
    }
  };

  return (
    <div className="w-full">
      <div
        className={`flex min-h-[44px] items-center gap-2 rounded-full border bg-white px-3 py-1.5 shadow-[0_1px_6px_rgba(16,24,40,0.06)] transition-all ${
          focused
            ? "border-brand shadow-[0_0_0_3px_rgba(37,99,235,0.12),0_1px_6px_rgba(16,24,40,0.06)]"
            : "border-line-strong hover:border-[#98A2B3]"
        }`}
      >
        {showMic ? (
          nativeVoice ? (
            <button
              type="button"
              onClick={onToggleLive}
              disabled={liveConnecting}
              aria-label={liveActive ? "Stop live voice" : "Start live voice"}
              aria-pressed={liveActive}
              title={
                liveConnecting
                  ? "Connecting live voice"
                  : liveActive
                    ? "Stop live voice"
                    : "Start live voice"
              }
              className={`relative flex h-9 w-9 min-h-[36px] min-w-[36px] flex-shrink-0 items-center justify-center rounded-full transition-all active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                liveActive
                  ? "bg-emerald-50 text-emerald-600"
                  : "text-ink-muted hover:bg-surface-alt disabled:cursor-not-allowed disabled:opacity-50"
              }`}
            >
              {liveActive ? (
                <>
                  <span
                    className="absolute inset-0 animate-ping rounded-full bg-emerald-400/30"
                    aria-hidden
                  />
                  <span
                    className="absolute inset-0 rounded-full ring-2 ring-emerald-500"
                    aria-hidden
                  />
                </>
              ) : null}
              {liveConnecting ? (
                <span
                  className="absolute inset-0 animate-pulse rounded-full ring-2 ring-emerald-300"
                  aria-hidden
                />
              ) : null}
              <MicIcon />
            </button>
          ) : (
            <button
              type="button"
              onClick={toggleListening}
              disabled={loading}
              aria-label={listening ? "Stop voice input" : "Start voice input"}
              title={listening ? "Stop voice input" : "Start voice input"}
              className={`relative flex h-9 w-9 min-h-[36px] min-w-[36px] flex-shrink-0 items-center justify-center rounded-full transition-all active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                listening
                  ? "bg-red-50 text-red-500"
                  : "text-ink-muted hover:bg-surface-alt disabled:cursor-not-allowed disabled:opacity-50"
              }`}
            >
              {listening ? (
                <span
                  className="absolute inset-0 animate-pulse rounded-full ring-2 ring-red-400"
                  aria-hidden
                />
              ) : null}
              <MicIcon />
            </button>
          )
        ) : null}
        <div className="relative min-w-0 flex-1 self-center">
          {/* Ghost overlay: same box and text metrics as the textarea. The
              typed portion is transparent so the real textarea text shows
              through on top, and only the suggested tail renders in gray. */}
          {ghostRemainder ? (
            <div
              ref={overlayRef}
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 max-h-[120px] overflow-hidden whitespace-pre-wrap break-words py-1 text-[14px] leading-6 text-transparent"
            >
              <span>{input}</span>
              <span className="text-[#98A2B3]">{ghostRemainder}</span>
            </div>
          ) : null}
          <textarea
            ref={inputRef}
            placeholder={placeholder}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              setDismissed(false);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
            }}
            onScroll={(e) => {
              if (overlayRef.current)
                overlayRef.current.scrollTop = e.target.scrollTop;
            }}
            onKeyDown={handleKeyDown}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            disabled={loading}
            rows={1}
            className="relative z-[1] max-h-[120px] min-h-[24px] w-full resize-none border-0 bg-transparent py-1 text-[14px] leading-6 text-ink-body placeholder-[#98A2B3] outline-none focus:ring-0 disabled:opacity-50"
          />
        </div>
        <button
          type="button"
          onClick={onSend}
          disabled={loading || !canSend}
          className={`flex h-9 w-9 min-h-[36px] min-w-[36px] flex-shrink-0 items-center justify-center rounded-full transition-all active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
            loading || !canSend
              ? "cursor-not-allowed bg-[#B8D4F8] text-white"
              : "cursor-pointer bg-brand text-white hover:bg-brand-hover"
          }`}
          aria-label="Send message"
        >
          <SendIcon />
        </button>
      </div>
      <p className="mt-1.5 overflow-hidden text-ellipsis whitespace-nowrap px-1 pt-1 text-center text-[10px] leading-tight text-[#98A2B3]">
        The shop assistant may be inaccurate. Payments run on the Monnify sandbox.
      </p>
    </div>
  );
}
