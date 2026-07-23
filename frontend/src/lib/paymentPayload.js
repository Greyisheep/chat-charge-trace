/** Normalize an AG-UI payment_event into the PaymentModal payload. */

export function isOpenPaymentModalEvent(event) {
  return event?.type === "open_payment_modal";
}

export function normalizePaymentPayload(eventData) {
  const paymentData = eventData?.payment_data || {};

  return {
    reference:
      paymentData.reference || eventData?.reference || `ref_${Date.now()}`,
    amount: paymentData.amount ?? eventData?.amount,
    currency: paymentData.currency || eventData?.currency || "NGN",
    customerFullName:
      paymentData.customerFullName ||
      paymentData.customer_full_name ||
      "Oja Connect Shopper",
    customerEmail:
      paymentData.customerEmail ||
      paymentData.customer_email ||
      "shopper@ojaconnect.demo",
    description:
      paymentData.description ||
      paymentData.paymentDescription ||
      "Oja Connect order",
    rawEvent: eventData,
    rawPaymentData: paymentData,
  };
}
