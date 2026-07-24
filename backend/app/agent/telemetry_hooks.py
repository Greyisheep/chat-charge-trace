"""Agent-layer telemetry hooks (see #11 - the instrumentation follow-up).

Two things ADK does not surface as metrics we control, plus one plugin with no
telemetry at all:

  * make_usage_recording_callback: an ADK after_model_callback factory that reads
    the LLM response usage metadata (including the cache-read token count ADK
    never emits as a metric) and records token + derived-cost histograms. Wired
    onto every LlmAgent in shop_agent.py / flight_agent.py.
  * TelemetryReflectAndRetryToolPlugin: subclasses ReflectAndRetryToolPlugin so
    each reflection-guidance injection emits a span event + a retry counter.
  * record_llm_usage: the shared token/cost recorder, reused by the voice door
    (api/live_router.py) so text and voice report identical metric shapes.

Everything here is wrapped so a telemetry failure can never break a turn.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from google.adk.plugins import ReflectAndRetryToolPlugin

from ..telemetry import (
    add_span_event,
    estimate_cost_usd,
    increment_counter,
    record_histogram,
)

log = logging.getLogger("telemetry_hooks")


def _usage_int(usage: Any, field: str) -> int:
    """Read one usage-metadata token count, guarded to a non-negative int.

    ADK / Gemini leave any absent field as None (thoughts / cache counts are
    only present on some models), so every field is getattr-with-None guarded
    per #11.
    """
    value = getattr(usage, field, None)
    try:
        return max(0, int(value)) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def record_llm_usage(model: str, usage: Any, door: str | None = None) -> None:
    """Record token + derived-cost histograms for one model turn (see #11).

    Shared by the text after_model_callback and the voice door so both channels
    emit the same four metrics. `door` (e.g. "voice") is added as an extra
    attribute when present. Cost stays exact Decimal until the last moment;
    only the histogram record (which the OTel API takes as a float) casts it.
    """
    if usage is None:
        return
    try:
        prompt = _usage_int(usage, "prompt_token_count")
        candidates = _usage_int(usage, "candidates_token_count")
        cached = _usage_int(usage, "cached_content_token_count")

        attrs: dict[str, str] = {"model": model}
        if door:
            attrs["door"] = door

        record_histogram("oja.llm.input_tokens", prompt, attrs)
        record_histogram("oja.llm.output_tokens", candidates, attrs)
        # The cache-hit proof: gen_ai.usage.cache_read tokens ADK never exports.
        record_histogram("oja.llm.cached_input_tokens", cached, attrs)

        cost = estimate_cost_usd(model, prompt, candidates, cached)
        record_histogram("oja.llm.cost_usd", float(cost), attrs)
    except Exception as exc:  # a telemetry miss must never break a turn (#11)
        log.debug("telemetry_hooks.record_llm_usage.failed error=%s", exc)


def make_usage_recording_callback(model: str) -> Callable[..., Optional[Any]]:
    """Build an ADK after_model_callback bound to one agent's model (see #11).

    ADK's after_model_callback fires with (CallbackContext, LlmResponse); the
    model id is not on the response, so it is closed over here from the agent's
    own config. Partial streaming chunks carry no usage, and their partial=True
    flag guards against double counting the final aggregated response.
    """

    # ADK invokes after_model_callback with keyword arguments, so these
    # parameter names must match its signature exactly (callback_context,
    # llm_response); callback_context is unused (see #11).
    def _after_model(callback_context: Any, llm_response: Any) -> Optional[Any]:
        try:
            # Skip streaming partials; only the final response bears usage.
            if getattr(llm_response, "partial", None):
                return None
            usage = getattr(llm_response, "usage_metadata", None)
            record_llm_usage(model, usage)
        except Exception as exc:  # never let telemetry break a turn (#11)
            log.debug("telemetry_hooks.after_model.failed error=%s", exc)
        # Return None: we observe the response, we never rewrite it.
        return None

    return _after_model


class TelemetryReflectAndRetryToolPlugin(ReflectAndRetryToolPlugin):
    """ReflectAndRetryToolPlugin with telemetry (see #11 - it shipped with none).

    The base plugin's single choke point for "a tool failed and we are injecting
    reflection guidance for another attempt" is _create_tool_reflection_response
    (both the exception path via on_tool_error_callback and the error-in-result
    path via after_tool_callback reach it through _handle_tool_error). Overriding
    it - call super() first, then emit - captures every real retry exactly once
    without touching the retry/backoff logic or the money path.
    """

    def _create_tool_reflection_response(
        self, tool: Any, tool_args: Any, error: Any, retry_count: int
    ) -> dict[str, Any]:
        response = super()._create_tool_reflection_response(
            tool, tool_args, error, retry_count
        )
        try:
            tool_name = getattr(tool, "name", "unknown")
            error_type = (
                type(error).__name__ if isinstance(error, Exception) else "ToolError"
            )
            # A short guidance tag, not the whole multi-paragraph reflection body.
            add_span_event(
                "tool.retry",
                tool=tool_name,
                retry_count=retry_count,
                error_type=error_type,
                reflection="reflect_and_retry",
            )
            increment_counter("oja.tool.retry", attributes={"tool": tool_name})
        except Exception as exc:  # telemetry must not break recovery (#11)
            log.debug("telemetry_hooks.tool_retry.failed error=%s", exc)
        return response
