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

/**
 * Rank a voice for naturalness. The browser default is often the robotic
 * fallback, so we actively prefer the modern natural voices when present:
 * Chrome's Google voices, macOS enhanced/premium voices, and the Edge
 * "Natural" online voices. Higher score wins.
 */
function scoreVoice(voice) {
  const name = (voice.name || "").toLowerCase();
  let score = 0;
  if (name.includes("natural")) score += 60; // Edge "... (Natural)"
  if (name.includes("google")) score += 50; // Chrome Google voices
  if (name.includes("enhanced") || name.includes("premium")) score += 40; // macOS
  // Known pleasant macOS/system English voices.
  if (/\b(samantha|ava|allison|zoe|serena|aria|jenny|evan)\b/.test(name)) {
    score += 25;
  }
  if (name.includes("siri")) score += 30;
  // Nudge away from the classic robotic fallbacks.
  if (/\b(albert|fred|zarvox|bad news|trinoids|junior|ralph)\b/.test(name)) {
    score -= 50;
  }
  return score;
}

let cachedVoice = null;
let cachedVoiceLang = null;

/** Pick the most natural available voice for the language. */
function getPreferredVoice(lang) {
  if (!isSpeechSynthesisSupported) return null;
  const voices = window.speechSynthesis.getVoices();
  if (!voices || voices.length === 0) return null;
  const wanted = (lang || "en-US").slice(0, 2).toLowerCase();
  if (cachedVoice && cachedVoiceLang === wanted && voices.includes(cachedVoice)) {
    return cachedVoice;
  }
  const matches = voices.filter((v) =>
    (v.lang || "").slice(0, 2).toLowerCase() === wanted,
  );
  const pool = matches.length > 0 ? matches : voices;
  const best = pool
    .slice()
    .sort((a, b) => scoreVoice(b) - scoreVoice(a))[0];
  cachedVoice = best || null;
  cachedVoiceLang = wanted;
  return cachedVoice;
}

// Voices load asynchronously in some browsers; warm the list and reset the
// cache when it arrives so the first spoken reply already uses a good voice.
if (isSpeechSynthesisSupported) {
  window.speechSynthesis.getVoices();
  window.speechSynthesis.addEventListener?.("voiceschanged", () => {
    cachedVoice = null;
  });
}

/** Speak the given text once. No-op when unsupported or empty. */
export function speak(text, options = {}) {
  if (!isSpeechSynthesisSupported) return;
  const clean = stripMarkdown(text);
  if (!clean) return;
  const synth = window.speechSynthesis;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(clean);
  const lang = options.lang || "en-US";
  utterance.lang = lang;
  const voice = getPreferredVoice(lang);
  if (voice) utterance.voice = voice;
  // A hair slower than default reads as calmer and less clipped.
  utterance.rate = options.rate ?? 0.98;
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
