/** Simple global event surface for the payment modal. */

import { paymentStore } from "./paymentStore";

class PaymentEventManager {
  openPaymentModal(paymentData) {
    paymentStore.openModal(paymentData);
  }

  closePaymentModal() {
    paymentStore.closeModal();
  }
}

export const paymentEvents = new PaymentEventManager();
