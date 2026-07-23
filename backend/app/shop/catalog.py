"""In-code product catalog for Oja Connect, a small Lagos market shop.

Prices are exact Decimals in NGN major units (D21: money is never a float
internally). Amounts are serialized to strings at the API edge.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


class Product(TypedDict):
    id: str
    name: str
    description: str
    price: Decimal
    image: str


PRODUCTS: list[Product] = [
    {
        "id": "ankara-tote",
        "name": "Ankara Tote Bag",
        "description": "Roomy everyday tote sewn from bold ankara print fabric, "
        "fully lined with an inner zip pocket.",
        "price": Decimal("4500.00"),
        "image": "/images/ankara-tote.jpg",
    },
    {
        "id": "adire-shirt",
        "name": "Adire Shirt",
        "description": "Hand-dyed adire shirt from Abeokuta in classic indigo, "
        "relaxed fit, breathable cotton.",
        "price": Decimal("8000.00"),
        "image": "/images/adire-shirt.jpg",
    },
    {
        "id": "suya-spice",
        "name": "Suya Spice Box",
        "description": "Yaji suya spice blend, ground fresh: peanuts, ginger, "
        "chilli, and secrets. 250g tin.",
        "price": Decimal("2500.00"),
        "image": "/images/suya-spice.jpg",
    },
    {
        "id": "beaded-bracelet",
        "name": "Beaded Bracelet",
        "description": "Handmade coral and glass bead bracelet, adjustable cord, "
        "one size fits most wrists.",
        "price": Decimal("1500.00"),
        "image": "/images/beaded-bracelet.jpg",
    },
    {
        "id": "jollof-spice",
        "name": "Jollof Spice Mix",
        "description": "Party jollof starter: smoked pepper base spices measured "
        "for one full pot. No smoky flavour left behind.",
        "price": Decimal("1800.00"),
        "image": "/images/jollof-spice.jpg",
    },
    {
        "id": "raffia-hat",
        "name": "Woven Raffia Hat",
        "description": "Wide-brim raffia sun hat woven by hand, light enough for "
        "Lagos heat, sturdy enough for the market run.",
        "price": Decimal("6000.00"),
        "image": "/images/raffia-hat.jpg",
    },
]


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
