/** Normalize AG-UI component envelopes from the stream. */

import { getAguiComponent } from "../components/agui/registry";

export function normalizeAguiComponent(raw) {
  if (!raw || typeof raw !== "object") return null;
  const name = raw.name;
  if (!name || typeof name !== "string") return null;
  if (!getAguiComponent(name)) return null;
  return {
    id: raw.id ?? `cmp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    name,
    props: raw.props && typeof raw.props === "object" ? raw.props : {},
  };
}

export function normalizeAguiComponents(raw) {
  if (raw == null) return [];
  const list = Array.isArray(raw) ? raw : [raw];
  return list.map(normalizeAguiComponent).filter(Boolean);
}

export function filterKnownUiComponents(blocks) {
  if (!Array.isArray(blocks)) return [];
  return blocks.filter((b) => b?.name && getAguiComponent(b.name));
}

/** Apply json-patch style STATE_DELTA ops to the ui_components list. */
export function applyStateDelta(uiComponents, delta) {
  let result = [...(uiComponents || [])];

  for (const op of delta || []) {
    if (!op || typeof op !== "object") continue;

    if (op.op === "add" && op.path === "/ui_components") {
      const items = Array.isArray(op.value) ? op.value : [op.value];
      for (const item of items) {
        const norm = normalizeAguiComponent(item);
        if (norm) {
          const idx = result.findIndex((c) => c.id === norm.id);
          if (idx >= 0) result[idx] = norm;
          else result.push(norm);
        }
      }
    } else if (
      (op.op === "replace" || op.op === "set") &&
      op.path === "/ui_components"
    ) {
      result = normalizeAguiComponents(op.value);
    } else if (op.op === "remove" && op.path?.startsWith("/ui_components")) {
      const match = op.path.match(/\/ui_components\/(\d+)/);
      if (match) {
        const i = Number(match[1]);
        if (!Number.isNaN(i)) result.splice(i, 1);
      }
    }
  }

  return filterKnownUiComponents(result);
}
