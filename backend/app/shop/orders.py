"""Order store + verification trust boundary, persisted in Postgres.

Design notes:
  * Orders live in one Postgres table via async SQLAlchemy (asyncpg), so the
    backend can scale horizontally: any replica can create or verify an order.
  * Amounts are Numeric(12,2) in the database and exact Decimals in Python;
    a float never reaches a money decision (D21).
  * verify() is the trust boundary: the only thing that can move an order out
    of pending is Monnify's own answer via query_transaction. A client claim
    never does. VERIFIED is terminal and idempotent.
  * Transition rules (deliberately softer than monnify-studio, which rejects
    on any non-PAID answer): the frontend polls verify while the checkout
    popup is still open, so a not-yet-paid answer must NOT reject the order.
    PAID + covers -> verified. PAID but short -> rejected (underpaid).
    Anything else -> stay pending.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import JSON, Boolean, DateTime, Numeric, String, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..config import get_settings
from ..money import covers, money
from ..telemetry import set_span_attribute, span

STATUS_PENDING = "pending"
STATUS_VERIFIED = "verified"
STATUS_REJECTED = "rejected"

# payment_reference -> {"status": "PAID"|..., "amount_paid": "<exact string>"}
Verifier = Callable[[str], dict[str, Any]]


class Base(DeclarativeBase):
    pass


# One order line, stored as JSON on the order row. Money values are STRINGS so
# the exact Decimal survives the JSON round trip (D21: a float never touches a
# money value, not even in storage).
LineItem = dict[str, str]

# JSONB on Postgres (the real target); plain JSON everywhere else so the same
# model still works under sqlite in any future test.
_LineItemsType = JSONB().with_variant(JSON(), "sqlite")


class Order(Base):
    __tablename__ = "orders"

    reference: Mapped[str] = mapped_column(String(32), primary_key=True)
    # product_id / product_name mirror the FIRST line (plus a "+N more" summary
    # on product_name) so existing single-item reads, the frontend, and the
    # purchasesStore name matching keep working unchanged.
    product_id: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(128))
    # The full order: [{product_id, product_name, unit_price, quantity, line_total}]
    # with money values as exact strings. Nullable so a pre-existing row (before
    # this column) reads back as None rather than failing.
    line_items: Mapped[list[LineItem] | None] = mapped_column(
        _LineItemsType, nullable=True, default=None
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # exact; never float
    currency: Mapped[str] = mapped_column(String(8), default="NGN")
    customer_full_name: Mapped[str] = mapped_column(String(128))
    customer_email: Mapped[str] = mapped_column(String(128))
    destination_city: Mapped[str] = mapped_column(String(64), default="")
    destination_country: Mapped[str] = mapped_column(String(64), default="")
    express: Mapped[bool] = mapped_column(Boolean, default=False)
    eta: Mapped[str] = mapped_column(String(32), default="")
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _monnify_verifier(payment_reference: str) -> dict[str, Any]:
    """Default verifier: ask the Monnify sandbox for the truth (sync httpx)."""
    from ..monnify.client import MonnifySandboxClient

    with MonnifySandboxClient(get_settings()) as client:
        return client.query_transaction(payment_reference=payment_reference)


class OrderStore:
    """Postgres-backed order store. Interface is async; verifier is injectable
    (production uses Monnify's query_transaction, tests inject fakes)."""

    def __init__(self, verifier: Verifier | None = None) -> None:
        self.verifier: Verifier = verifier or _monnify_verifier
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None

    # --- engine lifecycle (called from the app lifespan) ---

    def _sessions(self) -> async_sessionmaker:
        if self._session_factory is None:
            self._engine = create_async_engine(get_settings().async_database_url, pool_pre_ping=True)
            self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        return self._session_factory

    async def init_models(self) -> None:
        """Create the orders table if missing (workshop simplicity, no Alembic).

        metadata.create_all only creates a *missing* table; it will NOT add a
        new column to a table that already exists. `line_items` (#4) is a new
        column, so after create_all we run an idempotent ADD COLUMN IF NOT
        EXISTS. This means an existing demo database gains the column without a
        drop and nobody loses their orders. Postgres supports the IF NOT EXISTS
        clause natively; the guard is a no-op on a freshly created table.
        """
        self._sessions()  # ensure the engine exists
        assert self._engine is not None
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            dialect = conn.engine.dialect.name
            if dialect == "postgresql":
                await conn.execute(
                    text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS line_items JSONB")
                )

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    # --- creation & lookup ---

    @span("orders.create", amount="amount")
    async def create_order(
        self,
        *,
        product_id: str,
        product_name: str,
        line_items: list[LineItem],
        customer_full_name: str,
        customer_email: str,
        destination_city: str,
        destination_country: str,
        express: bool,
        eta: str,
        delivery_fee: Decimal,
        amount: Decimal,
    ) -> Order:
        """Persist a new pending order with its line items.

        `amount` is the exact total charged (goods subtotal plus the one
        per-order delivery fee), computed server side by the caller.
        `product_id` / `product_name` mirror the first line (name may carry a
        "+N more" summary) so single-item reads keep working. `line_items` is
        the full order, money values already stringified exactly.
        """
        reference = "ord-" + secrets.token_hex(5)  # 10 hex chars
        set_span_attribute("reference", reference)  # computed locally, not a parameter
        set_span_attribute("line_count", len(line_items))
        order = Order(
            reference=reference,
            product_id=product_id,
            product_name=product_name,
            line_items=line_items,
            amount=money(amount),
            currency="NGN",
            customer_full_name=customer_full_name,
            customer_email=customer_email,
            destination_city=destination_city,
            destination_country=destination_country,
            express=express,
            eta=eta,
            delivery_fee=money(delivery_fee),
            status=STATUS_PENDING,
        )
        async with self._sessions()() as session:
            session.add(order)
            await session.commit()
        return order

    async def get(self, reference: str) -> Order | None:
        async with self._sessions()() as session:
            result = await session.execute(select(Order).where(Order.reference == reference))
            return result.scalar_one_or_none()

    # --- the trust boundary ---

    @span("orders.verify", reference="reference")
    async def verify(self, reference: str) -> Order | None:
        """Re-derive an order's status from provider truth.

        Called when the frontend polls after the popup, when the agent checks
        status, or when a webhook nudges us. All paths converge here; none of
        them can assert an outcome directly. Idempotent: VERIFIED is terminal,
        and a not-yet-paid provider answer leaves the order pending (the buyer
        may still be inside the checkout popup).
        """
        async with self._sessions()() as session:
            result = await session.execute(select(Order).where(Order.reference == reference))
            order = result.scalar_one_or_none()
            if order is None:
                return None
            if order.status == STATUS_VERIFIED:
                return order  # terminal; nothing a repeat call should change

            # The verifier is sync (httpx client); keep the event loop free.
            truth = await asyncio.to_thread(self.verifier, reference)

            status = str(truth.get("status", "UNKNOWN")).upper()
            amount_paid = money(truth.get("amount_paid") or 0)  # exact, never a float

            if status == "PAID" and covers(amount_paid, order.amount):
                order.status = STATUS_VERIFIED
                order.verified_at = datetime.now(timezone.utc)
            elif status == "PAID":
                order.status = STATUS_REJECTED  # underpaid
            # else: stay pending; polling must not prematurely reject

            await session.commit()
            return order


order_store = OrderStore()
