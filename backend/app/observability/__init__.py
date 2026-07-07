"""Observability — Langfuse tracing for the model gateway.

Keys are read from the environment (``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` /
``LANGFUSE_HOST``, with ``SUPERCLAIMS_LANGFUSE_*`` fallbacks layered in by the env loader).

Langfuse v4 is OpenTelemetry-based (the legacy LiteLLM ``"langfuse"`` success-callback is NOT
compatible with langfuse>=3 — it reads ``langfuse.version`` which no longer exists and crashes
every call). So instead of registering that callback we initialize the langfuse v4 client and
expose ``trace_call``: a context manager that opens a Langfuse generation span around each
gateway call and records the model, usage, cost, and latency. ``enable_langfuse()`` is
idempotent and a no-op when keys are absent.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_ENABLED = False
_CLIENT: Any | None = None


def langfuse_configured() -> bool:
    pub = os.environ.get("LANGFUSE_PUBLIC_KEY") or os.environ.get("SUPERCLAIMS_LANGFUSE_PUBLIC_KEY")
    sec = os.environ.get("LANGFUSE_SECRET_KEY") or os.environ.get("SUPERCLAIMS_LANGFUSE_SECRET_KEY")
    return bool(pub and sec)


def enable_langfuse() -> bool:
    """Initialize the Langfuse v4 client (OTEL tracer). Idempotent; no-op without keys."""
    global _ENABLED, _CLIENT
    if _ENABLED:
        return True
    if not langfuse_configured():
        logger.info("Langfuse keys absent; tracing disabled.")
        return False

    # Normalize the SUPERCLAIMS_* fallbacks into the names the Langfuse SDK expects.
    for canonical, fallback in (
        ("LANGFUSE_PUBLIC_KEY", "SUPERCLAIMS_LANGFUSE_PUBLIC_KEY"),
        ("LANGFUSE_SECRET_KEY", "SUPERCLAIMS_LANGFUSE_SECRET_KEY"),
        ("LANGFUSE_HOST", "SUPERCLAIMS_LANGFUSE_HOST"),
    ):
        if not os.environ.get(canonical) and os.environ.get(fallback):
            os.environ[canonical] = os.environ[fallback]

    try:
        from langfuse import get_client

        _CLIENT = get_client()
        _ENABLED = True
        logger.info("Langfuse v4 tracing enabled (host=%s).", os.environ.get("LANGFUSE_HOST"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to enable Langfuse: %s", exc.__class__.__name__)
        return False


@contextlib.contextmanager
def trace_call(name: str, *, model: str, metadata: dict[str, Any] | None = None) -> Iterator[Any]:
    """Open a Langfuse generation span around a model call (no-op when tracing is disabled)."""
    if not _ENABLED or _CLIENT is None:
        yield None
        return
    try:
        with _CLIENT.start_as_current_observation(
            name=name, as_type="generation", model=model, metadata=metadata or {}
        ) as span:
            yield span
    except Exception as exc:  # noqa: BLE001 — tracing must never break a model call
        logger.debug("Langfuse span failed (%s); continuing untraced.", exc.__class__.__name__)
        yield None


def flush() -> None:
    """Flush buffered traces (call at the end of a run)."""
    if _ENABLED and _CLIENT is not None:
        with contextlib.suppress(Exception):
            _CLIENT.flush()


__all__ = ["enable_langfuse", "langfuse_configured", "trace_call", "flush"]
