"""Monnify transaction webhook receiver.

Mirrors monnify-studio's receiver: authenticate, then re-verify.

  1. Authenticity: the request is rejected unless `monnify-signature` matches
     an HMAC-SHA512 of the RAW body keyed by our secret. An unsigned or
     forged call gets 401 and never touches an order.
  2. The webhook nudges; it never asserts. Even a valid signature does not
     set an order paid: we re-derive from provider truth via the same
     verify() trust boundary as every other path. A duplicate delivery is
     harmless (verify() is terminal at verified).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.monnify.client import MonnifyError
from app.shop.orders import order_store

log = logging.getLogger("webhooks")

router = APIRouter()


@router.post("/webhooks/monnify")
async def monnify_webhook(request: Request) -> dict[str, Any]:
    raw = await request.body()
    secret = get_settings().monnify_secret_key
    signature = request.headers.get("monnify-signature", "")
    computed = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
    if not secret or not hmac.compare_digest(signature, computed):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="webhook body is not JSON") from None
    event_data = payload.get("eventData", payload) or {}
    payment_reference = event_data.get("paymentReference", "")

    # Our order reference IS the Monnify paymentReference (the frontend passes
    # it to the checkout popup), so the lookup is direct.
    order = await order_store.get(payment_reference)
    if order is None:
        # Ack unknown references with 200 so Monnify does not retry forever.
        log.info("webhook.unmatched payment_reference=%s", payment_reference)
        return {"received": True, "matched": False}

    try:
        updated = await order_store.verify(order.reference)  # re-query, never trust the payload
    except MonnifyError as exc:
        raise HTTPException(status_code=502, detail=f"Monnify sandbox error: {exc}") from None
    assert updated is not None
    log.info("webhook.verified reference=%s status=%s", updated.reference, updated.status)
    return {"received": True, "reference": updated.reference, "status": updated.status}
