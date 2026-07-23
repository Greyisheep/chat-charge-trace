/** Top header: shop identity plus sandbox badge. */

import React from "react";

export default function Header() {
  return (
    <header className="flex items-center justify-between border-b border-line bg-white px-5 py-3 sm:px-8">
      <div>
        <h1 className="text-lg font-bold tracking-tight text-ink">
          Oja Connect
        </h1>
        <p className="text-xs text-ink-muted">A Lagos market, one chat away</p>
      </div>
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-[11px] font-medium text-ink-muted">
        <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
        Powered by Monnify sandbox
      </span>
    </header>
  );
}
