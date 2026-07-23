/** Chat message bubbles: user, streaming agent, final agent (markdown), UI blocks. */

import React, { memo } from "react";
import ReactMarkdown from "react-markdown";
import { filterVisibleStreamTools } from "../../lib/streamingUtils";
import AguiMessageBlocks from "../agui/AguiMessageBlocks";
import { formatTimestamp } from "../../utils/format";
import { chatMarkdownComponents } from "./markdownComponents";
import StreamToolCalls from "./StreamToolCalls";
import TypingDots from "./TypingDots";

const TypingBubble = () => (
  <div className="w-fit rounded-2xl rounded-bl-md border border-line bg-white px-5 py-4 shadow-sm">
    <TypingDots />
  </div>
);

function MessageBubble({ message, onUiAction }) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="mb-4 flex justify-end">
        <div className="min-w-0 max-w-[85%]">
          <div className="min-w-0 rounded-2xl rounded-br-md bg-[#F7F9FC] px-4 py-3 text-[14px] font-normal text-[#11121A] shadow-sm">
            <p
              className="break-words leading-relaxed"
              style={{ overflowWrap: "anywhere" }}
            >
              {message.text}
            </p>
          </div>
          <p className="mt-1 px-1 text-right text-xs text-gray-500">
            {formatTimestamp(message.timestamp)}
          </p>
        </div>
      </div>
    );
  }

  const hasText = Boolean(
    typeof message.text === "string" && message.text.trim(),
  );
  const hasUi =
    Array.isArray(message.uiComponents) && message.uiComponents.length > 0;
  const visibleTools = filterVisibleStreamTools(message.streamTools);
  const showToolList =
    message.isStreaming &&
    (visibleTools.length > 0 || message.streamStatus === "tool");
  const showTyping =
    message.isStreaming && !showToolList && !hasText && !hasUi;

  const textBubbleClass =
    "min-w-0 rounded-2xl rounded-bl-md border border-gray-200 bg-white px-5 py-4 shadow-sm";

  return (
    <div className="mb-4 flex justify-start">
      <div className="min-w-0 w-full max-w-[95%]">
        <div className="flex min-w-0 flex-col items-start gap-2">
          {showToolList ? (
            <StreamToolCalls
              tools={visibleTools}
              activeTool={message.streamTool}
            />
          ) : null}

          {showTyping ? <TypingBubble /> : null}

          {hasText ? (
            <div className={textBubbleClass}>
              {message.isStreaming ? (
                <div
                  className="whitespace-pre-wrap break-words text-[14px] leading-relaxed text-[#1D2739]"
                  style={{ overflowWrap: "anywhere" }}
                >
                  {message.text}
                </div>
              ) : (
                <div
                  className="max-w-none break-words text-[14px] text-[#1D2739]"
                  style={{ overflowWrap: "anywhere" }}
                >
                  <ReactMarkdown components={chatMarkdownComponents}>
                    {message.text}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          ) : null}

          {hasUi ? (
            <div className="min-w-0 w-full">
              <AguiMessageBlocks
                uiComponents={message.uiComponents}
                onUiAction={onUiAction}
                disabled={message.isStreaming}
              />
            </div>
          ) : null}
        </div>

        <p className="mt-1 px-1 text-left text-xs text-gray-500">
          {formatTimestamp(message.timestamp)}
        </p>
      </div>
    </div>
  );
}

export default memo(MessageBubble);
