/** Parse TOOL_CALL_RESULT JSON for payment events, ui components, and display copy. */

import { normalizeAguiComponents } from "./normalizeComponents";

function normalizePaymentEvent(value) {
  if (!value || typeof value !== "object") return null;
  if (value.type === "open_payment_modal") return value;
  if (value.payment_data || value.reference) {
    return { type: "open_payment_modal", ...value };
  }
  return null;
}

export function parseToolCallResultContent(content) {
  if (content == null) return null;

  let data = content;
  if (typeof content === "string") {
    try {
      data = JSON.parse(content);
    } catch {
      return null;
    }
  }

  if (!data || typeof data !== "object") return null;

  const paymentEvent = normalizePaymentEvent(data.payment_event);
  const uiComponents = Array.isArray(data.ui_components)
    ? normalizeAguiComponents(data.ui_components)
    : [];
  const displayMessage =
    typeof data.message === "string" && data.message.trim()
      ? data.message.trim()
      : null;

  return {
    paymentEvent,
    uiComponents,
    displayMessage,
    requiresPayment: Boolean(data.requires_payment),
  };
}
