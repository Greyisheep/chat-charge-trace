/** Global payment modal state (tiny observable store, no dependencies). */

class PaymentStore {
  constructor() {
    this.isOpen = false;
    this.paymentData = null;
    this.listeners = [];
  }

  subscribe(callback) {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((cb) => cb !== callback);
    };
  }

  openModal(data) {
    const nextReference = data?.reference;
    const currentReference = this.paymentData?.reference;

    // Ignore duplicate open events for the same payment reference.
    if (
      this.isOpen &&
      nextReference &&
      currentReference &&
      nextReference === currentReference
    ) {
      return;
    }

    this.isOpen = true;
    this.paymentData = data;
    this.notifyListeners();
  }

  closeModal() {
    this.isOpen = false;
    this.paymentData = null;
    this.notifyListeners();
  }

  notifyListeners() {
    this.listeners.forEach((callback) => {
      callback({ isOpen: this.isOpen, paymentData: this.paymentData });
    });
  }

  getState() {
    return { isOpen: this.isOpen, paymentData: this.paymentData };
  }
}

export const paymentStore = new PaymentStore();
