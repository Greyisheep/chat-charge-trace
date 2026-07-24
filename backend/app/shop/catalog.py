"""In-code product catalog for Oja Connect, a small Lagos market shop.

Prices are exact Decimals in NGN major units (D21: money is never a float
internally). Amounts are serialized to strings at the API edge.

Pairing data (#10) lives here, in code, and is deterministic: every product
carries `tags` and an optional explicit `pairs_with` list. The agent only ever
words the suggestion; it can never invent inventory, because pairings_for()
only ever returns products that exist in PRODUCTS.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


class _ProductRequired(TypedDict):
    id: str
    name: str
    description: str
    price: Decimal
    image: str


class Product(_ProductRequired, total=False):
    """A catalog product. `tags` and `pairs_with` are optional pairing data.

    tags: free-form descriptors used by the tag pairing rule, e.g.
        ["spicy"], ["drink", "cooling"], ["wearable"], ["savoury"].
    pairs_with: explicit catalog ids that pair well with this product; they are
        offered before any tag-derived suggestion.
    """

    tags: list[str]
    pairs_with: list[str]


PRODUCTS: list[Product] = [
    {
        "id": "ankara-tote",
        "name": "Ankara Tote Bag",
        "description": "Roomy everyday tote sewn from bold ankara print fabric, "
        "fully lined with an inner zip pocket.",
        "price": Decimal("4500.00"),
        "image": "/images/ankara-tote.jpg",
        "tags": ["wearable", "accessory", "everyday"],
        "pairs_with": ["raffia-hat"],
    },
    {
        "id": "adire-shirt",
        "name": "Adire Shirt",
        "description": "Hand-dyed adire shirt from Abeokuta in classic indigo, "
        "relaxed fit, breathable cotton.",
        "price": Decimal("8000.00"),
        "image": "/images/adire-shirt.jpg",
        "tags": ["wearable", "everyday"],
        "pairs_with": ["beaded-bracelet"],
    },
    {
        "id": "suya-spice",
        "name": "Suya Spice Box",
        "description": "Yaji suya spice blend, ground fresh: peanuts, ginger, "
        "chilli, and secrets. 250g tin.",
        "price": Decimal("2500.00"),
        "image": "/images/suya-spice.jpg",
        "tags": ["spicy", "savoury", "pantry"],
        "pairs_with": ["chilled-cola", "zobo-drink"],
    },
    {
        "id": "beaded-bracelet",
        "name": "Beaded Bracelet",
        "description": "Handmade coral and glass bead bracelet, adjustable cord, "
        "one size fits most wrists.",
        "price": Decimal("1500.00"),
        "image": "/images/beaded-bracelet.jpg",
        "tags": ["wearable", "accessory"],
        "pairs_with": ["adire-shirt"],
    },
    {
        "id": "jollof-spice",
        "name": "Jollof Spice Mix",
        "description": "Party jollof starter: smoked pepper base spices measured "
        "for one full pot. No smoky flavour left behind.",
        "price": Decimal("1800.00"),
        "image": "/images/jollof-spice.jpg",
        "tags": ["spicy", "savoury", "pantry"],
        "pairs_with": ["chapman-mix", "zobo-drink"],
    },
    {
        "id": "raffia-hat",
        "name": "Woven Raffia Hat",
        "description": "Wide-brim raffia sun hat woven by hand, light enough for "
        "Lagos heat, sturdy enough for the market run.",
        "price": Decimal("6000.00"),
        "image": "/images/raffia-hat.jpg",
        "tags": ["wearable", "accessory", "sun"],
        "pairs_with": ["ankara-tote"],
    },
    {
        "id": "chilled-cola",
        "name": "Chilled Cola",
        "description": "Ice-cold bottled cola straight from the cooler, "
        "50cl, the classic answer to a peppery plate.",
        "price": Decimal("700.00"),
        "image": "/images/chilled-cola.jpg",
        "tags": ["drink", "cooling", "sweet"],
    },
    {
        "id": "zobo-drink",
        "name": "Zobo Drink",
        "description": "Chilled hibiscus zobo brewed with ginger and pineapple, "
        "75cl bottle, tart and refreshing.",
        "price": Decimal("900.00"),
        "image": "/images/zobo-drink.jpg",
        "tags": ["drink", "cooling", "tart"],
    },
    {
        "id": "chapman-mix",
        "name": "Chapman Mix",
        "description": "The party-favourite Chapman blend with cucumber and "
        "bitters, 75cl bottle, served over plenty of ice.",
        "price": Decimal("1200.00"),
        "image": "/images/chapman-mix.jpg",
        "tags": ["drink", "cooling", "sweet"],
    },
]

# --- pairing rules (deterministic, in-code) ---------------------------------

MAX_PAIRINGS = 3

# (source tag, candidate tag) pairs that make a suggestion by themselves, over
# and above any explicit pairs_with list.
TAG_PAIRING_RULES: list[tuple[str, str]] = [
    ("spicy", "cooling"),
]

# (source tag, candidate tag) -> the human reason the agent may say. First
# match wins; the agent only relays this wording, it never invents a reason.
PAIRING_REASONS: list[tuple[str, str, str]] = [
    ("spicy", "cooling", "to cool down the pepper"),
    ("sun", "cooling", "for the Lagos sun"),
    ("wearable", "accessory", "to finish the look"),
    ("wearable", "wearable", "to finish the look"),
    ("pantry", "pantry", "for the same pot"),
]

DEFAULT_PAIRING_REASON = "because they go well together"


def get_product(product_id: str) -> Product | None:
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    return None


def _norm(value: str) -> str:
    """Lowercase and strip everything but letters and digits, for loose matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def resolve_product(identifier: str) -> Product | None:
    """Resolve a product by id or name, tolerant of near-misses.

    A conversational agent (especially over voice) may pass a slightly-off id
    like "suya-spice-box" or the display name "Suya Spice Box" instead of the
    exact catalog id "suya-spice". Try an exact id first, then a normalized
    match against both id and name, then a containment match so a spoken name
    still resolves. Returns None only when nothing plausibly matches.
    """
    if not identifier:
        return None
    exact = get_product(identifier)
    if exact is not None:
        return exact
    target = _norm(identifier)
    if not target:
        return None
    for product in PRODUCTS:
        if _norm(product["id"]) == target or _norm(product["name"]) == target:
            return product
    for product in PRODUCTS:
        pid, pname = _norm(product["id"]), _norm(product["name"])
        if target in pid or pid in target or target in pname or pname in target:
            return product
    return None


def tags_of(product: Product) -> set[str]:
    return {str(tag) for tag in (product.get("tags") or [])}


def pairings_for(product_id: str, limit: int = MAX_PAIRINGS) -> list[Product]:
    """Products that go well with `product_id`, deterministically.

    Order: the explicit `pairs_with` ids first (in the order they are listed),
    then anything matched by a TAG_PAIRING_RULES pair (e.g. anything tagged
    "spicy" pairs with anything tagged "cooling"). Deduped, never includes the
    product itself, capped at `limit`. Everything returned is a real catalog
    product, so the agent cannot suggest inventory that does not exist.
    """
    product = resolve_product(product_id)
    if product is None:
        return []
    seen = {product["id"]}
    picked: list[Product] = []

    def _take(candidate: Product | None) -> None:
        if candidate is None or candidate["id"] in seen or len(picked) >= limit:
            return
        seen.add(candidate["id"])
        picked.append(candidate)

    for pid in product.get("pairs_with") or []:
        _take(get_product(str(pid)))

    source_tags = tags_of(product)
    for source_tag, candidate_tag in TAG_PAIRING_RULES:
        if source_tag not in source_tags:
            continue
        for candidate in PRODUCTS:
            if candidate_tag in tags_of(candidate):
                _take(candidate)

    return picked[:limit]


def pairing_reason(product: Product, paired: list[Product]) -> str:
    """The short, deterministic reason wording for a pairing suggestion."""
    source_tags = tags_of(product)
    paired_tags: set[str] = set()
    for candidate in paired:
        paired_tags |= tags_of(candidate)
    for source_tag, candidate_tag, reason in PAIRING_REASONS:
        if source_tag in source_tags and candidate_tag in paired_tags:
            return reason
    return DEFAULT_PAIRING_REASON
