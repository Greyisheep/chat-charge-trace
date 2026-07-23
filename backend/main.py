"""Oja Connect backend: conversational shop over AG-UI + Monnify sandbox.

FastAPI app wiring only; every seam lives in its own module:
  * /v1/agents/stream/   the AG-UI chat bridge (ADK Gemini agent), lifespan-mounted
  * /api/...             products and order status (shop_router)
  * /webhooks/monnify    signed webhook receiver (webhook_router)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.adk.sessions import DatabaseSessionService

from api import agents_router, shop_router, webhook_router
from app.config import get_settings
from app.shop.orders import order_store

settings = get_settings()  # refuses startup if not pointed at the Monnify sandbox

# The ADK / genai SDK reads GOOGLE_API_KEY from the process environment; our
# settings load it from the repo-root .env, so bridge it across here.
if settings.google_api_key:
    os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ADK sessions live in Postgres (DatabaseSessionService builds an async
    # SQLAlchemy engine, hence the asyncpg-normalized URL), so any replica can
    # serve any conversation.
    svc = DatabaseSessionService(db_url=settings.async_database_url)
    app.state.session_service = svc

    # Orders table (create_all is idempotent; workshop simplicity, no Alembic).
    await order_store.init_models()

    # The AG-UI router is built HERE (not at import) so it shares the app's
    # session service, mirroring dockporter-ai's lifespan mounting.
    app.include_router(
        agents_router.build_agents_router(svc),
        prefix="/v1/agents/stream",
        tags=["Agents AG-UI Stream"],
    )

    try:
        yield
    finally:
        await order_store.dispose()
        # Graceful shutdown of the session service across ADK versions.
        if hasattr(svc, "dispose") and callable(getattr(svc, "dispose")):
            await svc.dispose()
        elif hasattr(svc, "close") and callable(getattr(svc, "close")):
            await svc.close()


app = FastAPI(title="Oja Connect API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "oja-connect-backend"}


app.include_router(shop_router.router, tags=["Shop"])
app.include_router(webhook_router.router, tags=["Webhooks"])
