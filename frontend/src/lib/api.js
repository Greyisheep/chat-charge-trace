/** REST calls for products and order verification. */

import { API_BASE_URL } from "../config";

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const errText = await response.text().catch(() => "");
    throw new Error(errText || `Request failed (${response.status})`);
  }
  return response.json();
}

/** GET /api/products -> {products: [{id, name, description, price, currency, image}]} */
export async function fetchProducts() {
  const data = await requestJson("/api/products");
  return Array.isArray(data?.products) ? data.products : [];
}

/** GET /api/orders/{reference} -> {reference, status, amount, currency, product_name, customer_email} */
export async function fetchOrder(reference) {
  return requestJson(`/api/orders/${encodeURIComponent(reference)}`);
}

/** POST /api/orders/{reference}/verify -> same order shape */
export async function verifyOrder(reference) {
  return requestJson(`/api/orders/${encodeURIComponent(reference)}/verify`, {
    method: "POST",
  });
}
