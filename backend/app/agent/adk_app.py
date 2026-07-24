"""ADK App assembly: root agent + the shared plugin stack.

Mirrors dockporter-ai's adk_app.py in miniature. Single source of truth for
the plugins attached to the App consumed by ADKAgent.from_app (the AG-UI
bridge). Anything that changes plugin behavior changes here.
"""

from __future__ import annotations

from typing import Any

from google.adk.apps import App
from google.adk.apps.app import ContextCacheConfig
from google.adk.plugins.context_filter_plugin import ContextFilterPlugin
from google.adk.plugins.global_instruction_plugin import GlobalInstructionPlugin

from .telemetry_hooks import TelemetryReflectAndRetryToolPlugin

APP_NAME = "oja_connect_app"

GLOBAL_INSTRUCTION = """
You work for Oja Connect, a small Lagos market shop. Currency is Nigerian
Naira (NGN). Be warm, honest, and concise. Never invent prices, products,
or payment confirmations; every number comes from a tool result.
""".strip()


def build_adk_plugins() -> list[Any]:
    """Plugins attached to the App (order matters for plugin invocation)."""
    return [
        # Shared brand-and-honesty preamble for every agent in the app.
        GlobalInstructionPlugin(global_instruction=GLOBAL_INSTRUCTION),
        # Keep long chats from dragging the whole history into every LLM call.
        ContextFilterPlugin(num_invocations_to_keep=20),
        # A flaky tool call (geocoder timeout, Monnify hiccup) gets reflected
        # on and retried instead of surfacing a raw stack trace to the buyer.
        # Telemetry subclass so each retry emits a span event + counter (#11).
        TelemetryReflectAndRetryToolPlugin(max_retries=2),
    ]


def build_adk_app(root_agent: Any, *, name: str = APP_NAME) -> App:
    return App(
        name=name,
        root_agent=root_agent,
        plugins=build_adk_plugins(),
        # Cache the stable prompt prefix (static_instruction + tool
        # declarations) across turns: refresh the cache every 10 LLM calls or
        # 30 minutes, and only bother once the prefix is big enough to pay off.
        context_cache_config=ContextCacheConfig(
            cache_intervals=10,
            ttl_seconds=1800,
            min_tokens=2048,
        ),
    )
