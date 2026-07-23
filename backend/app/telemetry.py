"""Observability seam — OpenTelemetry trace implementation.

Public API
----------
traced(name, **attributes)
    Sync context manager. Use only when the span covers a *block* inside a
    function rather than the whole function (e.g. live_router's session block).

span(name, **arg_attrs)
    Function / method decorator. Declares the span at the signature so the
    intent is visible without reading the body:

        @span("tools.checkout", product_id="product_id")
        async def checkout(product_id: str, ...) -> dict:
            ...

    arg_attrs maps span attribute names to the names of the function's
    own parameters. Works on sync functions, async coroutines, and async
    generators (the three shapes present in this codebase).

set_span_attribute(key, value)
    Adds an attribute to the currently active span from *inside* a function,
    for values that are computed at runtime rather than taken from parameters:

        @span("orders.create", amount="amount")
        async def create_order(self, ..., amount: Decimal) -> Order:
            reference = "ord-" + secrets.token_hex(5)
            set_span_attribute("reference", reference)   # computed locally
            ...

register_secret(value)
    Records a secret value for future log / metric redaction. No-op in
    traces-only mode; the set is available if a scrubbing layer is added later.

Configuration (environment variables)
--------------------------------------
OTEL_SERVICE_NAME            default: oja-connect-backend
OTEL_EXPORTER_OTLP_ENDPOINT  Collector base URL, default: http://localhost:4318
                             /v1/traces is appended automatically.
OTEL_TRACES_SAMPLER          default: always_on
                             Also: parentbased_always_on, traceidratio=<0-1>
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from dotenv import load_dotenv

# Load .env before reading OTEL_ vars so local-dev (non-Docker) runs pick up
# the values. In Docker the real env vars are already set by the compose
# env_file directive; override=False keeps them intact.
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Provider — built once at module import
# ---------------------------------------------------------------------------


def _build_sampler(name: str):
    n = name.strip().lower()
    if n == "always_on":
        return ALWAYS_ON
    if n == "parentbased_always_on":
        return ParentBased(root=ALWAYS_ON)
    if n.startswith("traceidratio"):
        try:
            ratio = float(n.split("=", 1)[1])
        except (IndexError, ValueError):
            ratio = 1.0
        return TraceIdRatioBased(ratio)
    return ALWAYS_ON  # safe fallback


_resource = Resource(attributes={
    "service.name": os.getenv("OTEL_SERVICE_NAME", "oja-connect-backend"),
})

_provider = TracerProvider(
    resource=_resource,
    sampler=_build_sampler(os.getenv("OTEL_TRACES_SAMPLER", "always_on")),
)

_base = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "http://localhost:4318").rstrip("/")
_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{_base}/v1/traces"))
)

trace.set_tracer_provider(_provider)
_tracer = trace.get_tracer("oja-connect")

# ---------------------------------------------------------------------------
# Context manager (for partial-block spans only)
# ---------------------------------------------------------------------------


@contextmanager
def traced(name: str, **attributes: Any) -> Iterator[None]:
    """Open a span around a code *block*.

    Prefer @span for whole functions. Use traced() only when the span must
    cover a subset of a function body (e.g. a single awaited call inside a
    larger method).
    """
    with _tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        yield


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def span(name: str, **arg_attrs: str) -> Callable[[F], F]:
    """Declare a trace span as a decorator.

    arg_attrs maps span attribute names to function *parameter* names:

        @span("tools.get_product", product_id="product_id")
        def get_product(product_id: str) -> dict:
            ...

    The decorator is transparent to callers and to ADK's introspection: it
    preserves the original signature (via functools.wraps + __wrapped__),
    coroutine flag, and async-generator flag so downstream decorators such
    as @node see the correct function shape.
    """
    def decorator(func: F) -> F:
        sig = inspect.signature(func)

        def _extract_attrs(args: tuple, kwargs: dict) -> dict[str, str]:
            """Bind the call's arguments and pull out the declared attrs."""
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return {
                    attr: str(bound.arguments[param])
                    for attr, param in arg_attrs.items()
                    if param in bound.arguments
                }
            except TypeError:
                return {}

        # Async generator (e.g. checkout graph nodes that yield ADK Events).
        if inspect.isasyncgenfunction(func):
            @functools.wraps(func)
            async def _async_gen(*args: Any, **kwargs: Any):
                with traced(name, **_extract_attrs(args, kwargs)):
                    async for item in func(*args, **kwargs):
                        yield item
            return _async_gen  # type: ignore[return-value]

        # Async coroutine.
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def _async(*args: Any, **kwargs: Any) -> Any:
                with traced(name, **_extract_attrs(args, kwargs)):
                    return await func(*args, **kwargs)
            return _async  # type: ignore[return-value]

        # Sync function.
        @functools.wraps(func)
        def _sync(*args: Any, **kwargs: Any) -> Any:
            with traced(name, **_extract_attrs(args, kwargs)):
                return func(*args, **kwargs)
        return _sync  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# In-function attribute helper
# ---------------------------------------------------------------------------


def set_span_attribute(key: str, value: Any) -> None:
    """Set an attribute on the currently active span.

    Use inside @span-decorated functions when the attribute value is computed
    at runtime rather than read from a parameter:

        @span("orders.create")
        async def create_order(self, ...) -> Order:
            reference = "ord-" + secrets.token_hex(5)
            set_span_attribute("reference", reference)
    """
    current = trace.get_current_span()
    if current and current.is_recording():
        current.set_attribute(key, str(value))


# ---------------------------------------------------------------------------
# Secret registration
# ---------------------------------------------------------------------------

_registered_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Record a secret value for future log / metric redaction. No-op for now."""
    if value:
        _registered_secrets.add(value)
