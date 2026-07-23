/** Product image fallbacks: local SVG placeholders keyed by product id. */

const KNOWN_IDS = [
  "ankara-tote",
  "adire-shirt",
  "suya-spice",
  "beaded-bracelet",
  "jollof-spice",
  "raffia-hat",
];

export const PLACEHOLDER_IMAGES = Object.fromEntries(
  KNOWN_IDS.map((id) => [id, `/images/${id}.svg`]),
);

const GENERIC_PLACEHOLDER =
  "data:image/svg+xml," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="400" height="300" fill="#F2F4F7"/><text x="200" y="155" font-family="sans-serif" font-size="16" fill="#667085" text-anchor="middle">Oja Connect</text></svg>',
  );

export function placeholderFor(productId) {
  if (productId && PLACEHOLDER_IMAGES[productId]) {
    return PLACEHOLDER_IMAGES[productId];
  }
  if (productId) return `/images/${productId}.svg`;
  return GENERIC_PLACEHOLDER;
}

/**
 * onError handler for product <img>: first fall back to the SVG placeholder,
 * then to an inline data URI so the handler can never loop.
 */
export function handleProductImageError(event, productId) {
  const img = event.currentTarget;
  const fallback = placeholderFor(productId);
  if (img.dataset.fallbackStage === "final") return;
  if (img.dataset.fallbackStage === "svg" || img.src.endsWith(".svg")) {
    img.dataset.fallbackStage = "final";
    img.src = GENERIC_PLACEHOLDER;
    return;
  }
  img.dataset.fallbackStage = "svg";
  img.src = fallback;
}
