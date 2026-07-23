"""Native AG-UI endpoint via ag-ui-adk ADKAgent.from_app.

Mirrors dockporter-ai's agents_native_router: the ADK App is wrapped by
ADKAgent.from_app, the run generator is wrapped with our transforms, and
add_adk_fastapi_endpoint mounts the SSE endpoint. Mounted in the main.py
lifespan with the shared session service at POST /v1/agents/stream/.
"""

from __future__ import annotations

from typing import Any

from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint
from fastapi import APIRouter
from google.adk.agents.run_config import RunConfig, StreamingMode

from app.agent.adk_app import build_adk_app
from app.agent.agui import wrap_run_with_transforms
from app.agent.shop_agent import create_shop_agent


def _run_config_factory(_input: Any) -> RunConfig:
    """Force SSE so the native bridge streams TEXT token-by-token."""
    return RunConfig(
        streaming_mode=StreamingMode.SSE,
        response_modalities=["TEXT"],
        max_llm_calls=8,
    )


def build_agents_router(session_service: Any) -> APIRouter:
    """Build the AG-UI router. Called from the main.py lifespan (not at
    import) so it shares the app's session service."""
    router = APIRouter()
    adk_agent = ADKAgent.from_app(
        build_adk_app(create_shop_agent()),
        session_service=session_service,
        use_thread_id_as_session_id=True,
        run_config_factory=_run_config_factory,
        # ag-ui-adk's idle reaper hard-deletes ADK sessions after ~20 minutes by
        # default; Postgres is our durable record, so keep only the in-memory
        # registry cleanup (same rationale as dockporter-ai).
        delete_session_on_cleanup=False,
    )
    wrap_run_with_transforms(adk_agent)
    add_adk_fastapi_endpoint(router, adk_agent, path="/")
    return router
