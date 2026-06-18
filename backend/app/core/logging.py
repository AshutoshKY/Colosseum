"""Lightweight structured logging setup."""

from __future__ import annotations

import logging
import sys
from functools import cache

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """Configure root logging once, idempotently."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    # Imported lazily to avoid a circular import (config -> logging is fine, but keep clean).
    from app.core.config import get_settings

    resolved = (level or get_settings().log_level or "INFO").upper()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved)
    _CONFIGURED = True


@cache
def get_logger(name: str) -> logging.Logger:
    """Return a configured logger."""
    configure_logging()
    return logging.getLogger(name)
