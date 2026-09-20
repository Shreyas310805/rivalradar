"""Structured-ish logging setup shared by the API, CLI and scheduler."""

from __future__ import annotations

import contextlib
import logging
import sys

_CONFIGURED = False

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s"


def configure_console_encoding() -> None:
    """Force UTF-8 on stdout/stderr.

    Windows consoles default to a legacy code page (cp1252), which raises
    ``UnicodeEncodeError`` on the arrows and box-drawing characters used in the
    digest and CLI tables.  Reconfiguring is a no-op on POSIX.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # Detached or unusual streams simply cannot be reconfigured.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging exactly once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    configure_console_encoding()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]

    # Third-party libraries are chatty; keep them at WARNING.
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "apscheduler.executors"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)
