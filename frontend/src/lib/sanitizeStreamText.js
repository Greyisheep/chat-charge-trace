/** Strip payment_event markup that leaks into TEXT_MESSAGE_CONTENT. */

const PAYMENT_TAG_BLOCK = /<payment_event[\s\S]*?<\/payment_event>/gi;
const PAYMENT_SELF_CLOSE = /<payment_event[^>]*\/?>/gi;
const PAYMENT_CLOSE_FRAG = /<\/payment_event>/gi;
const PAYMENT_CLOSE_PARTIAL = /\s*\/?>\s*<\/paym\w*/gi;

/** Backend may stream XML-ish attrs instead of STATE_DELTA. */
const PAYMENT_ATTR_LEAK =
  /\s*(?:reference|amount|currency|customerFullName|customerEmail|description|payment_reference)="[^"]*"/gi;

/** Lines that are only leaked key="value" fragments. */
const ATTR_ONLY_LINE = /^\s*[a-zA-Z_]+="[^"]*"\s*$/gm;

export function sanitizeStreamText(text) {
  if (!text || typeof text !== "string") return text ?? "";

  const out = text
    .replace(PAYMENT_TAG_BLOCK, "")
    .replace(PAYMENT_SELF_CLOSE, "")
    .replace(PAYMENT_CLOSE_FRAG, "")
    .replace(PAYMENT_CLOSE_PARTIAL, "")
    .replace(PAYMENT_ATTR_LEAK, "")
    .replace(ATTR_ONLY_LINE, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return out;
}

/** True when a delta looks like backend payment metadata, not user-facing prose. */
export function isPaymentMetadataDelta(delta) {
  if (!delta || typeof delta !== "string") return false;
  return /<\/?payment_event/i.test(delta);
}
