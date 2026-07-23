"""Native Gemini Live voice endpoint (WebSocket), isolated from the SSE path.

This is the additive second door for issue #6. The shipped text path is
ag-ui-adk (SSE, text only) at POST /v1/agents/stream/ and is untouched here.
This module adds a parallel WebSocket at /v1/agents/live that drives ADK's
`Runner.run_live` (the Gemini Live API, real-time audio-to-audio) with the SAME
shop agent, the SAME tools, and the SAME shared session service, so a spoken
conversation still fires tools, renders product cards, and opens the Monnify
payment popup.

Wire protocol (the frontend agent matches this):

  Client -> server (JSON text frames, or raw binary as a shortcut):
    {"type": "start", "threadId": "..."}   begin (also accepted as a ?threadId= query param)
    {"type": "audio", "data": "<b64 16kHz mono PCM>"}   mic chunk
    {"type": "text",  "text": "..."}                    optional typed turn
    {"type": "stop"}                                     end the turn / close
    <binary frame>                                       raw 16kHz mono PCM (same as an audio frame)

  Server -> client (JSON text frames):
    {"type": "ready"}                                              handshake done
    {"type": "audio", "data": "<b64 24kHz PCM>"}                  output audio chunk
    {"type": "transcript", "role": "user"|"assistant",
        "text": "...", "final": bool}                             input/output transcription
    {"type": "state", "payment_event": {...}}                     lifted tool result -> open Monnify popup
    {"type": "ui", "components": [ {...}, ... ]}                  lifted tool result -> render cards
    {"type": "turn_complete"}                                     model finished a turn
    {"type": "error", "message": "..."}                          fatal; socket then closes

The two public keys (payment_event, ui_components) are lifted off the live event
stream with the SAME helper the SSE transform uses (app.agent.agui), so both
channels emit identical shapes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.artifacts import InMemoryArtifactService
from google.adk.runners import Runner
from google.genai import types

from app.agent.adk_app import APP_NAME, build_adk_app
from app.agent.agui import lift_public_payload
from app.agent.shop_agent import create_shop_agent
from app.config import get_settings
from app.telemetry import traced

log = logging.getLogger("live")

# The user id the live sessions live under. Kept distinct from any SSE user so
# the two paths never collide on a shared session row; the threadId is still
# the session id, mirroring the SSE path's use_thread_id_as_session_id.
LIVE_USER_ID = "voice"

# Public state keys mirrored from the SSE transform, in case a tool ever writes
# them into state_delta rather than returning them in its result dict.
PUBLIC_STATE_KEYS = ("payment_event", "ui_components")


@lru_cache(maxsize=1)
def _live_runner_app() -> Any:
    """Build the live ADK App once (same agent + tools as SSE, live model).

    Cached so the App and its plugin stack are assembled a single time and
    reused across every voice connection. The only difference from the SSE App
    is the model: run_live needs a Gemini Live audio model.
    """
    settings = get_settings()
    agent = create_shop_agent(model=settings.gemini_live_model)
    return build_adk_app(agent)


@lru_cache(maxsize=1)
def _artifact_service() -> Any:
    """One in-memory artifact service for the live path (audio is inline, so
    this is only a safety net for run_live's artifact seam)."""
    return InMemoryArtifactService()


def log_live_config() -> None:
    """Log the live model at startup so a wrong id is easy to spot and swap.

    Called from the main.py lifespan. Kept separate from route registration so
    the WebSocket route itself is registered at import time (it resolves the
    shared session service per-connection from app.state)."""
    log.info(
        "live voice endpoint ready: GEMINI_LIVE_MODEL=%s (env-configurable)",
        get_settings().gemini_live_model,
    )


router = APIRouter()


@router.websocket("/v1/agents/live")
async def agents_live(
    websocket: WebSocket,
    threadId: str | None = Query(default=None),
) -> None:
    # Complete the WebSocket handshake first. Everything below (receive/send)
    # requires an accepted socket; without this the opening handshake never
    # finishes and clients time out.
    await websocket.accept()

    # Share the exact session service the lifespan built (same durable Postgres
    # sessions the SSE path uses); resolved per-connection so the route can be
    # registered at import time without the service existing yet.
    session_service = getattr(websocket.app.state, "session_service", None)
    if session_service is None:
        await _safe_send(
            websocket,
            {"type": "error", "message": "voice service not ready"},
        )
        await websocket.close(code=1011)
        return

    runner = Runner(
        app=_live_runner_app(),
        session_service=session_service,
        artifact_service=_artifact_service(),
    )

    # The threadId can arrive as a query param or in the first start frame.
    thread_id = threadId
    try:
        if thread_id is None:
            thread_id = await _await_start(websocket)
    except WebSocketDisconnect:
        return
    if not thread_id:
        await _safe_send(websocket, {"type": "error", "message": "missing threadId"})
        await websocket.close(code=1008)
        return

    # run_live requires the session to already exist (its internal
    # get-or-create raises if missing), so ensure it here, keyed by threadId
    # exactly like the SSE path keys sessions. Durable in the shared Postgres.
    try:
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=LIVE_USER_ID, session_id=thread_id
        )
        if session is None:
            await session_service.create_session(
                app_name=APP_NAME, user_id=LIVE_USER_ID, session_id=thread_id
            )
    except Exception as exc:
        log.exception("live.session_setup_failed thread_id=%s error=%s", thread_id, exc)
        await _safe_send(
            websocket, {"type": "error", "message": _client_error(exc)}
        )
        await _safe_close(websocket)
        return

    live_request_queue = LiveRequestQueue()
    run_config = RunConfig(
        response_modalities=[types.Modality.AUDIO],
        # Transcription default-on gives us both sides as text events; set
        # explicitly so the intent is obvious and stable across adk versions.
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    await _safe_send(websocket, {"type": "ready"})

    async def forward_events() -> None:
        """Consume the run_live event stream and fan it out to the client."""
        async for event in runner.run_live(
            user_id=LIVE_USER_ID,
            session_id=thread_id,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
            await _forward_event(websocket, event)

    async def process_messages() -> None:
        """Pump client frames into the live queue until stop/disconnect."""
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            if not await _handle_client_frame(message, live_request_queue):
                return  # a stop frame

    with traced("live.session", thread_id=thread_id):
        tasks = [
            asyncio.create_task(forward_events()),
            asyncio.create_task(process_messages()),
        ]
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION
        )
        try:
            for task in done:
                task.result()
        except WebSocketDisconnect:
            log.info("live.disconnect thread_id=%s", thread_id)
        except Exception as exc:  # never crash the server on a live failure
            log.exception("live.error thread_id=%s error=%s", thread_id, exc)
            await _safe_send(
                websocket,
                {"type": "error", "message": _client_error(exc)},
            )
        finally:
            for task in pending:
                task.cancel()
            live_request_queue.close()
            await _safe_close(websocket)


async def _await_start(websocket: WebSocket) -> str | None:
    """Block until the client sends {"type":"start", ...}; return its threadId."""
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        frame = _decode_text_frame(message)
        if isinstance(frame, dict) and frame.get("type") == "start":
            tid = frame.get("threadId")
            return tid if isinstance(tid, str) and tid else None


async def _handle_client_frame(
    message: dict[str, Any], queue: LiveRequestQueue
) -> bool:
    """Route one inbound frame into the live queue.

    Returns False on a stop frame (caller should end), True otherwise. Binary
    frames are treated as raw 16kHz mono PCM. Malformed frames are ignored.
    """
    # Binary frame: raw PCM straight to realtime.
    raw = message.get("bytes")
    if raw is not None:
        queue.send_realtime(blob=types.Blob(data=raw, mime_type="audio/pcm"))
        return True

    frame = _decode_text_frame(message)
    if not isinstance(frame, dict):
        return True
    ftype = frame.get("type")

    if ftype == "audio":
        data = frame.get("data")
        if isinstance(data, str) and data:
            try:
                pcm = base64.b64decode(data)
            except (ValueError, TypeError):
                return True
            queue.send_realtime(blob=types.Blob(data=pcm, mime_type="audio/pcm"))
        return True

    if ftype == "text":
        text = frame.get("text")
        if isinstance(text, str) and text:
            queue.send_content(
                types.Content(role="user", parts=[types.Part(text=text)])
            )
        return True

    if ftype == "stop":
        queue.close()
        return False

    # start (a late/duplicate one) and unknown types are no-ops.
    return True


async def _forward_event(websocket: WebSocket, event: Any) -> None:
    """Translate one ADK live Event into zero or more client frames."""
    content = getattr(event, "content", None)

    # Output audio: model audio rides as inline_data blobs (24kHz PCM).
    if content is not None and getattr(content, "parts", None):
        for part in content.parts:
            blob = getattr(part, "inline_data", None)
            if (
                blob is not None
                and getattr(blob, "mime_type", "")
                and blob.mime_type.startswith("audio/")
                and blob.data
            ):
                await _safe_send(
                    websocket,
                    {
                        "type": "audio",
                        "data": base64.b64encode(blob.data).decode("ascii"),
                    },
                )

    # Transcription of the user's speech and of the model's speech.
    await _forward_transcript(websocket, getattr(event, "input_transcription", None), "user")
    await _forward_transcript(
        websocket, getattr(event, "output_transcription", None), "assistant"
    )

    # Tool-driven public state: lift payment_event / ui_components off any tool
    # response on this event, using the SAME helper as the SSE transform.
    payment_event: dict[str, Any] | None = None
    ui_components: list[dict[str, Any]] = []
    for fr in _function_responses(event):
        ev_payment, ev_ui = lift_public_payload(getattr(fr, "response", None))
        if ev_payment is not None:
            payment_event = ev_payment
        if ev_ui:
            ui_components.extend(ev_ui)

    # Belt and suspenders: a tool that instead wrote a public key into
    # state_delta should still surface on the voice channel.
    state_delta = _state_delta(event)
    if isinstance(state_delta, dict):
        if state_delta.get("payment_event"):
            payment_event = state_delta["payment_event"]
        if isinstance(state_delta.get("ui_components"), list):
            ui_components.extend(state_delta["ui_components"])

    if ui_components:
        await _safe_send(websocket, {"type": "ui", "components": ui_components})
    if payment_event is not None:
        await _safe_send(
            websocket, {"type": "state", "payment_event": payment_event}
        )

    if getattr(event, "turn_complete", None):
        await _safe_send(websocket, {"type": "turn_complete"})


async def _forward_transcript(
    websocket: WebSocket, transcription: Any, role: str
) -> None:
    if transcription is None:
        return
    text = getattr(transcription, "text", None)
    if not text:
        return
    await _safe_send(
        websocket,
        {
            "type": "transcript",
            "role": role,
            "text": text,
            "final": bool(getattr(transcription, "finished", False)),
        },
    )


def _function_responses(event: Any) -> list[Any]:
    getter = getattr(event, "get_function_responses", None)
    if callable(getter):
        try:
            return getter() or []
        except Exception:  # never let a malformed event kill the stream
            return []
    return []


def _state_delta(event: Any) -> dict[str, Any] | None:
    actions = getattr(event, "actions", None)
    delta = getattr(actions, "state_delta", None) if actions is not None else None
    return delta if isinstance(delta, dict) else None


def _decode_text_frame(message: dict[str, Any]) -> Any:
    text = message.get("text")
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _client_error(exc: Exception) -> str:
    """A short, non-leaky message for the client."""
    return (
        "Voice service hit a snag. Falling back to text is safe; nothing was "
        "charged."
    )


async def _safe_send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except (WebSocketDisconnect, RuntimeError):
        # Client already gone; forwarding is a no-op from here.
        pass


async def _safe_close(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except (WebSocketDisconnect, RuntimeError):
        pass


if __name__ == "__main__":
    # Guarded structural smoke: build the live App, the RunConfig, and the
    # LiveRequestQueue and push one PCM blob, all WITHOUT opening a model
    # connection. Proves the run_live wiring assembles for the installed adk.
    #   python -m api.live_router
    _app = _live_runner_app()
    _cfg = RunConfig(
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    _q = LiveRequestQueue()
    _q.send_realtime(blob=types.Blob(data=b"\x00\xff", mime_type="audio/pcm"))
    _q.send_content(types.Content(role="user", parts=[types.Part(text="hi")]))
    _q.close()
    print(
        "live_router smoke ok:",
        {
            "app": _app.name,
            "live_model": get_settings().gemini_live_model,
            "response_modalities": [m for m in _cfg.response_modalities],
            "input_transcription": _cfg.input_audio_transcription is not None,
            "output_transcription": _cfg.output_audio_transcription is not None,
        },
    )
