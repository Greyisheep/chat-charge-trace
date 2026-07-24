"""Plain REST endpoints for the shop: products and order status.

The frontend uses these outside the chat stream: the product grid, and
polling an order after the Monnify popup closes. Amounts are serialized as
strings (money is Decimal internally, D21).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.monnify.client import MonnifyError
from app.shop.catalog import PRODUCTS
from app.shop.orders import Order, order_store

router = APIRouter()


def _public_order(order: Order) -> dict[str, Any]:
    return {
        "reference": order.reference,
        "status": order.status,
        "amount": str(order.amount),
        "currency": order.currency,
        "product_name": order.product_name,
        "line_items": order.line_items or [],
        "customer_email": order.customer_email,
        "destination_city": order.destination_city,
        "destination_country": order.destination_country,
        "express": order.express,
        "eta": order.eta,
        "delivery_fee": str(order.delivery_fee),
    }


@router.get("/api/products")
def list_products() -> dict[str, Any]:
    return {
        "products": [
            {
                "id": p["id"],
                "name": p["name"],
                "description": p["description"],
                "price": str(p["price"]),
                "currency": "NGN",
                "image": p["image"],
            }
            for p in PRODUCTS
        ]
    }


@router.get("/api/orders/{reference}")
async def get_order(reference: str) -> dict[str, Any]:
    order = await order_store.get(reference)
    if order is None:
        raise HTTPException(status_code=404, detail=f"unknown order: {reference}")
    return _public_order(order)


@router.post("/api/orders/{reference}/verify")
async def verify_order(reference: str) -> dict[str, Any]:
    """The trust boundary endpoint: only Monnify's answer moves an order."""
    if await order_store.get(reference) is None:
        raise HTTPException(status_code=404, detail=f"unknown order: {reference}")
    try:
        order = await order_store.verify(reference)
    except MonnifyError as exc:
        raise HTTPException(status_code=502, detail=f"Monnify sandbox error: {exc}") from None
    assert order is not None
    return _public_order(order)
