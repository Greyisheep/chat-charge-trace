/**
 * Deterministic, local ghost-text suggestions for the chat composer.
 *
 * No network and no LLM calls: given the current input and a little
 * conversation context, return the single best completion string, or null
 * when nothing fits. The returned string always begins with the exact text
 * the user typed, so the composer can render the tail as ghost text and the
 * whole string as the value on accept.
 */

// Common openers we want to help people type quickly on stage. Order matters:
// the first that strictly extends the input wins within this source.
const INTENT_PHRASES = [
  "What do you sell?",
  "Ship a raffia hat to Abuja",
  "Can you fly an ankara tote to London?",
  "I want to buy the ",
  "What is the price of the ",
  "Do you deliver to ",
  "Check my order status",
];

// Context-aware next steps, keyed on a coarse conversation hint derived by the
// caller. After a delivery quote, bias toward buying; after a verified order,
// bias toward checking status.
const CONTEXT_PHRASES = {
  quote: ["Yes, buy it for me", "Buy it now", "I would like to buy it"],
  verified: ["Check my order status", "Where is my order?"],
};

// A candidate only helps if it adds visible (non-space) characters.
function hasVisibleRemainder(candidate, input) {
  return (
    candidate.length > input.length &&
    candidate.slice(input.length).trim().length > 0
  );
}

// Preserve the user's typed casing, append only the candidate's tail.
function extend(input, candidate) {
  return input + candidate.slice(input.length);
}

// Whole-input prefix match against a fixed phrase list.
function prefixComplete(input, phrases) {
  const lowered = input.toLowerCase();
  for (const phrase of phrases) {
    if (
      phrase.toLowerCase().startsWith(lowered) &&
      hasVisibleRemainder(phrase, input)
    ) {
      return extend(input, phrase);
    }
  }
  return null;
}

// Complete a product name when the tail of the input is a prefix of that name
// at a word boundary. The longest tail match across the catalog wins.
function productComplete(input, products) {
  if (!Array.isArray(products) || products.length === 0) return null;
  const lowered = input.toLowerCase();
  let best = null;
  let bestK = 0;

  for (const raw of products) {
    const name = typeof raw === "string" ? raw : raw?.name;
    if (!name) continue;
    const loweredName = name.toLowerCase();
    const maxK = Math.min(input.length, name.length);

    // Try the longest tail first; require at least 2 chars so a stray letter
    // does not trigger a whole product name.
    for (let k = maxK; k >= 2; k -= 1) {
      const boundaryOk =
        input.length === k || input[input.length - k - 1] === " ";
      if (!boundaryOk) continue;
      const tail = lowered.slice(lowered.length - k);
      if (loweredName.startsWith(tail) && k < name.length) {
        if (k > bestK) {
          bestK = k;
          best = input + name.slice(k);
        }
        break; // longest boundary match for this product found
      }
    }
  }

  return best && hasVisibleRemainder(best, input) ? best : null;
}

/**
 * Best single completion for the current input, or null.
 *
 * @param {string} input   The exact text in the composer.
 * @param {object} context { products: (string|{name})[], hint: "quote"|"verified"|null }
 * @returns {string|null}  A string that starts with input and is strictly longer.
 */
export function suggestFor(input, context = {}) {
  if (typeof input !== "string") return null;
  if (!input.trim()) return null;

  const { products = [], hint = null } = context;

  // 1. Product-name completion from the live catalog.
  const fromProduct = productComplete(input, products);
  if (fromProduct) return fromProduct;

  // 2. Static intent phrases for common openers.
  const fromIntent = prefixComplete(input, INTENT_PHRASES);
  if (fromIntent) return fromIntent;

  // 3. Context-aware next step, only when a clean hint is threaded in.
  if (hint && CONTEXT_PHRASES[hint]) {
    const fromContext = prefixComplete(input, CONTEXT_PHRASES[hint]);
    if (fromContext) return fromContext;
  }

  return null;
}
