/** Chat empty state with suggestion chips. */

import React from "react";

export const SUGGESTIONS = [
  "What do you sell?",
  "Ship a raffia hat to Abuja",
  "Can you fly an ankara tote to London?",
];

export default function ChatEmptyState({ onSuggestion }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-brand/10 text-brand">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <h3 className="text-base font-semibold text-ink">
        Chat with the market
      </h3>
      <p className="mt-1 max-w-xs text-sm text-ink-muted">
        Ask about products, get recommendations, and pay without leaving the
        conversation.
      </p>
      <div className="mt-5 flex flex-col items-stretch gap-2">
        {SUGGESTIONS.map((label) => (
          <button
            key={label}
            type="button"
            onClick={() => onSuggestion?.(label)}
            className="rounded-full border border-line bg-white px-4 py-2 text-sm text-ink-body transition-colors hover:border-brand hover:text-brand"
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
