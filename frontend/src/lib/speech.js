/**
 * Browser voice helpers: speech-to-text (Web Speech API) and
 * text-to-speech (speechSynthesis). Thin, reusable wrappers so a later
 * native voice mode can reuse the same mic button and voice-mode toggle.
 */

const SpeechRecognitionImpl =
  typeof window !== "undefined"
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : null;

export const isSpeechRecognitionSupported = Boolean(SpeechRecognitionImpl);

export const isSpeechSynthesisSupported =
  typeof window !== "undefined" && "speechSynthesis" in window;

/**
 * Create a thin speech recognizer. Returns null when unsupported.
 *
 * @param {object} [options]
 * @param {boolean} [options.interimResults=true]
 * @param {boolean} [options.continuous=false]
 * @param {string}  [options.lang="en-US"]
 * @returns {{ start: Function, stop: Function, isSupported: boolean } | null}
 */
export function createSpeechRecognizer(options = {}) {
  if (!SpeechRecognitionImpl) return null;

  const {
    interimResults = true,
    continuous = false,
    lang = "en-US",
  } = options;

  const recognition = new SpeechRecognitionImpl();
  recognition.interimResults = interimResults;
  recognition.continuous = continuous;
  recognition.lang = lang;
  recognition.maxAlternatives = 1;

  let active = false;

  /**
   * @param {(interim: string) => void} onInterim
   * @param {(final: string) => void} onFinal
   * @param {(error: string) => void} onError
   */
  function start(onInterim, onFinal, onError) {
    recognition.onresult = (event) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) final += transcript;
        else interim += transcript;
      }
      if (interim && onInterim) onInterim(interim);
      if (final && onFinal) onFinal(final.trim());
    };
    recognition.onerror = (event) => {
      active = false;
      if (onError) onError(event?.error || "speech-error");
    };
    recognition.onend = () => {
      active = false;
    };
    try {
      recognition.start();
      active = true;
    } catch (err) {
      // start() throws if it is already running; treat as a soft error.
      if (onError) onError(err?.message || "speech-start-failed");
    }
  }

  function stop() {
    try {
      recognition.stop();
    } catch {
      /* no-op */
    }
    active = false;
  }

  return {
    start,
    stop,
    isSupported: true,
    get active() {
      return active;
    },
  };
}

/** Light markdown strip so TTS reads plain prose, not syntax. */
export function stripMarkdown(text) {
  if (!text) return "";
  return String(text)
    .replace(/```[\s\S]*?```/g, " ") // fenced code blocks
    .replace(/`([^`]*)`/g, "$1") // inline code
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ") // images
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1") // links keep the label
    .replace(/^#{1,6}\s+/gm, "") // headings
    .replace(/^\s*>\s?/gm, "") // blockquotes
    .replace(/^\s*[-+]\s+/gm, "") // list bullets
    .replace(/[*_~]/g, "") // emphasis marks
    .replace(/\s+/g, " ")
    .trim();
}

/** Speak the given text once. No-op when unsupported or empty. */
export function speak(text, options = {}) {
  if (!isSpeechSynthesisSupported) return;
  const clean = stripMarkdown(text);
  if (!clean) return;
  const synth = window.speechSynthesis;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(clean);
  utterance.lang = options.lang || "en-US";
  utterance.rate = options.rate ?? 1;
  utterance.pitch = options.pitch ?? 1;
  synth.speak(utterance);
}

/** Stop any in-progress speech. */
export function cancelSpeech() {
  if (!isSpeechSynthesisSupported) return;
  try {
    window.speechSynthesis.cancel();
  } catch {
    /* no-op */
  }
}

/** Whether TTS is currently talking. */
export function isSpeaking() {
  return isSpeechSynthesisSupported && window.speechSynthesis.speaking;
}
