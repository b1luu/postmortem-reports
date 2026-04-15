from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger("postmortem")


def attach_node_status(
    name: str,
    result: dict[str, Any],
    *,
    source: str,
    duration_s: float,
    error: str | None = None,
) -> dict[str, Any]:
    result["node_status"] = {
        name: {
            "source": source,
            "duration_s": round(duration_s, 3),
            "error": error,
        }
    }
    return result


def run_with_status(
    name: str,
    llm_fn: Callable[[], dict[str, Any]],
    fallback_fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run a node's LLM path, falling back on any exception.

    Attributes the duration/source correctly: if llm_fn raises, the fallback is
    run separately and marked `source=fallback`, with the original error captured.
    """
    start = time.perf_counter()
    try:
        result = llm_fn()
        duration = time.perf_counter() - start
        logger.info(
            "node_completed name=%s source=llm duration_s=%.3f", name, duration
        )
        return attach_node_status(
            name, result, source="llm", duration_s=duration, error=None
        )
    except Exception as exc:
        duration = time.perf_counter() - start
        err = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "node_fallback name=%s duration_s=%.3f error=%s", name, duration, err
        )
        result = fallback_fn()
        return attach_node_status(
            name, result, source="fallback", duration_s=duration, error=err
        )


def timed_node(name: str, fn: Callable[[], T]) -> T:
    """Legacy helper — prefer run_with_status for nodes with a fallback path."""
    start = time.perf_counter()
    try:
        result = fn()
    except Exception:
        logger.exception(
            "node_failed name=%s duration_s=%.3f",
            name,
            time.perf_counter() - start,
        )
        raise
    logger.info(
        "node_completed name=%s duration_s=%.3f",
        name,
        time.perf_counter() - start,
    )
    return result
