"""Centralised logger setup for both the API + arq worker processes.

Sprint 9.0.5-B J. The R6 follow-up batch summary (``HybridClassifier
batch | total=… mode=…``) was emitted as ``logger.info(...)`` but
production smoke tests on the api-worker container couldn't find it
in journalctl. Root cause: arq's default logging configuration sets
the root logger to WARNING, so any INFO calls under ``imga_core.*``
(loaded inside the worker process) drop on the floor before they
reach the journal.

This module fixes that by explicitly setting the ``imga_core`` and
``imga_api`` namespace loggers to INFO and attaching a single
StreamHandler with the project's standard format. Idempotent — safe
to call multiple times (the second call no-ops).

Call sites:
  * ``imga_api.main`` — the API container's lifespan startup.
  * ``imga_api.workers.arq_worker.startup`` — the arq worker
    container's per-process startup hook.

Both import this module so a third process (e.g. a one-off
management script) gets the same shape.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_PROJECT_NAMESPACES = ("imga_api", "imga_core", "imga-api")
_CONFIGURED_FLAG = "_imga_logging_configured"


def configure_logging(level: int = logging.INFO) -> None:
    """Set up the project-wide logger surface.

    * Root logger gets a StreamHandler -> stderr at INFO so the
      bootstrap messages (Settings load, SDK import warnings) flow.
    * ``imga_api`` / ``imga_core`` (+ the legacy hyphenated
      ``imga-api`` channel from main.py) are pinned to INFO so the
      HybridClassifier batch summary, the rotator key-usage log,
      and the worker's progress lines reach the journal.
    * Idempotent — checks a sentinel flag on the root logger and
      no-ops if we've already configured it.
    """
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_FLAG, False):
        return

    formatter = logging.Formatter(_FORMAT)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    # Don't double-attach if some other framework (uvicorn, arq)
    # already wired its own handler to root — its handler stays,
    # ours adds the project's preferred format alongside.
    root.setLevel(level)
    root.addHandler(handler)

    for namespace in _PROJECT_NAMESPACES:
        ns_logger = logging.getLogger(namespace)
        ns_logger.setLevel(level)
        # Propagate to root so the StreamHandler picks them up;
        # don't re-attach a per-namespace handler — that would
        # double-print every message.
        ns_logger.propagate = True

    setattr(root, _CONFIGURED_FLAG, True)


__all__ = ["configure_logging"]
