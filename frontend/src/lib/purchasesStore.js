/** Purchased-product state (tiny observable store, no dependencies).
 *
 * Tracks which product NAMES have a verified order, plus the latest order
 * reference per name. Cards match by name so no backend change is needed.
 * References stay single-use: "Buy again" removes the name so a fresh
 * conversation-driven checkout can start with a brand new reference.
 */

class PurchasesStore {
  constructor() {
    this.purchases = new Map(); // name -> latest verified reference
    this.listeners = [];
  }

  subscribe(callback) {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((cb) => cb !== callback);
    };
  }

  add(name, reference) {
    if (!name) return;
    this.purchases.set(name, reference ?? null);
    this.notifyListeners();
  }

  remove(name) {
    if (this.purchases.delete(name)) {
      this.notifyListeners();
    }
  }

  has(name) {
    return this.purchases.has(name);
  }

  getReference(name) {
    return this.purchases.get(name) ?? null;
  }

  notifyListeners() {
    const state = this.getState();
    this.listeners.forEach((callback) => {
      callback(state);
    });
  }

  getState() {
    return { purchases: new Map(this.purchases) };
  }
}

export const purchasesStore = new PurchasesStore();
