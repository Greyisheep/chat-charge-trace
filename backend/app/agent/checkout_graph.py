"""The checkout money path as an explicit google.adk.workflow graph.

Topology (google-adk 2.5.0 Workflow):

    START -> validate_product -> geocode_destination
        route "standard" -> standard_quote ----------------------+
        route "express"  -> (express_base_quote, flight_fare_lookup)
                                 |                |
                            fee_join (JoinNode, waits for both)
                                 |                                |
                                 +---------> compute_fee <--------+
                                                 |
                                          create_order
                                                 |
                                          payment_event   (single terminal output)

Design rules:
  * Real dataflow: each node passes its payload dict downstream as the node
    output (node_input on the next node); fan-in arrives as a
    {predecessor_name: output} dict on the JoinNode.
  * The graph never trusts a model-provided number. It re-geocodes, re-prices,
    and re-derives the express fee itself; the flight fare comes from the
    google_search LlmAgent running as a dynamic child node inside
    flight_fare_lookup, wrapped in a timeout and a try/except so its failure
    can only ever mean "no fare" (fallback 3x standard), never a dead checkout.
  * Deterministic nodes are plain @node functions; retries are per node
    (geocode retries only GeocodeUnavailableError, so an unknown place is
    not retried).
  * The single terminal node (payment_event) emits the tool-result dict that
    carries payment_event + ui_components, so the AG-UI transform layer lifts
    them without change.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.workflow import START, JoinNode, RetryConfig, Workflow, node

from ..money import money
from ..shop import catalog, delivery
from ..shop.orders import order_store
from ..telemetry import set_span_attribute, span, traced
from . import gen_ui
from .flight_agent import create_flight_agent

log = logging.getLogger("checkout")

ROUTE_STANDARD = "standard"
ROUTE_EXPRESS = "express"

FLIGHT_NODE_TIMEOUT_S = 75.0

GEOCODE_MISS_ERROR = (
    "I could not find that place on the map. Could you give me the nearest "
    "big city (and the country) instead?"
)


class CheckoutError(ValueError):
    """A buyer-facing checkout failure; the message is safe to relay."""


def _as_request(node_input: Any) -> dict[str, Any]:
    """Normalize the workflow input (pydantic model or dict) to a plain dict."""
    if hasattr(node_input, "model_dump"):
        return node_input.model_dump()
    if isinstance(node_input, dict):
        return dict(node_input)
    raise CheckoutError("Checkout needs the product, destination, name, and email.")


# --- deterministic nodes -----------------------------------------------------


@node(name="validate_product")
@span("checkout.validate_product")
def validate_product(ctx: Context, node_input: Any) -> dict[str, Any]:
    request = _as_request(node_input)
    product = catalog.get_product(str(request.get("product_id", "")))
    if product is None:
        raise CheckoutError(f"No product with id '{request.get('product_id')}'.")
    if not str(request.get("customer_full_name", "")).strip():
        raise CheckoutError("The buyer's full name is required first.")
    if "@" not in str(request.get("customer_email", "")):
        raise CheckoutError("A valid email address is required first.")
    if not str(request.get("destination_city", "")).strip():
        raise CheckoutError("The destination city is required first.")
    return {
        "request": request,
        "product": dict(product),
        "price": str(product["price"]),
    }


@node(
    name="geocode_destination",
    timeout=30.0,
    retry_config=RetryConfig(
        max_attempts=3,
        initial_delay=0.5,
        exceptions=[delivery.GeocodeUnavailableError],
    ),
)
@span("checkout.geocode_destination")
async def geocode_destination(ctx: Context, node_input: Any):
    payload = dict(node_input)
    request = payload["request"]
    set_span_attribute("city", request.get("destination_city", ""))
    set_span_attribute("country", request.get("destination_country", ""))
    geo = await asyncio.to_thread(
        delivery.geocode_city,
        str(request["destination_city"]),
        str(request.get("destination_country", "")),
        raise_errors=True,
    )
    if geo is None:
        raise CheckoutError(GEOCODE_MISS_ERROR)
    payload.update(
        destination_city=geo.city,
        destination_country=geo.country,
        location_label=f"{geo.city}, {geo.country}",
        distance_km=delivery.distance_from_lagos_km(geo),
        international=geo.country.strip().lower() != "nigeria",
    )
    route = ROUTE_EXPRESS if request.get("express") else ROUTE_STANDARD
    yield Event(output=payload, route=route)


def _standard_quote(ctx: Context, node_input: Any) -> dict[str, Any]:
    payload = dict(node_input)
    fee = delivery.standard_fee(payload["distance_km"], payload["international"])
    payload["standard_fee"] = str(fee)
    return payload


# The same pure function serves both branches under two node names, so each
# branch owns its node and the fan-in bookkeeping stays unambiguous.
standard_quote = node(_standard_quote, name="standard_quote")
express_base_quote = node(_standard_quote, name="express_base_quote")


# --- the flight fare leg (LlmAgent as a contained graph node) ---------------


def _parse_fare_text(raw: Any) -> dict[str, str] | None:
    """Extract {"price", "currency"} from the flight agent's reply, or None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    price = str(data.get("price", "")).strip().replace(",", "")
    currency = str(data.get("currency", "NGN")).strip().upper() or "NGN"
    if not price:
        return None
    try:
        if money(price) <= 0:
            return None
    except (InvalidOperation, ArithmeticError):
        return None
    return {"price": price, "currency": currency}


async def _agent_fare_resolver(ctx: Context, city: str, country: str) -> dict[str, str] | None:
    """Run the google_search flight agent as a dynamic child node of the graph."""
    agent_node = node(create_flight_agent(), name="flight_price_search", timeout=60.0)
    prompt = (
        f"Find the current approximate one-way economy flight fare from "
        f"Lagos, Nigeria to {city}, {country}."
    )
    raw = await asyncio.wait_for(
        ctx.run_node(agent_node, node_input=prompt),
        timeout=FLIGHT_NODE_TIMEOUT_S,
    )
    return _parse_fare_text(raw)


# Seam: the boot check (and any test) swaps this for a stub so the graph runs
# end to end without a Gemini call.
fare_resolver = _agent_fare_resolver


@node(name="flight_fare_lookup", timeout=90.0)
@span("checkout.flight_fare_lookup")
async def flight_fare_lookup(ctx: Context, node_input: Any) -> dict[str, Any]:
    payload = dict(node_input)
    set_span_attribute("city", payload["destination_city"])
    fare: dict[str, str] | None = None
    try:
        fare = await fare_resolver(
            ctx, payload["destination_city"], payload["destination_country"]
        )
    except Exception as exc:  # a fare miss must never kill checkout
        log.warning("checkout.flight_fare_lookup.failed error=%s", exc)
    return {"fare": fare}


fee_join = JoinNode(name="fee_join")


# --- merge, order, payment ---------------------------------------------------


@node(name="compute_fee")
@span("checkout.compute_fee")
def compute_fee(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Merge point of both branches: derive the final fee, total, and ETA.

    Standard branch input: the quote payload from standard_quote.
    Express branch input: the JoinNode's {predecessor_name: output} dict.
    """
    if isinstance(node_input, dict) and "express_base_quote" in node_input:
        payload = dict(node_input["express_base_quote"])
        fare = (node_input.get("flight_fare_lookup") or {}).get("fare")
        base_fee = money(payload["standard_fee"])
        if fare:
            fee = delivery.express_fee_from_fare(money(fare["price"]), fare["currency"])
            fee_source = "flight_search"
        else:
            fee = delivery.express_fallback_fee(base_fee)
            fee_source = "fallback"
        express = True
    else:
        payload = dict(node_input)
        fee = money(payload["standard_fee"])
        fee_source = "standard"
        express = False

    total = money(payload["price"]) + fee
    payload.update(
        express=express,
        delivery_fee=str(fee),
        total=str(total),
        eta=delivery.eta_for(payload["distance_km"], payload["international"], express),
        fee_source=fee_source,
    )
    return payload


@node(name="create_order")
@span("checkout.create_order")
async def create_order_node(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Persist the order in Postgres. Every number here was derived in-graph."""
    payload = dict(node_input)
    request = payload["request"]
    product = catalog.get_product(payload["product"]["id"])
    order = await order_store.create_order(
        product,
        str(request["customer_full_name"]).strip(),
        str(request["customer_email"]).strip(),
        destination_city=payload["destination_city"],
        destination_country=payload["destination_country"],
        express=payload["express"],
        eta=payload["eta"],
        delivery_fee=Decimal(payload["delivery_fee"]),
        amount=Decimal(payload["total"]),
    )
    payload["order"] = {
        "reference": order.reference,
        "product_id": order.product_id,
        "product_name": order.product_name,
        "amount": str(order.amount),
        "currency": order.currency,
        "destination_city": order.destination_city,
        "destination_country": order.destination_country,
        "express": order.express,
        "eta": order.eta,
        "delivery_fee": str(order.delivery_fee),
        "status": order.status,
    }
    payload["customer_full_name"] = order.customer_full_name
    payload["customer_email"] = order.customer_email
    return payload


@node(name="payment_event")
@span("checkout.payment_event")
def payment_event_node(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Terminal node: the tool-result payload the frontend contract expects."""
    payload = dict(node_input)
    order = payload["order"]
    product = payload["product"]
    mode = "express air" if order["express"] else "standard delivery"
    description = (
        f"{order['product_name']} to {order['destination_city']}, "
        f"{mode}, arrives {order['eta']}"
    )
    amount = money(order["amount"])
    product_public = {
        "id": product["id"],
        "name": product["name"],
        "description": product["description"],
        "price": str(money(product["price"])),
        "currency": "NGN",
        "image": product["image"],
    }
    return {
        "success": True,
        "message": (
            f"Order {order['reference']} created: {description}. "
            f"Total NGN {amount:,.2f} including delivery. "
            "The payment window opens now."
        ),
        "order": order,
        "payment_event": {
            "type": "open_payment_modal",
            "payment_data": {
                "reference": order["reference"],
                "amount": order["amount"],
                "currency": "NGN",
                "customerFullName": payload["customer_full_name"],
                "customerEmail": payload["customer_email"],
                "description": description,
            },
        },
        "ui_components": [
            gen_ui.product_card(
                product_public,
                delivery_fee=order["delivery_fee"],
                total=order["amount"],
                location_label=payload["location_label"],
                distance_km=payload["distance_km"],
                eta=order["eta"],
                express=order["express"],
            )
        ],
    }


# --- the graph ---------------------------------------------------------------


def build_checkout_workflow() -> Workflow:
    return Workflow(
        name="checkout",
        description="Deterministic checkout: validate, price, order, payment event.",
        edges=[
            (START, validate_product, geocode_destination),
            (
                geocode_destination,
                {
                    ROUTE_STANDARD: standard_quote,
                    ROUTE_EXPRESS: (express_base_quote, flight_fare_lookup),
                },
            ),
            (standard_quote, compute_fee),
            (express_base_quote, fee_join),
            (flight_fare_lookup, fee_join),
            (fee_join, compute_fee),
            (compute_fee, create_order_node, payment_event_node),
        ],
    )


checkout_workflow = build_checkout_workflow()
