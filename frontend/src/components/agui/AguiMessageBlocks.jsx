/** Renders AG-UI generative blocks below assistant text in chat. */

import React from "react";
import { getAguiComponent } from "./registry";
import { filterKnownUiComponents } from "../../lib/normalizeComponents";

export default function AguiMessageBlocks({
  uiComponents = [],
  onUiAction,
  disabled,
}) {
  const blocks = filterKnownUiComponents(uiComponents);
  if (!blocks.length) return null;

  return (
    <div className="mt-2 w-full min-w-0 max-w-full space-y-3">
      {blocks.map((block) => {
        const Component = getAguiComponent(block.name);
        if (!Component) return null;
        return (
          <div key={block.id ?? block.name} className="min-w-0">
            <Component
              componentId={block.id}
              props={block.props ?? {}}
              onAction={onUiAction}
              disabled={disabled}
            />
          </div>
        );
      })}
    </div>
  );
}
