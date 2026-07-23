/** Product grid card with an "Ask about this" chat shortcut. */

import React from "react";
import { formatMoneyString } from "../utils/format";
import {
  handleProductImageError,
  placeholderFor,
} from "../utils/productImages";

export default function ProductCard({ product, onAsk }) {
  const { id, name, description, price, currency, image } = product;

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-line bg-white transition-shadow hover:shadow-md">
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
          <button
            type="button"
            onClick={() => onAsk?.(product)}
            className="rounded-full border border-line-strong bg-white px-3 py-1.5 text-xs font-medium text-ink-body transition-colors hover:border-brand hover:text-brand"
          >
            Ask about this
          </button>
        </div>
      </div>
    </div>
  );
}
