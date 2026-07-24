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
from ..telemetry import (
    add_span_event,
    increment_counter,
    set_span_attribute,
    span,
    traced,
)
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


MAX_LINE_QUANTITY = 20


def _normalize_items(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the requested cart lines out of a checkout request.

    Accepts the new multi-item shape (request["items"] = [{product_id,
    quantity}]) and the legacy single-item shape (request["product_id"]) so a
    direct "buy this one thing" call still works. Returns raw, unresolved lines
    (validation happens in _validate_impl).
    """
    items = request.get("items")
    if isinstance(items, list) and items:
        return [dict(it) for it in items if isinstance(it, dict)]
    pid = request.get("product_id")
    if pid:
        return [{"product_id": pid, "quantity": 1}]
    return []


def _clamp_quantity(raw: Any) -> int:
    """Coerce a requested quantity to a sane positive int (1..MAX_LINE_QUANTITY)."""
    try:
        qty = int(raw)
    except (TypeError, ValueError):
        qty = 1
    if qty < 1:
        qty = 1
    if qty > MAX_LINE_QUANTITY:
        qty = MAX_LINE_QUANTITY
    return qty


@span("checkout.validate_product")
def _validate_impl(request: dict[str, Any]) -> dict[str, Any]:
    """Validate the checkout request and resolve every line; pure, no ADK ctx.

    Shared by the graph node and the direct executor so both doors validate
    identically. Reads the cart from request["items"] (falling back to a single
    request["product_id"] line for the legacy path). Resolves each product
    loosely (id or name) so a near-miss like "suya-spice-box" still finds
    "suya-spice", merges duplicate lines, and computes each line total and the
    goods subtotal with exact Decimal money(). Nothing here is a float, and no
    number ever comes from the model: unit prices come straight from the
    catalog.
    """
    raw_lines = _normalize_items(request)
    if not raw_lines:
        raise CheckoutError(
            "Your cart is empty. Tell me which item (or items) you would like "
            "to buy first."
        )
    if not str(request.get("customer_full_name", "")).strip():
        raise CheckoutError("The buyer's full name is required first.")
    if "@" not in str(request.get("customer_email", "")):
        raise CheckoutError("A valid email address is required first.")
    if not str(request.get("destination_city", "")).strip():
        raise CheckoutError("The destination city is required first.")

    # Resolve + merge duplicate product lines, preserving first-seen order.
    merged: dict[str, int] = {}
    order_seen: list[str] = []
    for raw in raw_lines:
        product = catalog.resolve_product(str(raw.get("product_id", "")))
        if product is None:
            raise CheckoutError(
                "I could not find one of those items in the shop. Could you "
                "tell me the product name again?"
            )
        qty = _clamp_quantity(raw.get("quantity", 1))
        pid = product["id"]
        if pid not in merged:
            merged[pid] = 0
            order_seen.append(pid)
        merged[pid] += qty

    line_items: list[dict[str, Any]] = []
    goods_subtotal = money(0)
    for pid in order_seen:
        product = catalog.get_product(pid)
        quantity = min(merged[pid], MAX_LINE_QUANTITY)
        unit_price = money(product["price"])
        line_total = money(unit_price * quantity)
        goods_subtotal += line_total
        line_items.append(
            {
                "product_id": product["id"],
                "product_name": product["name"],
                "unit_price": str(unit_price),
                "quantity": quantity,
                "line_total": str(line_total),
            }
        )

    request = dict(request)
    first = catalog.get_product(order_seen[0])
    request["product_id"] = first["id"]
    return {
        "request": request,
        # The first line's product still drives the primary product card and
        # the mirrored product_id / product_name columns.
        "product": dict(first),
        "line_items": line_items,
        "goods_subtotal": str(goods_subtotal),
        # Kept so downstream fee math (which reads payload["price"]) stays the
        # goods subtotal, not a single unit price.
        "price": str(goods_subtotal),
    }


@node(name="validate_product")
def validate_product(ctx: Context, node_input: Any) -> dict[str, Any]:
    return _validate_impl(_as_request(node_input))


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
    # Conditional-edge routing rationale + which checkout path ran. There is no
    # OTel standard for edge/routing telemetry, so these are ours (see #11).
    set_span_attribute("path", "graph")
    set_span_attribute("gen_ai.workflow.route", route)
    set_span_attribute(
        "route.reason",
        "buyer chose express air" if route == ROUTE_EXPRESS
        else "standard road delivery",
    )
    set_span_attribute("route.candidates", "standard,express")
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
    # Agent-to-agent handoff: shop -> flight fare search sub-agent (see #11).
    add_span_event(
        "agent.handoff",
        from_agent="shop",
        to_agent="flight_price_search",
        reason="express flight fare lookup",
    )
    increment_counter("oja.agent.handoff", attributes={"to": "flight_price_search"})
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


@span("checkout.compute_fee")
def _compute_fee_impl(
    payload: dict[str, Any], fare: dict[str, str] | None, express: bool
) -> dict[str, Any]:
    """Derive the final fee, total, and ETA; pure, shared by node and direct path."""
    if express:
        base_fee = money(payload["standard_fee"])
        if fare:
            fee = delivery.express_fee_from_fare(money(fare["price"]), fare["currency"])
            fee_source = "flight_search"
        else:
            fee = delivery.express_fallback_fee(base_fee)
            fee_source = "fallback"
    else:
        fee = money(payload["standard_fee"])
        fee_source = "standard"

    total = money(payload["price"]) + fee
    payload.update(
        express=express,
        delivery_fee=str(fee),
        total=str(total),
        eta=delivery.eta_for(payload["distance_km"], payload["international"], express),
        fee_source=fee_source,
    )
    return payload


@node(name="compute_fee")
def compute_fee(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Merge point of both branches: derive the final fee, total, and ETA.

    Standard branch input: the quote payload from standard_quote.
    Express branch input: the JoinNode's {predecessor_name: output} dict.
    """
    if isinstance(node_input, dict) and "express_base_quote" in node_input:
        payload = dict(node_input["express_base_quote"])
        fare = (node_input.get("flight_fare_lookup") or {}).get("fare")
        return _compute_fee_impl(payload, fare, express=True)
    return _compute_fee_impl(dict(node_input), fare=None, express=False)


def _summary_product_name(line_items: list[dict[str, Any]]) -> str:
    """A short name for the first product plus a "+N more" tail for extra lines.

    The mirrored product_name column keeps single-item reads meaningful; for a
    multi-line order it reads e.g. "Suya Spice Box +2 more" (2 = the number of
    OTHER distinct product lines).
    """
    first_name = str(line_items[0]["product_name"])
    extra = len(line_items) - 1
    if extra <= 0:
        return first_name
    return f"{first_name} +{extra} more"


@span("checkout.create_order")
async def _create_order_impl(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist the order (with its line items) in Postgres.

    Every number here was derived above by _validate_impl (goods subtotal, line
    totals) and _compute_fee_impl (delivery fee, total). Nothing came from the
    model.
    """
    request = payload["request"]
    line_items = payload["line_items"]
    first = catalog.get_product(str(line_items[0]["product_id"]))
    order = await order_store.create_order(
        product_id=first["id"],
        product_name=_summary_product_name(line_items),
        line_items=line_items,
        customer_full_name=str(request["customer_full_name"]).strip(),
        customer_email=str(request["customer_email"]).strip(),
        destination_city=payload["destination_city"],
        destination_country=payload["destination_country"],
        express=payload["express"],
        eta=payload["eta"],
        delivery_fee=Decimal(payload["delivery_fee"]),
        amount=Decimal(payload["total"]),
    )
    set_span_attribute("reference", order.reference)  # computed locally
    payload["order"] = {
        "reference": order.reference,
        "product_id": order.product_id,
        "product_name": order.product_name,
        "line_items": order.line_items,
        "amount": str(order.amount),
        "goods_subtotal": payload["goods_subtotal"],
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


@node(name="create_order")
async def create_order_node(ctx: Context, node_input: Any) -> dict[str, Any]:
    return await _create_order_impl(dict(node_input))


def _items_phrase(line_items: list[dict[str, Any]]) -> str:
    """Human list of the ordered items, e.g. "Suya Spice Box x2 and Chilled Cola".

    A quantity of 1 is left implicit; quantities above 1 get an "xN" suffix.
    The last item is joined with "and"; three or more use Oxford commas.
    """
    parts: list[str] = []
    for line in line_items:
        name = str(line["product_name"])
        qty = int(line["quantity"])
        parts.append(f"{name} x{qty}" if qty > 1 else name)
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


@span("checkout.payment_event")
def _build_result_impl(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the terminal tool-result payload; pure, shared by node and direct path.

    The order may carry several line items now. The description reads naturally
    for one or many ("Suya Spice Box x2 and Chilled Cola to Lagos, standard
    delivery, arrives 1 day"). The primary product card is still the first
    line's product; a cart_card summarises the whole order and its money.
    """
    order = payload["order"]
    product = payload["product"]
    line_items = order["line_items"]
    mode = "express air" if order["express"] else "standard delivery"
    description = (
        f"{_items_phrase(line_items)} to {order['destination_city']}, "
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

    # A cart_card summarises the whole order (every line + money breakdown).
    # For a single-line order we ALSO keep the familiar product_card, so the
    # common one-item path renders exactly as before and the frontend's
    # name-matching (purchasesStore) still lights up. Multi-line orders lead
    # with the cart_card.
    ui_components: list[dict[str, Any]] = [
        gen_ui.cart_card(
            line_items,
            goods_subtotal=order["goods_subtotal"],
            delivery_fee=order["delivery_fee"],
            total=order["amount"],
            currency="NGN",
            location_label=payload["location_label"],
            distance_km=payload["distance_km"],
            eta=order["eta"],
            express=order["express"],
            reference=order["reference"],
        )
    ]
    if len(line_items) == 1:
        ui_components.append(
            gen_ui.product_card(
                product_public,
                delivery_fee=order["delivery_fee"],
                total=order["amount"],
                location_label=payload["location_label"],
                distance_km=payload["distance_km"],
                eta=order["eta"],
                express=order["express"],
            )
        )

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
        "ui_components": ui_components,
    }


@node(name="payment_event")
def payment_event_node(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Terminal node: the tool-result payload the frontend contract expects."""
    return _build_result_impl(dict(node_input))


# --- direct executor (used when the graph engine is unavailable) -------------
#
# run_live drives the checkout tool under an invocation context that has no node
# event queue, so tool_context.run_node(checkout_workflow) raises there. The
# direct executor runs the SAME shared step impls in sequence without the graph
# engine, so the voice door checks out identically to the text door. Each step
# is traced() so the observability seam still sees the same span boundaries.


async def _standalone_fare(city: str, country: str) -> dict[str, str] | None:
    """Get a flight fare by running the flight agent in its own Runner.

    The graph's fare leg uses ctx.run_node, which is unavailable in the direct
    path, so here the google_search flight agent runs under a private
    InMemory runner. Any failure means "no fare" (the caller falls back to the
    fixed express multiple); it can never break checkout.
    """
    try:
        # Agent-to-agent handoff on the direct (voice) path too (see #11).
        add_span_event(
            "agent.handoff",
            from_agent="shop",
            to_agent="flight_price_search",
            reason="express flight fare lookup",
        )
        increment_counter(
            "oja.agent.handoff", attributes={"to": "flight_price_search"}
        )
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types as gtypes

        service = InMemorySessionService()
        runner = Runner(
            agent=create_flight_agent(),
            app_name="flight_fare",
            session_service=service,
        )
        await service.create_session(
            app_name="flight_fare", user_id="checkout", session_id="fare"
        )
        prompt = (
            f"Find the current approximate one-way economy flight fare from "
            f"Lagos, Nigeria to {city}, {country}."
        )
        message = gtypes.Content(role="user", parts=[gtypes.Part(text=prompt)])
        collected: list[str] = []

        async def _drive() -> None:
            async for event in runner.run_async(
                user_id="checkout", session_id="fare", new_message=message
            ):
                content = getattr(event, "content", None)
                for part in getattr(content, "parts", None) or []:
                    if getattr(part, "text", None):
                        collected.append(part.text)

        await asyncio.wait_for(_drive(), timeout=FLIGHT_NODE_TIMEOUT_S)
        return _parse_fare_text("".join(collected))
    except Exception as exc:  # a fare miss must never kill checkout
        log.warning("checkout.standalone_fare.failed error=%s", exc)
        return None


async def run_checkout_direct(node_input: Any) -> dict[str, Any]:
    """Run the checkout pipeline without the ADK graph engine (live path)."""
    request = _as_request(node_input)
    with traced("checkout.direct", path="direct"):
        payload = _validate_impl(request)
        req = payload["request"]
        with traced(
            "checkout.geocode_destination",
            city=str(req.get("destination_city")),
            country=str(req.get("destination_country", "")),
        ):
            geo = await asyncio.to_thread(
                delivery.geocode_city,
                str(req["destination_city"]),
                str(req.get("destination_country", "")),
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
        payload["standard_fee"] = str(
            delivery.standard_fee(payload["distance_km"], payload["international"])
        )
        express = bool(req.get("express"))
        # Same routing rationale the graph node stamps, on the direct span; the
        # span already carries path="direct" (see #11). No OTel standard exists
        # for this, so the attributes are ours.
        route = ROUTE_EXPRESS if express else ROUTE_STANDARD
        set_span_attribute("gen_ai.workflow.route", route)
        set_span_attribute(
            "route.reason",
            "buyer chose express air" if express else "standard road delivery",
        )
        set_span_attribute("route.candidates", "standard,express")
        fare = None
        if express:
            with traced("checkout.flight_fare_lookup", city=payload["destination_city"]):
                fare = await _standalone_fare(
                    payload["destination_city"], payload["destination_country"]
                )
        payload = _compute_fee_impl(payload, fare, express)
        # _create_order_impl and _build_result_impl carry their own
        # @span("checkout.create_order") / @span("checkout.payment_event"),
        # so the direct path emits the same span names as the graph path.
        payload = await _create_order_impl(payload)
        return _build_result_impl(payload)


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
