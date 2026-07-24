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
from ..telemetry import set_span_attribute, span
from . import gen_ui
from .checkout_graph import CheckoutError, checkout_workflow, run_checkout_direct

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


@span("tools.list_products")
def list_products() -> dict[str, Any]:
    """List every product in the shop with id, name, description, and price in NGN."""
    return {
        "success": True,
        "products": [_public_product(p) for p in catalog.PRODUCTS],
        "ui_components": [
            gen_ui.product_list(
                [
                    {
                        "productId": p["id"],
                        "name": p["name"],
                        "price": str(p["price"]),
                        "currency": "NGN",
                        "image": p["image"],
                    }
                    for p in catalog.PRODUCTS
                ]
            )
        ],
    }


@span("tools.get_product", product_id="product_id")
def get_product(product_id: str) -> dict[str, Any]:
    """Get one product's details by its product id.

    Renders a product card in the chat. Delivery pricing on the card stays
    empty until quote_delivery is called with a destination.

    Args:
        product_id: The catalog id of the product, e.g. "ankara-tote".
    """
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


@span("tools.quote_delivery", product_id="product_id", city="destination_city")
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


# --- cart (#4): conversational state, not a table ---------------------------
#
# The cart lives in ADK session state under "cart" as a list of
# {"product_id", "quantity"}. It is never persisted until checkout, where it
# becomes the order's line items. Unit prices always come from the catalog;
# nothing the model says sets a price. Money is exact Decimal via money().

CART_KEY = "cart"
MAX_CART_QUANTITY = 20


def _read_cart(tool_context: ToolContext | None) -> list[dict[str, Any]]:
    """Return the current cart (list of {product_id, quantity}) from state."""
    if tool_context is None:
        return []
    try:
        raw = tool_context.state.get(CART_KEY)
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    cart: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("product_id")
        if not pid:
            continue
        try:
            qty = int(entry.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 1
        cart.append({"product_id": str(pid), "quantity": max(1, qty)})
    return cart


def _write_cart(tool_context: ToolContext | None, cart: list[dict[str, Any]]) -> None:
    if tool_context is None:
        return
    try:
        tool_context.state[CART_KEY] = cart
    except Exception as exc:
        log.warning("tools.cart.write_failed error=%s", exc)


def _priced_cart(cart: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Decimal]:
    """Resolve each cart line to a priced line item; return (line_items, subtotal).

    line_item shape mirrors what is persisted at checkout:
    {product_id, product_name, unit_price, quantity, line_total} with money as
    exact strings. Unresolvable lines are dropped defensively (add_to_cart only
    ever stores resolved ids, so this should not happen).
    """
    line_items: list[dict[str, Any]] = []
    subtotal = money(0)
    for entry in cart:
        product = catalog.get_product(entry["product_id"])
        if product is None:
            continue
        quantity = max(1, min(int(entry["quantity"]), MAX_CART_QUANTITY))
        unit_price = money(product["price"])
        line_total = money(unit_price * quantity)
        subtotal += line_total
        line_items.append(
            {
                "product_id": product["id"],
                "product_name": product["name"],
                "unit_price": str(unit_price),
                "quantity": quantity,
                "line_total": str(line_total),
            }
        )
    return line_items, subtotal


def _cart_card_component(cart: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], Decimal]:
    """Build the cart_card ui component for the current cart (no delivery yet)."""
    line_items, subtotal = _priced_cart(cart)
    card = gen_ui.cart_card(line_items, goods_subtotal=str(subtotal))
    return card, line_items, subtotal


def _pairing_suggestion(product: catalog.Product) -> dict[str, Any] | None:
    """A short, deterministic pairing suggestion for a just-added product.

    Returns {reason, products, ui_components} or None when nothing pairs. The
    agent words this; the data is entirely in-code, so no inventory is invented.
    """
    paired = catalog.pairings_for(product["id"])
    if not paired:
        return None
    reason = catalog.pairing_reason(product, paired)
    return {
        "reason": reason,
        "products": [_public_product(p) for p in paired],
        "ui_components": [
            gen_ui.product_list(
                [
                    {
                        "productId": p["id"],
                        "name": p["name"],
                        "price": str(p["price"]),
                        "currency": "NGN",
                        "image": p["image"],
                    }
                    for p in paired
                ],
                title=f"Goes well with {product['name']}",
            )
        ],
    }


@span("tools.add_to_cart", product_id="product_id", quantity="quantity")
def add_to_cart(
    product_id: str,
    quantity: int = 1,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Add a product to the buyer's cart (or increase its quantity).

    Resolves the product loosely by id or name. Quantity is clamped to a whole
    number between 1 and 20. If the product is already in the cart, the
    quantities are merged. Returns the updated cart with line totals and
    subtotal, a cart_card to render, and, when the product has pairings, a
    short complementary-item suggestion the agent may offer once.

    Args:
        product_id: The catalog id or name of the product to add.
        quantity: How many to add (1-20). Defaults to 1.
    """
    product = catalog.resolve_product(product_id)
    if product is None:
        return {
            "success": False,
            "error": "I could not find that item in the shop. Could you tell me "
            "the product name again?",
        }
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        qty = 1
    qty = max(1, min(qty, MAX_CART_QUANTITY))

    cart = _read_cart(tool_context)
    for entry in cart:
        if entry["product_id"] == product["id"]:
            entry["quantity"] = min(entry["quantity"] + qty, MAX_CART_QUANTITY)
            break
    else:
        cart.append({"product_id": product["id"], "quantity": qty})
    _write_cart(tool_context, cart)

    card, line_items, subtotal = _cart_card_component(cart)
    set_span_attribute("cart_lines", len(line_items))
    set_span_attribute("subtotal", str(subtotal))
    result: dict[str, Any] = {
        "success": True,
        "added": {"product_id": product["id"], "name": product["name"], "quantity": qty},
        "cart": line_items,
        "subtotal": str(subtotal),
        "currency": "NGN",
        "ui_components": [card],
    }
    suggestion = _pairing_suggestion(product)
    if suggestion is not None:
        result["suggestion"] = {
            "reason": suggestion["reason"],
            "products": suggestion["products"],
        }
        result["ui_components"].extend(suggestion["ui_components"])
    return result


@span("tools.view_cart")
def view_cart(tool_context: ToolContext = None) -> dict[str, Any]:
    """Show the buyer's current cart with line totals and the subtotal.

    The subtotal is the goods total only; the one per-order delivery fee is
    added at checkout once the destination is known.
    """
    cart = _read_cart(tool_context)
    card, line_items, subtotal = _cart_card_component(cart)
    set_span_attribute("cart_lines", len(line_items))
    return {
        "success": True,
        "cart": line_items,
        "subtotal": str(subtotal),
        "currency": "NGN",
        "empty": not line_items,
        "ui_components": [card],
    }


@span("tools.remove_from_cart", product_id="product_id")
def remove_from_cart(product_id: str, tool_context: ToolContext = None) -> dict[str, Any]:
    """Remove a product line from the cart entirely.

    Args:
        product_id: The catalog id or name of the product to remove.
    """
    product = catalog.resolve_product(product_id)
    target_id = product["id"] if product is not None else str(product_id)
    cart = _read_cart(tool_context)
    new_cart = [e for e in cart if e["product_id"] != target_id]
    removed = len(new_cart) != len(cart)
    _write_cart(tool_context, new_cart)
    card, line_items, subtotal = _cart_card_component(new_cart)
    return {
        "success": True,
        "removed": removed,
        "cart": line_items,
        "subtotal": str(subtotal),
        "currency": "NGN",
        "empty": not line_items,
        "ui_components": [card],
    }


@span("tools.clear_cart")
def clear_cart(tool_context: ToolContext = None) -> dict[str, Any]:
    """Empty the buyer's cart completely."""
    _write_cart(tool_context, [])
    return {"success": True, "cart": [], "subtotal": "0.00", "currency": "NGN", "empty": True}


@span("tools.suggest_pairings", product_id="product_id")
def suggest_pairings(product_id: str, tool_context: ToolContext = None) -> dict[str, Any]:
    """Suggest complementary items that go well with a product.

    Pairings are deterministic catalog data, never invented: explicit pairs
    first, then a tag rule (spicy items pair with cooling drinks). Returns the
    paired products, a short human reason (e.g. "to cool down the pepper"), and
    a titled product_list to render. Offer at most one or two, and never
    pushily.

    Args:
        product_id: The catalog id or name of the product to pair.
    """
    product = catalog.resolve_product(product_id)
    if product is None:
        return {
            "success": False,
            "error": f"No product matching '{product_id}'.",
        }
    suggestion = _pairing_suggestion(product)
    if suggestion is None:
        return {
            "success": True,
            "product_id": product["id"],
            "products": [],
            "reason": "",
            "ui_components": [],
        }
    set_span_attribute("paired_count", len(suggestion["products"]))
    return {
        "success": True,
        "product_id": product["id"],
        "products": suggestion["products"],
        "reason": suggestion["reason"],
        "ui_components": suggestion["ui_components"],
    }


@span("tools.checkout", product_id="product_id")
async def checkout(
    product_id: str = "",
    customer_full_name: str = "",
    customer_email: str = "",
    destination_city: str = "",
    destination_country: str = "",
    express: bool = False,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Create an order and open payment, after the buyer has confirmed the purchase.

    Checks out the whole CART (every item the buyer added), as ONE order with
    ONE delivery fee and ONE payment. Only call this once the buyer has
    confirmed the cart, said where it ships to (city and country) and whether
    they want express, and given their full name and email. As a convenience,
    if the cart is empty you may pass a single product_id to buy just that one
    item. The price is recomputed server side inside the checkout workflow
    (including a live flight fare check for express), so quoted and charged
    totals can differ slightly; relay what this returns.

    Args:
        product_id: Optional. Only used when the cart is empty, to buy one item.
        customer_full_name: The buyer's full name.
        customer_email: The buyer's email address.
        destination_city: The city the order ships to, e.g. "Abuja".
        destination_country: The country of that city, e.g. "Nigeria".
        express: True when the buyer chose the express fly-it option.
    """
    # The cart is the source of truth. Fall back to the single product_id only
    # when the cart is empty, so a direct "buy this one thing" still works.
    cart = _read_cart(tool_context)
    if cart:
        items = [dict(entry) for entry in cart]
    elif product_id:
        items = [{"product_id": product_id, "quantity": 1}]
    else:
        return {
            "success": False,
            "error": "Your cart is empty. Add an item first, then I can check "
            "you out.",
        }
    node_input = {
        "items": items,
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
        # A real validation failure (bad product, missing detail, geocode
        # miss). Relay it; retrying the graph would fail the same way.
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        # The graph engine could not run in this context. This is expected
        # under run_live (the voice door), whose invocation context has no
        # node event queue, so tool_context.run_node raises. Fall back to
        # the direct executor, which runs the identical steps. The graph
        # fails before create_order, so there is no partial order to worry
        # about. This also covers any future graph-runtime breakage.
        log.warning(
            "tools.checkout.graph_unavailable error=%s; using direct path", exc
        )
        try:
            result = await run_checkout_direct(node_input)
        except CheckoutError as exc2:
            return {"success": False, "error": str(exc2)}
        except Exception as exc2:
            log.warning("tools.checkout.direct_failed error=%s", exc2)
            return {
                "success": False,
                "error": "Checkout hit a snag on our side. Nothing was "
                "charged; please try again in a moment.",
            }
    if not isinstance(result, dict):
        return {"success": False, "error": "Checkout returned no result. Please try again."}

    order = result.get("order") or {}
    # The cart has become an order; empty it so the next purchase starts clean.
    if order.get("reference"):
        _write_cart(tool_context, [])
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


@span("tools.check_order_status", reference="reference")
async def check_order_status(reference: str, tool_context: ToolContext = None) -> dict[str, Any]:
    """Check the current status of an order by its reference.

    Re-verifies against Monnify (provider truth), so the answer is live.
    Returns the ETA and customer name so a verified order can be celebrated.

    Args:
        reference: The order reference, e.g. "ord-1a2b3c4d5e".
    """
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
        "line_items": order.line_items or [],
        "amount": str(order.amount),
        "currency": order.currency,
        "customer_full_name": order.customer_full_name,
        "destination_city": order.destination_city,
        "destination_country": order.destination_country,
        "express": order.express,
        "eta": order.eta,
    }
