"""Generative UI component builders shared by tools and the checkout graph.

Components ride in tool results under "ui_components" and are lifted into
AG-UI state by app/agent/agui.py; the frontend renders them inline in chat.
"""

from __future__ import annotations

import uuid
from typing import Any


def component(name: str, props: dict[str, Any]) -> dict[str, Any]:
    return {"id": uuid.uuid4().hex, "name": name, "props": props}


def product_card(
    product_public: dict[str, str],
    *,
    delivery_fee: str | None = None,
    total: str | None = None,
    location_label: str | None = None,
    distance_km: int | None = None,
    eta: str | None = None,
    express: bool = False,
) -> dict[str, Any]:
    """One product card. Delivery props stay None until a quote exists."""
    return component(
        "product_card",
        {
            "productId": product_public["id"],
            "name": product_public["name"],
            "description": product_public["description"],
            "image": product_public["image"],
            "price": product_public["price"],
            "currency": product_public["currency"],
            "deliveryFee": delivery_fee,
            "total": total,
            "deliveryLocation": location_label,
            "distanceKm": distance_km,
            "eta": eta,
            "express": express,
        },
    )


def product_list(
    products: list[dict[str, Any]],
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """A compact grid of mini product cards, with an optional heading.

    `title` labels the group, e.g. "Goes well with Suya Spice Box" for a
    pairing suggestion (#10). It is omitted (None) for a plain catalog listing,
    so the existing untitled list renders unchanged.
    """
    return component("product_list", {"title": title, "products": products})


def cart_card(
    line_items: list[dict[str, Any]],
    *,
    goods_subtotal: str,
    delivery_fee: str | None = None,
    total: str | None = None,
    currency: str = "NGN",
    location_label: str | None = None,
    distance_km: int | None = None,
    eta: str | None = None,
    express: bool = False,
    reference: str | None = None,
) -> dict[str, Any]:
    """An order/cart summary card: every line plus the money breakdown.

    Money values are exact strings (D21). `items` mirrors the persisted
    line_items shape, with a display-friendly image added per line. Delivery
    props are populated at checkout; for an in-conversation cart preview
    (before a destination is known) they may be None.
    """
    from ..shop import catalog

    items = []
    for line in line_items:
        product = catalog.get_product(str(line.get("product_id", "")))
        items.append(
            {
                "productId": line.get("product_id"),
                "name": line.get("product_name"),
                "unitPrice": line.get("unit_price"),
                "quantity": line.get("quantity"),
                "lineTotal": line.get("line_total"),
                "image": product["image"] if product else None,
            }
        )
    return component(
        "cart_card",
        {
            "reference": reference,
            "items": items,
            "goodsSubtotal": goods_subtotal,
            "deliveryFee": delivery_fee,
            "total": total,
            "currency": currency,
            "deliveryLocation": location_label,
            "distanceKm": distance_km,
            "eta": eta,
            "express": express,
        },
    )
