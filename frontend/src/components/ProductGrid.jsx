/** Product grid fetched from the backend, with loading and error states. */

import React, { useEffect, useState } from "react";
import { fetchProducts } from "../lib/api";
import ProductCard from "./ProductCard";

export default function ProductGrid({ onAskAbout }) {
  const [products, setProducts] = useState([]);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    fetchProducts()
      .then((list) => {
        if (cancelled) return;
        setProducts(list);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "loading") {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-64 animate-pulse rounded-lg border border-line bg-surface-alt"
          />
        ))}
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="rounded-lg border border-line bg-white p-8 text-center">
        <p className="text-sm font-medium text-ink">
          Could not load the shop catalog
        </p>
        <p className="mt-1 text-xs text-ink-muted">
          Make sure the backend is running, then refresh this page.
        </p>
      </div>
    );
  }

  if (!products.length) {
    return (
      <div className="rounded-lg border border-line bg-white p-8 text-center">
        <p className="text-sm text-ink-muted">No products in the shop yet.</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {products.map((product) => (
        <ProductCard key={product.id} product={product} onAsk={onAskAbout} />
      ))}
    </div>
  );
}
