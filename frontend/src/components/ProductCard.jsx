/** Product grid card: the whole card is the button and fires the ask directly. */

import React from "react";
import { formatMoneyString } from "../utils/format";
import {
  handleProductImageError,
  placeholderFor,
} from "../utils/productImages";

export default function ProductCard({ product, onAsk, disabled = false }) {
  const { id, name, description, price, currency, image } = product;

  // Clicks always reach the chat panel's single-flight guard: while a turn
  // streams the guard ignores the send and pulses the panel as feedback.
  const activate = () => onAsk?.(product);

  const handleKeyDown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Ask about the ${name}`}
      aria-disabled={disabled}
      onClick={activate}
      onKeyDown={handleKeyDown}
      className={`group flex flex-col overflow-hidden rounded-lg border border-line bg-white transition-all hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
        disabled
          ? "cursor-not-allowed opacity-60"
          : "cursor-pointer active:scale-[0.99]"
      }`}
    >
      <div className="h-40 w-full overflow-hidden bg-surface-alt">
        <img
          src={image || placeholderFor(id)}
          alt={name}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={(e) => handleProductImageError(e, id)}
        />
      </div>
      <div className="flex flex-1 flex-col p-4">
        <h3 className="text-sm font-semibold text-ink">{name}</h3>
        <p className="mt-1 flex-1 text-xs leading-5 text-ink-muted">
          {description}
        </p>
        <div className="mt-3 flex items-center justify-between">
          <span className="text-sm font-bold text-ink">
            {formatMoneyString(price, currency)}
          </span>
          {/* Passive affordance only: the card itself is the button. */}
          <span
            aria-hidden
            className="rounded-full border border-line-strong bg-white px-3 py-1.5 text-xs font-medium text-ink-body transition-colors group-hover:border-brand group-hover:text-brand"
          >
            Ask
          </span>
        </div>
      </div>
    </div>
  );
}
