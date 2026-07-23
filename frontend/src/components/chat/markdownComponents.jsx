/** Shared react-markdown component styling for agent messages. */

import React from "react";

export const chatMarkdownComponents = {
  p: (props) => <p className="mb-3 leading-6 text-[#1D2739] last:mb-0" {...props} />,
  strong: (props) => <strong className="font-semibold text-ink" {...props} />,
  em: (props) => <em className="italic text-[#475467]" {...props} />,
  h1: (props) => (
    <h1 className="mb-3 mt-5 text-[17px] font-semibold text-ink first:mt-0" {...props} />
  ),
  h2: (props) => (
    <h2 className="mb-2.5 mt-5 text-[16px] font-semibold text-ink first:mt-0" {...props} />
  ),
  h3: (props) => (
    <h3 className="mb-2 mt-4 text-[15px] font-semibold text-ink first:mt-0" {...props} />
  ),
  ul: (props) => (
    <ul className="mb-3 list-disc space-y-1.5 pl-5 marker:text-[#98A2B3]" {...props} />
  ),
  ol: (props) => (
    <ol className="mb-3 list-decimal space-y-1.5 pl-5 marker:text-[#98A2B3]" {...props} />
  ),
  li: (props) => <li className="leading-6 text-[#1D2739] [&>p]:mb-0" {...props} />,
  a: (props) => (
    <a
      className="break-words text-brand underline underline-offset-2 hover:text-brand-hover"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  blockquote: (props) => (
    <blockquote
      className="my-3 border-l-4 border-line py-1 pl-4 italic text-[#475467]"
      {...props}
    />
  ),
  code: (props) => (
    <code
      className="rounded bg-surface-alt px-1.5 py-0.5 font-mono text-[0.9em] text-ink"
      {...props}
    />
  ),
};
