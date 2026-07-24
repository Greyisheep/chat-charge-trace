/** Maps backend ui_components `name` to a React component. */

import CartCardBlock from "./CartCardBlock";
import ProductCardBlock from "./ProductCardBlock";
import ProductListBlock from "./ProductListBlock";

export const AGUI_COMPONENT_REGISTRY = {
  product_card: ProductCardBlock,
  product_list: ProductListBlock,
  cart_card: CartCardBlock,
};

export function getAguiComponent(name) {
  if (!name || typeof name !== "string") return null;
  const Component = AGUI_COMPONENT_REGISTRY[name];
  return typeof Component === "function" ? Component : null;
}
