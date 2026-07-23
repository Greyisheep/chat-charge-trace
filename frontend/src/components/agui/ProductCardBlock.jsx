/** AG-UI product_card: rich single-product card with delivery-aware price breakdown. */

import React, { useEffect, useState } from "react";
import { purchasesStore } from "../../lib/purchasesStore";
import { formatMoneyString } from "../../utils/format";
import {
  handleProductImageError,
  placeholderFor,
} from "../../utils/productImages";

const CheckIcon = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden
    className="inline-block flex-shrink-0"
  >
    <path
      d="M20 6L9 17l-5-5"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

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

export default function ProductCardBlock({ props = {}, onAction, disabled }) {
  const {
    productId,
    name,
    description,
    image,
    price,
    currency = "NGN",
    deliveryFee,
    total,
    deliveryLocation,
    distanceKm,
    eta,
    express,
  } = props;

  const deliveryLabel = express
    ? "Express air delivery"
    : deliveryLocation
      ? `Delivery to ${deliveryLocation}`
      : "Delivery";

  const noteParts = [];
  if (distanceKm != null) noteParts.push(`${distanceKm} km`);
  if (eta) noteParts.push(eta);
  const deliveryNote = noteParts.length ? `(${noteParts.join(", ")})` : null;

  // Card click asks about the product. The Buy now button keeps its own,
  // more specific action; stopPropagation ensures one click never fires both.
  // Sends always reach the panel's single-flight guard, which ignores them
  // (with a pulse) while a turn is streaming.
  const handleAsk = () => {
    onAction?.({ type: "send", text: `Tell me about the ${name}` });
  };

  const handleCardKeyDown = (event) => {
    // Only react to keys pressed on the card itself, not on the Buy button.
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleAsk();
    }
  };

  // Bought state, matched by product name via the purchases store. Once a
  // payment for this name verifies, the Buy now button flips to Bought and a
  // secondary Buy again action appears.
  const [bought, setBought] = useState(() => purchasesStore.has(name));
  useEffect(() => {
    const update = () => setBought(purchasesStore.has(name));
    update();
    return purchasesStore.subscribe(update);
  }, [name]);

  const handleBuy = (event) => {
    event.stopPropagation();
    const shipTo = deliveryLocation ? `, shipping to ${deliveryLocation}` : "";
    const expressPart = express ? ", express air" : "";
    onAction?.({
      type: "send",
      text: `I want to buy the ${name}${shipTo}${expressPart}`,
    });
  };

  // Buy again starts a fresh conversation-driven checkout: never reuse the old
  // reference. Clearing the name lets a new order flow and re-arms Buy now.
  const handleBuyAgain = (event) => {
    event.stopPropagation();
    purchasesStore.remove(name);
    onAction?.({
      type: "send",
      text: `I would like to buy another ${name}`,
    });
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Ask about the ${name}`}
      aria-disabled={disabled}
      onClick={handleAsk}
      onKeyDown={handleCardKeyDown}
      className={`w-full max-w-sm overflow-hidden rounded-lg border border-line bg-white transition-all hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"
      }`}
    >
      <div className="h-36 w-full overflow-hidden bg-surface-alt">
        <img
          src={image || placeholderFor(productId)}
          alt={name || "Product"}
          className="h-full w-full object-cover"
          onError={(e) => handleProductImageError(e, productId)}
        />
      </div>
      <div className="p-4">
        <h4 className="text-sm font-semibold text-ink">{name}</h4>
        {description ? (
          <p className="mt-1 text-xs leading-5 text-ink-muted">{description}</p>
        ) : null}

        <div className="mt-3 space-y-1.5 border-t border-line pt-3 text-xs">
          {price != null ? (
            <div className="flex justify-between">
              <span className="text-ink-muted">Price</span>
              <span className="text-ink-body">
                {formatMoneyString(price, currency)}
              </span>
            </div>
          ) : null}
          {deliveryFee != null ? (
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
          {total != null ? (
            <div className="flex justify-between pt-1 text-[13px] font-semibold">
              <span className="text-ink">Total</span>
              <span className="text-ink">
                {formatMoneyString(total, currency)}
              </span>
            </div>
          ) : null}
        </div>

        {bought ? (
          <>
            {/* Terminal bought state: disabled so it is not clickable. */}
            <button
              type="button"
              disabled
              aria-label={`${name} already bought`}
              className="mt-3 flex w-full cursor-not-allowed items-center justify-center gap-1.5 rounded-lg border border-success/30 bg-success/10 py-2 text-xs font-medium text-success"
            >
              <CheckIcon />
              Bought
            </button>
            {/* aria-disabled (not disabled) so an ignored click still reaches
                the single-flight guard and triggers the panel pulse. */}
            <button
              type="button"
              onClick={handleBuyAgain}
              aria-disabled={disabled}
              aria-label={`Buy the ${name} again`}
              className={`mt-2 w-full rounded-lg border py-2 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                disabled
                  ? "cursor-not-allowed border-line bg-surface-alt text-ink-muted"
                  : "border-brand bg-white text-brand hover:bg-surface-alt active:scale-[0.99]"
              }`}
            >
              Buy again
            </button>
          </>
        ) : (
          /* aria-disabled (not disabled) so an ignored click still reaches the
             single-flight guard and triggers the panel pulse feedback. */
          <button
            type="button"
            onClick={handleBuy}
            aria-disabled={disabled}
            aria-label={`Buy the ${name} now`}
            className={`mt-3 w-full rounded-lg py-2 text-xs font-medium text-white transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
              disabled
                ? "cursor-not-allowed bg-line-strong"
                : "bg-brand hover:bg-brand-hover active:scale-[0.99]"
            }`}
          >
            Buy now
          </button>
        )}
      </div>
    </div>
  );
}
