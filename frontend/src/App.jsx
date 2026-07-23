/** Oja Connect: product grid + AG-UI chat panel + global Monnify payment modal. */

import React, { useCallback, useRef, useState } from "react";
import Header from "./components/Header";
import PaymentModal from "./components/PaymentModal";
import ProductGrid from "./components/ProductGrid";
import ChatPanel from "./components/chat/ChatPanel";

function ChatIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M18 6L6 18M6 6l12 12"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function App() {
  const chatRef = useRef(null);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);

  const handleAskAbout = useCallback((product) => {
    setMobileChatOpen(true);
    chatRef.current?.insertPrompt(`Tell me about the ${product.name}`);
  }, []);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Header />

      <div className="flex min-h-0 flex-1">
        {/* Product grid */}
        <main className="min-w-0 flex-1 overflow-y-auto px-5 py-6 sm:px-8">
          <div className="mx-auto max-w-4xl">
            <h2 className="text-base font-semibold text-ink">
              Fresh from the stalls
            </h2>
            <p className="mb-5 mt-0.5 text-sm text-ink-muted">
              Tap a product or just ask the assistant. It handles the rest,
              payment included.
            </p>
            <ProductGrid onAskAbout={handleAskAbout} />
          </div>
        </main>

        {/* Single chat panel: right column on desktop, full-screen sheet on mobile */}
        <aside
          className={`fixed inset-0 z-40 bg-white transition-transform duration-300 lg:static lg:z-auto lg:block lg:w-[420px] lg:flex-shrink-0 lg:transform-none lg:border-l lg:border-line lg:transition-none ${
            mobileChatOpen ? "translate-y-0" : "translate-y-full"
          }`}
        >
          <div className="relative h-full">
            <ChatPanel ref={chatRef} />
            <button
              type="button"
              onClick={() => setMobileChatOpen(false)}
              className="absolute right-3 top-2.5 rounded-full p-2 text-ink-muted hover:bg-surface-alt lg:hidden"
              aria-label="Close chat"
            >
              <CloseIcon />
            </button>
          </div>
        </aside>
      </div>

      {/* Mobile chat toggle */}
      {!mobileChatOpen && (
        <button
          type="button"
          onClick={() => setMobileChatOpen(true)}
          className="fixed bottom-5 right-5 z-30 flex h-14 w-14 items-center justify-center rounded-full bg-brand text-white shadow-lg transition-colors hover:bg-brand-hover lg:hidden"
          aria-label="Open chat"
        >
          <ChatIcon />
        </button>
      )}

      <PaymentModal />
    </div>
  );
}
