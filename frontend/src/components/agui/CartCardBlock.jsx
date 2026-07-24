/** AG-UI cart_card: multi-item cart summary with a delivery-aware breakdown.
 *
 * Two shapes arrive on the same component:
 *  - PREVIEW (in conversation): only the goods are known, so deliveryFee/total/
 *    deliveryLocation/distanceKm/eta are null. We render the line items, the
 *    goods subtotal, and a soft note that delivery is added at checkout.
 *  - CHECKOUT: every field is present. We render the full breakdown: line
 *    items, goods subtotal, one delivery line, and a bold total.
 *
 * The presence of `total` is what tells the two apart.
 */

import React from "react";
import { formatMoneyString } from "../../utils/format";
import {
  handleProductImageError,
  placeholderFor,
} from "../../utils/productImages";

const PlaneIcon = () => (
  <svg
    width="12"
    height="12"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden
    className="inline-block flex-shrink-0"
  >
    <path
      d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"
      fill="currentColor"
    />
  </svg>
);

export default function CartCardBlock({ props = {} }) {
  const {
    items,
    goodsSubtotal,
    deliveryFee,
    total,
    currency = "NGN",
    deliveryLocation,
    distanceKm,
    eta,
    express,
  } = props;

  const lines = Array.isArray(items) ? items : [];
  if (!lines.length) return null;

  // Checkout once a total is known; until then it is a goods-only preview.
  const isCheckout = total != null;

  const deliveryLabel = express
    ? "Express air"
    : deliveryLocation
      ? `Delivery to ${deliveryLocation}`
      : "Delivery";

  const noteParts = [];
  if (distanceKm != null) noteParts.push(`${distanceKm} km`);
  if (eta) noteParts.push(eta);
  const deliveryNote = noteParts.length ? `(${noteParts.join(", ")})` : null;

  return (
    <div className="w-full max-w-sm overflow-hidden rounded-lg border border-line bg-white">
      <div className="border-b border-line px-4 py-2.5">
        <h4 className="text-sm font-semibold text-ink">
          {isCheckout ? "Order summary" : "Your cart"}
        </h4>
      </div>

      <ul className="divide-y divide-line">
        {lines.map((item, index) => {
          const {
            productId,
            name,
            quantity,
            lineTotal,
            unitPrice,
          } = item || {};
          const qty = quantity != null ? quantity : 1;
          return (
            <li
              key={productId ?? index}
              className="flex items-center gap-3 px-4 py-2.5"
            >
              <div className="h-10 w-10 flex-shrink-0 overflow-hidden rounded-md bg-surface-alt">
                <img
                  src={item?.image || placeholderFor(productId)}
                  alt={name || "Item"}
                  className="h-full w-full object-cover"
                  onError={(e) => handleProductImageError(e, productId)}
                />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-ink">
                  {name}
                  <span className="text-ink-muted"> x {qty}</span>
                </p>
                {unitPrice != null ? (
                  <p className="text-[11px] text-ink-muted">
                    {formatMoneyString(unitPrice, currency)} each
                  </p>
                ) : null}
              </div>
              {lineTotal != null ? (
                <span className="flex-shrink-0 text-xs text-ink-body">
                  {formatMoneyString(lineTotal, currency)}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>

      <div className="space-y-1.5 border-t border-line px-4 py-3 text-xs">
        {goodsSubtotal != null ? (
          <div className="flex justify-between">
            <span className="text-ink-muted">Goods subtotal</span>
            <span className="text-ink-body">
              {formatMoneyString(goodsSubtotal, currency)}
            </span>
          </div>
        ) : null}

        {isCheckout && deliveryFee != null ? (
          <div className="flex justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1 text-ink-muted">
              {express ? <PlaneIcon /> : null}
              <span className="truncate">{deliveryLabel}</span>
              {deliveryNote ? (
                <span className="flex-shrink-0 text-[11px] text-[#98A2B3]">
                  {deliveryNote}
                </span>
              ) : null}
            </span>
            <span className="flex-shrink-0 text-ink-body">
              {formatMoneyString(deliveryFee, currency)}
            </span>
          </div>
        ) : null}

        {isCheckout ? (
          <div className="flex justify-between border-t border-line pt-2 text-[13px] font-semibold">
            <span className="text-ink">Total</span>
            <span className="text-ink">
              {formatMoneyString(total, currency)}
            </span>
          </div>
        ) : (
          <p className="pt-0.5 text-[11px] leading-4 text-ink-muted">
            Delivery is added at checkout, once we know where it is going.
          </p>
        )}
      </div>
    </div>
  );
}
