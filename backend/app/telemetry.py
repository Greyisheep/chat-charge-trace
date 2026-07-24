"""Observability seam - OpenTelemetry trace implementation.

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

Metrics + logs + the shared instrumentation-helper API (issue #11)
------------------------------------------------------------------
This module installs, in addition to the TracerProvider above, a global
MeterProvider (OTLP metric exporter + PeriodicExportingMetricReader) and a
global LoggerProvider (OTLP log exporter). ADK already COMPUTES rich agentic
metrics in google/adk/telemetry/_metrics.py against the *global* meter
(gen_ai.invoke_agent.inference_calls, gen_ai.invoke_agent.tool_calls,
gen_ai.invoke_workflow.duration, gen_ai.execute_tool.duration,
gen_ai.client.token.usage, ...) but exports NONE of them unless a MeterProvider
is installed. Installing it here is what makes that data actually flow.

Shared helper API (the #11 in-code instrumentation follow-up calls these):
  add_span_event(name, **attributes)
  increment_counter(name, amount=1, attributes=None)
  record_histogram(name, value, attributes=None)
  estimate_cost_usd(model, input_tokens, output_tokens, cached_input_tokens=0)

Configuration (environment variables)
--------------------------------------
OTEL_SERVICE_NAME                    default: oja-connect-backend
OTEL_EXPORTER_OTLP_ENDPOINT          Collector base URL, default http://localhost:4318.
                                     /v1/traces, /v1/metrics, /v1/logs are appended.
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT  Optional explicit metrics URL (overrides base).
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT     Optional explicit logs URL (overrides base).
OTEL_TRACES_SAMPLER                  default: always_on
                                     Also: parentbased_always_on, traceidratio=<0-1>

The ADK schema / semconv opt-ins (ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN,
OTEL_SEMCONV_STABILITY_OPT_IN, OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT,
ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS) are read by ADK/OTel themselves from the
real process environment. We deliberately do NOT set them from Python; they are
documented in .env.example and loaded via the .env file / compose env_file.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import os
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from dotenv import load_dotenv

# Load .env before reading OTEL_ vars so local-dev (non-Docker) runs pick up
# the values. In Docker the real env vars are already set by the compose
# env_file directive; override=False keeps them intact.
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Provider - built once at module import
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
# MeterProvider (see #11) - ADK computes agentic metrics against the GLOBAL
# meter but exports NOTHING unless a MeterProvider exists. Installing it is the
# whole point of the metrics half of the task.
# Built once, at import, alongside the tracer. Non-fatal: if the collector is
# down the PeriodicExportingMetricReader export attempts fail silently on a
# background thread and never break a request.
# ---------------------------------------------------------------------------


def _metrics_endpoint() -> str:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    if explicit:
        return explicit
    return f"{_base}/v1/metrics"


def _logs_endpoint() -> str:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
    if explicit:
        return explicit
    return f"{_base}/v1/logs"


_meter_provider: Any = None
try:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    _metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=_metrics_endpoint()),
        export_interval_millis=15000,  # 15s: fine for a live demo dashboard
    )
    _meter_provider = MeterProvider(resource=_resource, metric_readers=[_metric_reader])
    metrics.set_meter_provider(_meter_provider)
except Exception:  # pragma: no cover - never break import/startup on telemetry
    # Leave the no-op global meter provider in place; ADK instruments become
    # no-ops rather than raising. A downed collector must not break the app.
    _meter_provider = None

# Our own meter, used by the shared increment_counter / record_histogram helpers
# (kept separate from ADK's "gcp.vertex.agent" meter so the two are legible
# apart in the backend). get_meter returns a proxy that binds to whichever
# global provider is installed above.
_meter = metrics.get_meter("oja-connect")

# ---------------------------------------------------------------------------
# LoggerProvider - content log events (prompt / response bodies emitted as OTel
# log events under OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY)
# flow here, then out to Loki via the collector. Bodies stay OFF spans (Tempo
# silently truncates any attribute past 2048 bytes), so logs are where the full
# fidelity lives. Non-fatal, same as the meter.
# ---------------------------------------------------------------------------

_logger_provider: Any = None
try:
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    _logger_provider = LoggerProvider(resource=_resource)
    _logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=_logs_endpoint()))
    )
    set_logger_provider(_logger_provider)
except Exception:  # pragma: no cover - never break import/startup on telemetry
    _logger_provider = None

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


# ---------------------------------------------------------------------------
# Shared instrumentation-helper API (issue #11)
#
# These exist NOW so the in-code instrumentation follow-up has a stable surface
# to call. Nothing in this repo calls them yet; that is intentional. All three
# are safe no-ops when no provider / active span is present.
# ---------------------------------------------------------------------------


def add_span_event(name: str, **attributes: Any) -> None:
    """Add an event to the current active span. No-op if there is no span.

    Use for point-in-time facts inside an operation: an agent-to-agent switch,
    a context-cache hit, a barge-in on the voice door, a re-plan.

        add_span_event("agent.switch", to="flight_fare", reason="fare_lookup")
    """
    current = trace.get_current_span()
    if current and current.is_recording():
        # OTel event attributes must be primitive / sequences of primitives.
        current.add_event(name, attributes={k: v for k, v in attributes.items()})


# Lazily created + cached instruments, keyed by name. OTel forbids creating two
# instruments with the same name on one meter, so we memoize.
_counters: dict[str, Any] = {}
_histograms: dict[str, Any] = {}


def increment_counter(
    name: str, amount: int = 1, attributes: dict | None = None
) -> None:
    """Add to a counter, creating and caching it on first use.

        increment_counter("oja.agent.replans", attributes={"agent": "checkout"})
    """
    counter = _counters.get(name)
    if counter is None:
        counter = _meter.create_counter(name)
        _counters[name] = counter
    counter.add(amount, attributes=attributes or {})


def record_histogram(
    name: str, value: float, attributes: dict | None = None
) -> None:
    """Record a value into a histogram, creating and caching it on first use.

        record_histogram("oja.context.size_tokens", 4096, {"agent": "checkout"})
    """
    hist = _histograms.get(name)
    if hist is None:
        hist = _meter.create_histogram(name)
        _histograms[name] = hist
    hist.record(value, attributes=attributes or {})


# ---------------------------------------------------------------------------
# Cost helper (see #11)
#
# OTel gen_ai semconv deliberately has NO cost attribute (price is a business
# concern that changes independently of the trace), so this derived number is
# OURS. Prices are USD per 1,000,000 tokens. Cached input is billed at the
# reduced context-cache-read rate. Update the ONE dict below when Gemini pricing
# changes; nothing else needs to move.
#
# NOTE: these figures are current-as-of-authoring estimates for the AI Studio
# (Gemini API) tier and are meant to be edited, not trusted to the cent.
# ---------------------------------------------------------------------------

# model -> {"input", "output", "cached_input"} USD per 1M tokens.
_GEMINI_PRICES_USD_PER_1M: dict[str, dict[str, str]] = {
    "gemini-flash-latest": {
        "input": "0.30",
        "output": "2.50",
        "cached_input": "0.075",  # context-cache read rate (~25% of input)
    },
    "gemini-3.1-flash-live-preview": {
        # Live / native-audio preview model used by the voice door. Priced
        # higher than the text flash tier; preview pricing, verify before relying.
        "input": "0.50",
        "output": "2.00",
        "cached_input": "0.125",
    },
}

# Fallback used when an unknown model id is passed, so cost is never silently
# zero. Mirrors the text flash tier.
_DEFAULT_PRICE_USD_PER_1M: dict[str, str] = {
    "input": "0.30",
    "output": "2.50",
    "cached_input": "0.075",
}

_ONE_MILLION = Decimal(1_000_000)


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> Decimal:
    """Estimate the USD cost of one model turn as an exact Decimal.

    cached_input_tokens are billed at the reduced cache-read rate and are
    assumed to be a SUBSET already counted in input_tokens (ADK / Gemini report
    cached tokens inside the prompt total), so the uncached input is
    (input_tokens - cached_input_tokens), floored at zero.

    Returns Decimal so callers can sum turns without float drift.
    """
    price = _GEMINI_PRICES_USD_PER_1M.get(model, _DEFAULT_PRICE_USD_PER_1M)
    cached = max(0, cached_input_tokens)
    uncached_input = max(0, input_tokens - cached)

    cost = (
        Decimal(uncached_input) * Decimal(price["input"])
        + Decimal(cached) * Decimal(price["cached_input"])
        + Decimal(max(0, output_tokens)) * Decimal(price["output"])
    ) / _ONE_MILLION
    return cost
