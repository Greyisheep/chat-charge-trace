/** Parse STATE_DELTA json-patch ops (ui_components + payment_event). */

import { applyStateDelta, normalizeAguiComponents } from "./normalizeComponents";

function normalizePaymentEvent(value) {
  if (!value || typeof value !== "object") return null;
  if (value.type === "open_payment_modal") return value;
  if (value.payment_data || value.reference) {
    return { type: "open_payment_modal", ...value };
  }
  return null;
}

function pathMatchesPaymentEvent(path) {
  return path === "/payment_event" || path === "payment_event";
}

/**
 * @param {Array} delta - json-patch style ops from a STATE_DELTA event
 * @param {Array} uiComponents - current component list for the turn
 * @returns {{ uiComponents: object[], paymentEvent: object|null }}
 */
export function parseStateDeltaOps(delta, uiComponents = []) {
  let paymentEvent = null;
  let components = [...(uiComponents || [])];

  for (const op of delta || []) {
    if (!op || typeof op !== "object") continue;
    if (!pathMatchesPaymentEvent(op.path)) continue;
    if (op.op === "add" || op.op === "replace" || op.op === "set") {
      const normalized = normalizePaymentEvent(op.value);
      if (normalized) paymentEvent = normalized;
    }
  }

  components = applyStateDelta(components, delta);
  return { uiComponents: components, paymentEvent };
}

export function paymentEventFromSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return null;
  return normalizePaymentEvent(snapshot.payment_event ?? snapshot.paymentEvent);
}

export function uiComponentsFromSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return null;
  if (!Array.isArray(snapshot.ui_components)) return null;
  return normalizeAguiComponents(snapshot.ui_components);
}
