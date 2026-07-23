"""Event-stream transforms for the native AG-UI bridge.

A simplified mirror of dockporter-ai's agui_native_filters. The native
`ADKAgent.run(...)` async generator yields AG-UI events derived from the RAW
ADK session-state diff, which would stream private session keys straight to
the client. `wrap_run_with_transforms` shadows the bound `run` method (no
subclassing, no reimplementation of the SSE endpoint) and applies:

  1. Public-state allow-list on STATE_SNAPSHOT / STATE_DELTA: only the keys
     the frontend is meant to see (payment_event, ui_components) pass.
  2. Tool-result scan: a create_order result carries `payment_event`, and
     list_products / get_product results carry `ui_components` (generative UI
     product cards). Both are lifted into one STATE_DELTA emitted just before
     RUN_FINISHED, so the frontend opens the checkout popup and renders the
     cards after the assistant text has streamed.
"""

from __future__ import annotations

import json
from typing import Any

from ag_ui.core import EventType, StateDeltaEvent

# The only state keys the frontend may see. Everything else is private.
PUBLIC_STATE_KEYS = {"payment_event", "ui_components"}


def _public_path(path: str) -> bool:
    if not isinstance(path, str) or not path.startswith("/"):
        return False
    return path[1:].split("/")[0] in PUBLIC_STATE_KEYS


def public_state_filter(event: Any) -> Any | None:
    """Clamp one AG-UI event to the public-state allow-list.

    Returns the (possibly rewritten) event, or None to drop it entirely.
    Non-state events pass through unchanged.
    """
    event_type = getattr(event, "type", None)

    if event_type == EventType.STATE_SNAPSHOT:
        snapshot = event.snapshot if isinstance(event.snapshot, dict) else {}
        public = {k: v for k, v in snapshot.items() if k in PUBLIC_STATE_KEYS}
        return event.model_copy(update={"snapshot": public})

    if event_type == EventType.STATE_DELTA:
        kept = [
            op
            for op in (event.delta or [])
            if isinstance(op, dict) and _public_path(op.get("path", ""))
        ]
        if not kept:
            return None
        return event.model_copy(update={"delta": kept})

    return event


def _parse_tool_content(content: Any) -> dict[str, Any] | None:
    """Parse a TOOL_CALL_RESULT content (the serialized tool response) to a dict."""
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def wrap_run_with_transforms(agent: Any) -> None:
    """Wrap an ADKAgent instance's `run` with the AG-UI transforms.

    ag-ui-adk's endpoint iterates `agent.run(input)`; shadowing the bound
    method intercepts every event before it is encoded and streamed.
    """
    original_run = agent.run

    async def transformed_run(input_data: Any):
        payment_event: dict[str, Any] | None = None
        ui_components: list[dict[str, Any]] = []
        pending_finish: Any | None = None

        async for event in original_run(input_data):
            if getattr(event, "type", None) == EventType.TOOL_CALL_RESULT:
                parsed = _parse_tool_content(event.content)
                if parsed is not None:
                    if parsed.get("payment_event"):
                        payment_event = parsed["payment_event"]
                    if isinstance(parsed.get("ui_components"), list):
                        ui_components.extend(parsed["ui_components"])

            filtered = public_state_filter(event)
            if filtered is None:
                continue
            if getattr(filtered, "type", None) == EventType.RUN_FINISHED:
                pending_finish = filtered  # hold so the state delta lands first
                continue
            yield filtered

        ops: list[dict[str, Any]] = []
        if ui_components:
            ops.append({"op": "add", "path": "/ui_components", "value": ui_components})
        if payment_event is not None:
            ops.append({"op": "add", "path": "/payment_event", "value": payment_event})
        if ops:
            yield StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)

        if pending_finish is not None:
            yield pending_finish

    agent.run = transformed_run
