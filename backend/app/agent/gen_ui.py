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
