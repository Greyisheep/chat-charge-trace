"""Observability seam. This is the module the workshop fills in.

Both functions are deliberate no-ops. During the workshop we replace `traced`
with a real OpenTelemetry span context manager and `register_secret` with a
redaction registry so keys and tokens can never leak into a span or a log.
Every call site in this codebase already goes through this seam, so wiring in
OpenTelemetry touches only this file.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def traced(name: str, **attributes: Any) -> Iterator[None]:
    """No-op span. The workshop swaps this for tracer.start_as_current_span."""
    yield


def register_secret(value: str | None) -> None:
    """No-op secret registration. The workshop swaps this for log redaction."""
    return None
