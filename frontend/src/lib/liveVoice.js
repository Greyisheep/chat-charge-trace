/**
 * Native Gemini Live voice session for the browser.
 *
 * This is the "star" voice path from issue #6. It opens a WebSocket to the
 * backend live endpoint (/v1/agents/live), streams mic audio up as 16kHz mono
 * PCM16, and plays the model's 24kHz PCM16 audio back gaplessly. Transcript,
 * ui, and state frames are handed to the caller so they render through the
 * exact same chat, product-card, and Monnify-popup paths the text channel uses.
 *
 * It is feature-flagged at the call site (VITE_VOICE_NATIVE). The browser
 * push-to-talk floor in speech.js stays the automatic fallback: connect()
 * rejects on any open failure, and the session reports errors/closes so the UI
 * can revert to the floor for that session.
 */

import { API_BASE_URL } from "../config";

const INPUT_TARGET_RATE = 16000; // what the backend expects on the way up
const OUTPUT_RATE = 24000; // what the backend sends on the way down
const SEND_INTERVAL_MS = 150; // mic chunk cadence
const PLAYBACK_LEAD_S = 0.06; // small scheduling lead so the first chunk is smooth

/**
 * Derive the ws(s) URL for the live endpoint from the REST API base.
 *
 * A non-empty API base (e.g. http://localhost:8000) points at a separate host,
 * so we reuse its host and swap the scheme. An empty base means same-origin
 * (the docker image, where nginx proxies /v1), so we use the page's own host.
 */
export function deriveLiveWsUrl(path = "/v1/agents/live") {
  const base = API_BASE_URL;
  if (base) {
    const url = new URL(base);
    const scheme = url.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${url.host}${path}`;
  }
  if (typeof window !== "undefined" && window.location) {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}${path}`;
  }
  return `ws://localhost:8000${path}`;
}

// A tiny AudioWorklet that copies each input frame up to the main thread. It is
// injected as a Blob URL so no separate asset file is needed. When AudioWorklet
// is unavailable we fall back to a ScriptProcessorNode.
const WORKLET_SOURCE = `
class MicCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}
registerProcessor('mic-capture', MicCaptureProcessor);
`;

function floatToPcm16Base64(float32) {
  const pcm = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i += 1) {
    let s = float32[i];
    if (s > 1) s = 1;
    else if (s < -1) s = -1;
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  const bytes = new Uint8Array(pcm.buffer);
  // btoa over a binary string, chunked to avoid call-stack limits on big buffers.
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(
      null,
      bytes.subarray(i, i + chunk),
    );
  }
  return btoa(binary);
}

function base64ToPcm16Float(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const view = new DataView(bytes.buffer);
  const count = Math.floor(bytes.length / 2);
  const float32 = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    const sample = view.getInt16(i * 2, true); // little-endian
    float32[i] = sample < 0 ? sample / 0x8000 : sample / 0x7fff;
  }
  return float32;
}

export class LiveVoiceSession {
  constructor() {
    this.ws = null;
    this.handlers = {};
    this.threadId = null;

    // Mic capture side.
    this.micStream = null;
    this.inputContext = null;
    this.workletNode = null;
    this.scriptNode = null;
    this.muteGain = null;
    this.sendTimer = null;
    this._pendingChunks = []; // Float32Array pieces captured at the input rate
    this._resamplePos = 0; // fractional read cursor carried across flushes
    this._inputRate = 48000;

    // Playback side (24kHz).
    this.outputContext = null;
    this.outputGain = null;
    this._nextStartTime = 0;
    this._activeSources = new Set();

    this._closed = false;
    this._ready = false;
    this._workletUrl = null;
  }

  /**
   * Open the socket and start capturing. Resolves once the backend has sent
   * {"type":"ready"} and the mic is streaming. Rejects on any failure to open
   * the socket or acquire the mic, so the caller can fall back to the floor.
   *
   * @param {string} threadId
   * @param {object} handlers
   * @param {(t:{role:string,text:string,final:boolean})=>void} [handlers.onTranscript]
   * @param {(paymentEvent:object)=>void} [handlers.onPaymentEvent]
   * @param {(components:object[])=>void} [handlers.onUi]
   * @param {()=>void} [handlers.onTurnComplete]
   * @param {(message:string)=>void} [handlers.onError]
   * @param {()=>void} [handlers.onClose]
   */
  connect(threadId, handlers = {}) {
    this.threadId = threadId;
    this.handlers = handlers;
    this._closed = false;

    return new Promise((resolve, reject) => {
      let settled = false;
      const fail = (message) => {
        if (settled) return;
        settled = true;
        this._teardown();
        reject(new Error(message || "live voice connection failed"));
      };

      let ws;
      try {
        ws = new WebSocket(deriveLiveWsUrl());
      } catch (err) {
        fail(err?.message || "could not open live socket");
        return;
      }
      this.ws = ws;

      ws.onopen = () => {
        this._safeSend({ type: "start", threadId });
      };

      ws.onmessage = async (event) => {
        let frame;
        try {
          frame = JSON.parse(event.data);
        } catch {
          return; // binary/unknown frames are not part of the JSON baseline
        }
        if (frame?.type === "ready" && !this._ready) {
          this._ready = true;
          try {
            await this._startCapture();
          } catch (err) {
            fail(err?.message || "microphone unavailable");
            return;
          }
          if (!settled) {
            settled = true;
            resolve();
          }
          return;
        }
        this._handleFrame(frame);
      };

      ws.onerror = () => {
        // Before ready this is a hard open failure; after ready it is a
        // mid-session drop. Either way the UI reverts to the floor.
        if (!settled) fail("live socket error");
        else this._emitError("live socket error");
      };

      ws.onclose = () => {
        if (!settled) {
          fail("live socket closed before ready");
          return;
        }
        if (!this._closed) {
          // Unexpected close mid-session: surface it, then tear down.
          this._closed = true;
          this.handlers.onClose?.();
          this._teardown();
        }
      };
    });
  }

  _handleFrame(frame) {
    if (!frame || typeof frame !== "object") return;
    switch (frame.type) {
      case "audio":
        if (typeof frame.data === "string" && frame.data) {
          this._enqueuePlayback(frame.data);
        }
        break;
      case "transcript":
        // A fresh user utterance is a barge-in: drop any queued assistant audio.
        if (frame.role === "user" && frame.text) this._flushPlayback();
        this.handlers.onTranscript?.({
          role: frame.role,
          text: frame.text ?? "",
          final: Boolean(frame.final),
        });
        break;
      case "state":
        if (frame.payment_event) {
          this.handlers.onPaymentEvent?.(frame.payment_event);
        }
        break;
      case "ui":
        if (Array.isArray(frame.components)) {
          this.handlers.onUi?.(frame.components);
        }
        break;
      case "turn_complete":
        this.handlers.onTurnComplete?.();
        break;
      case "error":
        this._emitError(frame.message || "live voice error");
        break;
      default:
        break;
    }
  }

  _emitError(message) {
    if (this._closed) return;
    this._closed = true;
    this.handlers.onError?.(message);
    this._teardown();
  }

  // --- Mic capture -------------------------------------------------------

  async _startCapture() {
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    this.inputContext = new AudioCtx();
    // A user gesture starts this flow, but resume defensively for autoplay policy.
    if (this.inputContext.state === "suspended") {
      await this.inputContext.resume().catch(() => {});
    }
    this._inputRate = this.inputContext.sampleRate || 48000;

    const source = this.inputContext.createMediaStreamSource(this.micStream);
    // A silent sink keeps the capture node in the graph without echoing the mic.
    this.muteGain = this.inputContext.createGain();
    this.muteGain.gain.value = 0;
    this.muteGain.connect(this.inputContext.destination);

    const onSamples = (float32) => {
      if (this._closed) return;
      // Copy: the underlying buffer is reused by the audio thread.
      this._pendingChunks.push(new Float32Array(float32));
    };

    let usedWorklet = false;
    if (this.inputContext.audioWorklet) {
      try {
        const blob = new Blob([WORKLET_SOURCE], {
          type: "application/javascript",
        });
        this._workletUrl = URL.createObjectURL(blob);
        await this.inputContext.audioWorklet.addModule(this._workletUrl);
        this.workletNode = new AudioWorkletNode(
          this.inputContext,
          "mic-capture",
        );
        this.workletNode.port.onmessage = (e) => onSamples(e.data);
        source.connect(this.workletNode);
        this.workletNode.connect(this.muteGain);
        usedWorklet = true;
      } catch {
        usedWorklet = false;
      }
    }

    if (!usedWorklet) {
      // ScriptProcessorNode fallback (deprecated but broadly supported).
      const node = this.inputContext.createScriptProcessor(4096, 1, 1);
      node.onaudioprocess = (e) => onSamples(e.inputBuffer.getChannelData(0));
      source.connect(node);
      node.connect(this.muteGain);
      this.scriptNode = node;
    }

    this.sendTimer = window.setInterval(
      () => this._flushMic(),
      SEND_INTERVAL_MS,
    );
  }

  /** Concatenate captured chunks, resample to 16kHz, encode, and send. */
  _flushMic() {
    if (this._closed || this._pendingChunks.length === 0) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    let total = 0;
    for (const c of this._pendingChunks) total += c.length;
    const input = new Float32Array(total);
    let offset = 0;
    for (const c of this._pendingChunks) {
      input.set(c, offset);
      offset += c.length;
    }
    this._pendingChunks = [];

    const ratio = this._inputRate / INPUT_TARGET_RATE;
    const out = [];
    let pos = this._resamplePos;
    // Linear interpolation resample. We only consume samples that have a right
    // neighbour, then carry the fractional position forward so there is no drift
    // or click at chunk boundaries.
    while (pos + 1 < input.length) {
      const i = Math.floor(pos);
      const frac = pos - i;
      out.push(input[i] * (1 - frac) + input[i + 1] * frac);
      pos += ratio;
    }
    // Preserve the fractional remainder relative to the last unconsumed sample.
    const consumed = Math.floor(pos);
    this._resamplePos = pos - consumed;
    // Keep the tail sample(s) so interpolation stays continuous next flush.
    const leftover = input.subarray(Math.min(consumed, input.length));
    if (leftover.length > 0) this._pendingChunks.push(new Float32Array(leftover));

    if (out.length === 0) return;
    const data = floatToPcm16Base64(Float32Array.from(out));
    this._safeSend({ type: "audio", data });
  }

  // --- Playback ----------------------------------------------------------

  _ensureOutputContext() {
    if (this.outputContext) return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    // Ask for a 24kHz context so incoming PCM needs no resample.
    try {
      this.outputContext = new AudioCtx({ sampleRate: OUTPUT_RATE });
    } catch {
      this.outputContext = new AudioCtx();
    }
    this.outputGain = this.outputContext.createGain();
    this.outputGain.connect(this.outputContext.destination);
    this._nextStartTime = 0;
  }

  _enqueuePlayback(base64) {
    this._ensureOutputContext();
    const ctx = this.outputContext;
    if (ctx.state === "suspended") ctx.resume().catch(() => {});

    const float32 = base64ToPcm16Float(base64);
    if (float32.length === 0) return;

    // The context may already run at 24kHz; if the platform ignored the hint
    // and gave us another rate, the buffer still plays at that rate which is a
    // graceful (if slightly pitched) degradation rather than silence.
    const buffer = ctx.createBuffer(1, float32.length, OUTPUT_RATE);
    buffer.copyToChannel(float32, 0);

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.outputGain);

    const now = ctx.currentTime;
    if (this._nextStartTime < now + PLAYBACK_LEAD_S) {
      this._nextStartTime = now + PLAYBACK_LEAD_S;
    }
    src.start(this._nextStartTime);
    this._nextStartTime += buffer.duration;

    this._activeSources.add(src);
    src.onended = () => this._activeSources.delete(src);
  }

  /** Stop and drop all queued/playing assistant audio (barge-in, turn reset). */
  _flushPlayback() {
    for (const src of this._activeSources) {
      try {
        src.onended = null;
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    this._activeSources.clear();
    this._nextStartTime = 0;
  }

  // --- Teardown ----------------------------------------------------------

  /** Public close: politely stop the turn and release everything. No leaks. */
  close() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this._safeSend({ type: "stop" });
    }
    this._closed = true;
    this._teardown();
  }

  _teardown() {
    if (this.sendTimer) {
      window.clearInterval(this.sendTimer);
      this.sendTimer = null;
    }
    this._flushPlayback();

    if (this.workletNode) {
      try {
        this.workletNode.port.onmessage = null;
        this.workletNode.disconnect();
      } catch {
        /* no-op */
      }
      this.workletNode = null;
    }
    if (this.scriptNode) {
      try {
        this.scriptNode.onaudioprocess = null;
        this.scriptNode.disconnect();
      } catch {
        /* no-op */
      }
      this.scriptNode = null;
    }
    if (this.muteGain) {
      try {
        this.muteGain.disconnect();
      } catch {
        /* no-op */
      }
      this.muteGain = null;
    }
    if (this.micStream) {
      for (const track of this.micStream.getTracks()) track.stop();
      this.micStream = null;
    }
    if (this.inputContext) {
      this.inputContext.close().catch(() => {});
      this.inputContext = null;
    }
    if (this.outputContext) {
      this.outputContext.close().catch(() => {});
      this.outputContext = null;
      this.outputGain = null;
    }
    if (this._workletUrl) {
      URL.revokeObjectURL(this._workletUrl);
      this._workletUrl = null;
    }
    this._pendingChunks = [];
    this._resamplePos = 0;

    if (this.ws) {
      try {
        this.ws.onopen = null;
        this.ws.onmessage = null;
        this.ws.onerror = null;
        this.ws.onclose = null;
        if (
          this.ws.readyState === WebSocket.OPEN ||
          this.ws.readyState === WebSocket.CONNECTING
        ) {
          this.ws.close();
        }
      } catch {
        /* no-op */
      }
      this.ws = null;
    }
  }

  _safeSend(obj) {
    try {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify(obj));
      }
    } catch {
      /* socket went away between the check and the send */
    }
  }
}

/** Feature flag: native live voice on only when VITE_VOICE_NATIVE === "1". */
export const isNativeVoiceEnabled =
  import.meta.env.VITE_VOICE_NATIVE === "1";
