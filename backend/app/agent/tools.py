"""Shop tools exposed to the ADK agent as FunctionTools.

Plain functions with JSON-serializable results (ADK derives the declarations
from the signatures). Two structured keys in tool results are lifted into
AG-UI state by the transform layer (app/agent/agui.py):

  * payment_event: the frontend opens the Monnify checkout popup from it.
  * ui_components: generative UI (product cards) the chat renders inline.

The money path is the checkout tool: it runs the explicit workflow graph in
app/agent/checkout_graph.py via tool_context.run_node (the same invocation
NodeTool uses under the hood), so every charged number is derived inside the
graph and nothing the model says can move money. quote_delivery stays as the
lighter browsing-stage path.

Tools also record a few session facts (customer name, last destination, last
order) into ctx.state; the dynamic instruction injects them each turn while
the static instruction stays byte-stable for context caching.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from google.adk.tools.tool_context import ToolContext

from ..money import money
from ..monnify.client import MonnifyError
from ..shop import catalog, delivery
from ..shop.orders import order_store
from ..telemetry import traced
from . import gen_ui
from .checkout_graph import CheckoutError, checkout_workflow

log = logging.getLogger("tools")

GEOCODE_MISS_ERROR = (
    "I could not find that place on the map. Could you give me the nearest big "
    "city (and the country) instead?"
)


def _public_product(product: catalog.Product) -> dict[str, str]:
    return {
        "id": product["id"],
        "name": product["name"],
        "description": product["description"],
        "price": str(product["price"]),
        "currency": "NGN",
        "image": product["image"],
    }


def _remember(tool_context: ToolContext | None, **facts: Any) -> None:
    """Record session facts for the dynamic instruction. Never fails a tool."""
    if tool_context is None:
        return
    try:
        for key, value in facts.items():
            if value is not None:
                tool_context.state[key] = value
    except Exception as exc:
        log.warning("tools.remember.failed error=%s", exc)


def list_products() -> dict[str, Any]:
    """List every product in the shop with id, name, description, and price in NGN."""
    with traced("tools.list_products"):
        return {
            "success": True,
            "products": [_public_product(p) for p in catalog.PRODUCTS],
            "ui_components": [
                gen_ui.component(
                    "product_list",
                    {
                        "products": [
                            {
                                "productId": p["id"],
                                "name": p["name"],
                                "price": str(p["price"]),
                                "currency": "NGN",
                                "image": p["image"],
                            }
                            for p in catalog.PRODUCTS
                        ]
                    },
                )
            ],
        }


def get_product(product_id: str) -> dict[str, Any]:
    """Get one product's details by its product id.

    Renders a product card in the chat. Delivery pricing on the card stays
    empty until quote_delivery is called with a destination.

    Args:
        product_id: The catalog id of the product, e.g. "ankara-tote".
    """
    with traced("tools.get_product", product_id=product_id):
        product = catalog.get_product(product_id)
        if product is None:
            return {"success": False, "error": f"No product with id '{product_id}'."}
        return {
            "success": True,
            "product": _public_product(product),
            "ui_components": [gen_ui.product_card(_public_product(product))],
        }


def _parse_fare(found_flight_price: str) -> Decimal | None:
    try:
        fare = money(found_flight_price.strip().replace(",", ""))
        return fare if fare > 0 else None
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


async def quote_delivery(
    product_id: str,
    destination_city: str,
    destination_country: str,
    express: bool = False,
    found_flight_price: str = "",
    found_flight_currency: str = "NGN",
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Quote delivery of a product to a destination city, with fee, total, and ETA.

    Standard delivery is priced by road distance from Lagos. Express "fly it"
    delivery is priced from a real flight fare: FIRST ask the FlightPriceAgent
    tool for the current one-way economy fare from Lagos to the destination,
    then pass its price here as found_flight_price and found_flight_currency.
    If no fare could be found, leave found_flight_price empty and a fallback
    price is used. This is a browsing-stage quote; checkout re-prices
    everything server side.

    Args:
        product_id: The catalog id of the product, e.g. "ankara-tote".
        destination_city: The city the order ships to, e.g. "Abuja".
        destination_country: The country of that city, e.g. "Nigeria".
        express: True for the express fly-it option.
        found_flight_price: The flight fare number the FlightPriceAgent found,
            e.g. "85000". Empty string if unknown.
        found_flight_currency: Currency of that fare, "NGN" or "USD".
    """
    with traced("tools.quote_delivery", product_id=product_id, city=destination_city):
        product = catalog.get_product(product_id)
        if product is None:
            return {"success": False, "error": f"No product with id '{product_id}'."}

        fare = _parse_fare(found_flight_price) if express else None
        quote = await asyncio.to_thread(
            delivery.quote_for,
            product,
            destination_city,
            destination_country,
            express=express,
            found_flight_price=fare,
            found_flight_currency=found_flight_currency,
        )
        if quote is None:
            return {"success": False, "error": GEOCODE_MISS_ERROR}

        _remember(tool_context, last_destination=quote.location_label)
        return {
            "success": True,
            "product": _public_product(product),
            "destination": quote.location_label,
            "distance_km": quote.distance_km,
            "express": quote.express,
            "delivery_fee": str(quote.delivery_fee),
            "total": str(quote.total),
            "eta": quote.eta,
            "fee_source": quote.fee_source,
            "ui_components": [
                gen_ui.product_card(
                    _public_product(product),
                    delivery_fee=str(quote.delivery_fee),
                    total=str(quote.total),
                    location_label=quote.location_label,
                    distance_km=quote.distance_km,
                    eta=quote.eta,
                    express=quote.express,
                )
            ],
        }


async def checkout(
    product_id: str,
    customer_full_name: str,
    customer_email: str,
    destination_city: str,
    destination_country: str,
    express: bool = False,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Create an order and open payment, after the buyer has confirmed the purchase.

    Only call this once the buyer has explicitly confirmed they want to buy,
    has said where the order ships to (city and country) and whether they want
    express, and has provided their full name and email address. The price is
    recomputed server side inside the checkout workflow (including a live
    flight fare check for express), so quoted and charged totals can differ
    slightly; relay what this returns.

    Args:
        product_id: The catalog id of the product being bought.
        customer_full_name: The buyer's full name.
        customer_email: The buyer's email address.
        destination_city: The city the order ships to, e.g. "Abuja".
        destination_country: The country of that city, e.g. "Nigeria".
        express: True when the buyer chose the express fly-it option.
    """
    with traced("tools.checkout", product_id=product_id):
        node_input = {
            "product_id": product_id,
            "customer_full_name": customer_full_name,
            "customer_email": customer_email,
            "destination_city": destination_city,
            "destination_country": destination_country,
            "express": express,
        }
        # Same invocation NodeTool uses: the workflow becomes a child node of
        # this tool call, branch-scoped by the function call id.
        fc_id = getattr(tool_context, "function_call_id", None) or "checkout"
        base_branch = getattr(tool_context, "branch", None)
        segment = f"checkout@{fc_id}"
        tool_branch = f"{base_branch}.{segment}" if base_branch else segment
        try:
            result = await tool_context.run_node(
                checkout_workflow,
                node_input=node_input,
                override_branch=tool_branch,
                use_sub_branch=False,
            )
        except CheckoutError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            log.warning("tools.checkout.failed error=%s", exc)
            message = str(exc)
            if "CheckoutError" in type(exc).__name__ or "could not find" in message.lower():
                return {"success": False, "error": message}
            return {
                "success": False,
                "error": "Checkout hit a snag on our side. Nothing was charged; "
                "please try again in a moment.",
            }
        if not isinstance(result, dict):
            return {"success": False, "error": "Checkout returned no result. Please try again."}

        order = result.get("order") or {}
        _remember(
            tool_context,
            customer_name=customer_full_name.strip(),
            last_destination=(
                f"{order.get('destination_city')}, {order.get('destination_country')}"
                if order
                else None
            ),
            last_order_reference=order.get("reference"),
            last_order_status=order.get("status"),
        )
        return result


async def check_order_status(reference: str, tool_context: ToolContext = None) -> dict[str, Any]:
    """Check the current status of an order by its reference.

    Re-verifies against Monnify (provider truth), so the answer is live.
    Returns the ETA and customer name so a verified order can be celebrated.

    Args:
        reference: The order reference, e.g. "ord-1a2b3c4d5e".
    """
    with traced("tools.check_order_status", reference=reference):
        try:
            order = await order_store.verify(reference)
        except MonnifyError as exc:
            order = await order_store.get(reference)
            if order is None:
                return {"success": False, "error": f"No order with reference '{reference}'."}
            return {
                "success": True,
                "reference": order.reference,
                "status": order.status,
                "note": f"Could not reach Monnify to re-verify ({exc}); showing last known status.",
            }
        if order is None:
            return {"success": False, "error": f"No order with reference '{reference}'."}
        _remember(
            tool_context,
            last_order_reference=order.reference,
            last_order_status=order.status,
        )
        return {
            "success": True,
            "reference": order.reference,
            "status": order.status,
            "product_name": order.product_name,
            "amount": str(order.amount),
            "currency": order.currency,
            "customer_full_name": order.customer_full_name,
            "destination_city": order.destination_city,
            "destination_country": order.destination_country,
            "express": order.express,
            "eta": order.eta,
        }
