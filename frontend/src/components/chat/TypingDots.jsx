/** Shared wave typing dots. */

import React from "react";

const DOT_DELAYS = ["0ms", "150ms", "320ms"];

export default function TypingDots({
  dotClassName = "bg-gray-400",
  sizeClass = "h-2 w-2",
}) {
  return (
    <div className="flex gap-1" aria-hidden>
      {DOT_DELAYS.map((delay, i) => (
        <span
          key={i}
          className={`rounded-full animate-bounce ${sizeClass} ${dotClassName}`}
          style={{ animationDelay: delay }}
        />
      ))}
    </div>
  );
}
