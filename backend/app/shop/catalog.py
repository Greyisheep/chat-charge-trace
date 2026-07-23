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
