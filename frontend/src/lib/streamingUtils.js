/** AG-UI stream helpers: hidden tools plus throttled text patches. */

/** Internal routing tools that never show in the tool pill list. */
export const HIDDEN_STREAM_TOOLS = new Set(["transfer_to_agent"]);

export function isHiddenStreamTool(name) {
  return HIDDEN_STREAM_TOOLS.has(name);
}

export function filterVisibleStreamTools(tools = []) {
  return tools.filter((t) => t?.name && !isHiddenStreamTool(t.name));
}

/** Throttle text patches (~12fps) so the bubble grows smoothly without layout thrash. */
export function createThrottledTextPatch(onPatch, intervalMs = 80) {
  let latest = "";
  let timerId = null;

  const flushPatch = () => {
    timerId = null;
    onPatch({ text: latest, streamStatus: "writing" });
  };

  return {
    push(text) {
      latest = text;
      if (timerId != null) return;
      timerId = window.setTimeout(flushPatch, intervalMs);
    },
    flush() {
      if (timerId != null) {
        window.clearTimeout(timerId);
        timerId = null;
      }
      return latest;
    },
    cancel() {
      if (timerId != null) {
        window.clearTimeout(timerId);
        timerId = null;
      }
    },
  };
}
