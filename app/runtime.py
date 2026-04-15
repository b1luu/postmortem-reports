from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger("postmortem")


def timed_node(name: str, fn: Callable[[], T]) -> T:
    start = time.perf_counter()
    try:
        result = fn()
    except Exception:
        logger.exception("node_failed name=%s duration_s=%.3f", name, time.perf_counter() - start)
        raise

    logger.info("node_completed name=%s duration_s=%.3f", name, time.perf_counter() - start)
    return result
