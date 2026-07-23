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

  return (
    <div className="grid w-full grid-cols-2 gap-2">
      {products.map((product, index) => {
        const { productId, name, price, currency = "NGN", image } = product || {};
        return (
          <div
            key={productId ?? index}
            className="overflow-hidden rounded-lg border border-line bg-white transition-shadow hover:shadow-md"
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
              <p className="truncate text-xs font-semibold text-ink">{name}</p>
              <p className="mt-0.5 text-xs text-ink-body">
                {formatMoneyString(price, currency)}
              </p>
              <button
                type="button"
                onClick={() =>
                  onAction?.({ type: "send", text: `Tell me about the ${name}` })
                }
                disabled={disabled}
                className="mt-2 w-full rounded-md border border-line-strong bg-white py-1 text-[11px] font-medium text-ink-body transition-colors hover:border-brand hover:text-brand disabled:cursor-not-allowed disabled:opacity-50"
              >
                Ask
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
