/** Open the Monnify payment modal from an AG-UI payment_event. */

import { paymentEvents } from "./paymentEvents";
import {
  isOpenPaymentModalEvent,
  normalizePaymentPayload,
} from "./paymentPayload";

export function openPaymentFromStreamEvent(paymentEvent) {
  if (!isOpenPaymentModalEvent(paymentEvent)) return false;
  paymentEvents.openPaymentModal(normalizePaymentPayload(paymentEvent));
  return true;
}
