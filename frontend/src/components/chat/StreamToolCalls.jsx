/** Tool-call status pills during an AG-UI stream. */

import React from "react";
import {
  filterVisibleStreamTools,
  isHiddenStreamTool,
} from "../../lib/streamingUtils";
import TypingDots from "./TypingDots";

const TOOL_LABELS = {
  transfer_to_agent: "Routing your request",
  list_products: "Browsing the shop",
  get_product: "Checking the product",
  get_product_details: "Checking the product",
  create_order: "Preparing your order",
  initiate_payment: "Preparing payment",
};

function labelForTool(name) {
  if (!name) return "Working";
  return (
    TOOL_LABELS[name] ??
    name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export default function StreamToolCalls({ tools = [], activeTool }) {
  const visible = filterVisibleStreamTools(tools);
  const list =
    visible.length > 0
      ? visible
      : activeTool && !isHiddenStreamTool(activeTool)
        ? [{ name: activeTool, status: "running" }]
        : [];

  if (!list.length) return null;

  return (
    <ul className="flex min-w-0 flex-col gap-1.5">
      {list.map((t) => (
        <li
          key={t.id ?? t.name}
          className="inline-flex w-fit max-w-full items-center gap-2 rounded-full border border-line bg-surface-alt px-3 py-1.5 text-[12px] text-[#475467]"
        >
          {t.status === "running" ? (
            <TypingDots />
          ) : (
            <span
              className="h-2 w-2 flex-shrink-0 animate-pulse rounded-full bg-success"
              aria-hidden
            />
          )}
          <span className="truncate">{labelForTool(t.name)}</span>
        </li>
      ))}
    </ul>
  );
}
