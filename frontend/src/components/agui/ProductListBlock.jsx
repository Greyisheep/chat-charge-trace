/** AG-UI product_list: compact grid of mini product cards. */

import React from "react";
import { formatMoneyString } from "../../utils/format";
import {
  handleProductImageError,
  placeholderFor,
} from "../../utils/productImages";

export default function ProductListBlock({ props = {}, onAction, disabled }) {
  const products = Array.isArray(props.products) ? props.products : [];
  if (!products.length) return null;

  // A non-null title marks this list as a PAIRING suggestion (e.g. "Goes well
  // with Suya Spice Box"). A pairing card converts on click by adding the item
  // to the cart; the plain catalog list (title null) keeps asking about it.
  const title = typeof props.title === "string" ? props.title.trim() : "";
  const isPairing = title.length > 0;

  return (
    <div className="w-full">
      {isPairing ? (
        <h5 className="mb-1.5 text-xs font-semibold text-ink-muted">{title}</h5>
      ) : null}
      <div className="grid w-full grid-cols-2 gap-2">
        {products.map((product, index) => {
          const {
            productId,
            name,
            price,
            currency = "NGN",
            image,
          } = product || {};

          // Whole card fires the send. A pairing sends an add-to-cart intent so
          // the suggestion converts; a plain catalog card asks about the item.
          // Either way the click reaches the panel's single-flight guard, which
          // ignores it (with a pulse) mid-turn.
          const intent = isPairing
            ? `Add the ${name} to my cart`
            : `Tell me about the ${name}`;
          const send = () => onAction?.({ type: "send", text: intent });

          const handleKeyDown = (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              send();
            }
          };

          return (
            <div
              key={productId ?? index}
              role="button"
              tabIndex={0}
              aria-label={
                isPairing ? `Add the ${name} to cart` : `Ask about the ${name}`
              }
              aria-disabled={disabled}
              onClick={send}
              onKeyDown={handleKeyDown}
              className={`group overflow-hidden rounded-lg border border-line bg-white transition-all hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                disabled
                  ? "cursor-not-allowed opacity-60"
                  : "cursor-pointer active:scale-[0.99]"
              }`}
            >
              <div className="h-20 w-full overflow-hidden bg-surface-alt">
                <img
                  src={image || placeholderFor(productId)}
                  alt={name || "Product"}
                  className="h-full w-full object-cover"
                  onError={(e) => handleProductImageError(e, productId)}
                />
              </div>
              <div className="p-2.5">
                <p className="truncate text-xs font-semibold text-ink">
                  {name}
                </p>
                <p className="mt-0.5 text-xs text-ink-body">
                  {formatMoneyString(price, currency)}
                </p>
                {/* Passive affordance only: the card itself is the button. */}
                <span
                  aria-hidden
                  className="mt-2 block w-full rounded-md border border-line-strong bg-white py-1 text-center text-[11px] font-medium text-ink-body transition-colors group-hover:border-brand group-hover:text-brand"
                >
                  {isPairing ? "Add" : "Ask"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
