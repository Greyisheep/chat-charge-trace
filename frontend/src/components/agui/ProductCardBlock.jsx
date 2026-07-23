/** AG-UI product_card: rich single-product card with delivery-aware price breakdown. */

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

  const handleBuy = () => {
    const shipTo = deliveryLocation ? `, shipping to ${deliveryLocation}` : "";
    const expressPart = express ? ", express air" : "";
    onAction?.({
      type: "send",
      text: `I want to buy the ${name}${shipTo}${expressPart}`,
    });
  };

  return (
    <div className="w-full max-w-sm overflow-hidden rounded-lg border border-line bg-white transition-shadow hover:shadow-md">
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

        <button
          type="button"
          onClick={handleBuy}
          disabled={disabled}
          className="mt-3 w-full rounded-lg bg-brand py-2 text-xs font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:bg-line-strong"
        >
          Buy now
        </button>
      </div>
    </div>
  );
}
