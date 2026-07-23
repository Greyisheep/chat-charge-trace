"""Distance-based delivery pricing, ETAs, and the express fly-it option.

Everything ships from the Oja Connect stall in Lagos. The destination is
geocoded with the free, no-key Open-Meteo geocoding API, the distance is a
haversine from Lagos, and the fee scales with distance. Express delivery is
priced from a live flight fare (found by the flight search agent) with a
markup and handling fee, falling back to 3x the standard fee when no usable
fare is available.

Money rules hold here too (D21): every fee is an exact Decimal quantized to
the kobo via money(). Floats appear only in the geometry (kilometers are not
money).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import Decimal

import httpx

from ..money import money
from ..telemetry import traced
from .catalog import Product

log = logging.getLogger("delivery")

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

LAGOS_LAT, LAGOS_LON = 6.5244, 3.3792

# Standard delivery: base + per-km, capped at something sane.
FEE_BASE_NIGERIA = Decimal("800.00")
FEE_PER_KM_NIGERIA = Decimal("15.00")
FEE_BASE_INTERNATIONAL = Decimal("10000.00")
FEE_PER_KM_INTERNATIONAL = Decimal("25.00")
FEE_CAP = Decimal("250000.00")

# Express fly-it: flight fare (NGN) + 20 percent markup + handling.
EXPRESS_MARKUP = Decimal("1.20")
EXPRESS_HANDLING = Decimal("5000.00")
EXPRESS_FALLBACK_MULTIPLIER = Decimal("3")
NAIRA_PER_USD = Decimal("1600")  # rough fixed workshop rate


class GeocodeUnavailableError(RuntimeError):
    """The geocoding service could not be reached (retryable).

    Distinct from a genuine miss (unknown place), which returns None and must
    NOT be retried. The checkout graph's RetryConfig matches this class name.
    """


@dataclass
class Geo:
    city: str
    country: str
    latitude: float
    longitude: float


@dataclass
class DeliveryQuote:
    product_id: str
    destination_city: str
    destination_country: str
    location_label: str  # e.g. "Abuja, Nigeria"
    distance_km: int
    international: bool
    express: bool
    delivery_fee: Decimal  # exact
    total: Decimal  # product price + fee, exact
    eta: str  # e.g. "2-4 days"
    fee_source: str  # "standard" | "flight_search" | "fallback"


def geocode_city(city: str, country: str = "", *, raise_errors: bool = False) -> Geo | None:
    """Resolve a city to coordinates via Open-Meteo (no API key needed).

    Fetches a few candidates and prefers one matching the given country.
    Returns None on a genuine miss. Transport trouble returns None by default
    (browsing-quote path) or raises GeocodeUnavailableError when raise_errors
    is True (checkout graph path, where the node retries it).
    """
    with traced("delivery.geocode", city=city):
        try:
            resp = httpx.get(
                _GEOCODE_URL,
                params={"name": city.strip(), "count": 5, "language": "en", "format": "json"},
                timeout=10.0,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("delivery.geocode.failed city=%s error=%s", city, exc)
            if raise_errors:
                raise GeocodeUnavailableError(str(exc)) from exc
            return None
    if not results:
        return None
    wanted = country.strip().lower()
    chosen = results[0]
    if wanted:
        for candidate in results:
            if str(candidate.get("country", "")).lower() == wanted:
                chosen = candidate
                break
    return Geo(
        city=str(chosen.get("name") or city),
        country=str(chosen.get("country") or country or "Unknown"),
        latitude=float(chosen["latitude"]),
        longitude=float(chosen["longitude"]),
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def distance_from_lagos_km(geo: Geo) -> int:
    return int(round(haversine_km(LAGOS_LAT, LAGOS_LON, geo.latitude, geo.longitude)))


def standard_fee(distance_km: int, international: bool) -> Decimal:
    if international:
        fee = FEE_BASE_INTERNATIONAL + FEE_PER_KM_INTERNATIONAL * Decimal(distance_km)
    else:
        fee = FEE_BASE_NIGERIA + FEE_PER_KM_NIGERIA * Decimal(distance_km)
    return money(min(fee, FEE_CAP))


def eta_for(distance_km: int, international: bool, express: bool) -> str:
    if express:
        return "2-4 days" if international else "1-2 days"
    if distance_km < 100:
        return "1 day"
    if not international:
        return "2-4 days" if distance_km < 1000 else "3-5 days"
    return "7-14 days"


def express_fee_from_fare(fare: Decimal, currency: str) -> Decimal:
    """Flight fare -> express fee: convert to NGN, add markup and handling."""
    fare_ngn = money(fare) if currency.strip().upper() == "NGN" else money(fare) * NAIRA_PER_USD
    return money(fare_ngn * EXPRESS_MARKUP + EXPRESS_HANDLING)


def express_fallback_fee(base_fee: Decimal) -> Decimal:
    """Express price when no usable flight fare exists: 3x the standard fee."""
    return money(base_fee * EXPRESS_FALLBACK_MULTIPLIER)


def quote_for(
    product: Product,
    destination_city: str,
    destination_country: str,
    *,
    express: bool = False,
    found_flight_price: Decimal | None = None,
    found_flight_currency: str = "NGN",
) -> DeliveryQuote | None:
    """Compute a full delivery quote, or None when geocoding misses.

    This is the browsing-stage path (quote_delivery tool). The checkout graph
    recomputes everything itself node by node; nothing quoted here is trusted
    at charge time.
    """
    geo = geocode_city(destination_city, destination_country)
    if geo is None:
        return None

    distance_km = distance_from_lagos_km(geo)
    international = geo.country.strip().lower() != "nigeria"
    base_fee = standard_fee(distance_km, international)

    fee_source = "standard"
    fee = base_fee
    if express:
        if found_flight_price is not None and found_flight_price > 0:
            fee = express_fee_from_fare(found_flight_price, found_flight_currency)
            fee_source = "flight_search"
        else:
            fee = express_fallback_fee(base_fee)
            fee_source = "fallback"

    return DeliveryQuote(
        product_id=product["id"],
        destination_city=geo.city,
        destination_country=geo.country,
        location_label=f"{geo.city}, {geo.country}",
        distance_km=distance_km,
        international=international,
        express=express,
        delivery_fee=fee,
        total=money(product["price"]) + fee,
        eta=eta_for(distance_km, international, express),
        fee_source=fee_source,
    )
