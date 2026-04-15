import time
from datetime import datetime

from app.runtime import attach_node_status
from app.state import PostmortemState

_DETECT_KEYWORDS = ("alert", "page", "detected", "pagerduty", "ack")
_RESOLVE_KEYWORDS = (
    "resolved",
    "recovered",
    "rollback complete",
    "mitigated",
    "back to normal",
    "normal login rate resumed",
    "errors back to normal",
    "queue drained",
)
_ERROR_KEYWORDS = ("error", "fail", "exhaust", "timeout", "unavailable", "503", "500")


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_delta(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours, rem = divmod(seconds, 3600)
    return f"{hours}h {rem // 60}m"


def _compute_durations(points: dict[str, str]) -> dict[str, str | float | None]:
    started = _parse_ts(points.get("started", ""))
    detected = _parse_ts(points.get("detected", ""))
    resolved = _parse_ts(points.get("resolved", ""))

    def delta(a, b):
        if not a or not b:
            return None
        return max(0.0, (b - a).total_seconds())

    mttd = delta(started, detected)
    mttr = delta(detected, resolved)
    total = delta(started, resolved)
    return {
        "mttd_seconds": mttd,
        "mttr_seconds": mttr,
        "total_seconds": total,
        "mttd_human": _format_delta(mttd) if mttd is not None else None,
        "mttr_human": _format_delta(mttr) if mttr is not None else None,
        "total_human": _format_delta(total) if total is not None else None,
    }


def timeline_node(state: PostmortemState) -> PostmortemState:
    events = list(state.get("incident", {}).get("events", []))
    events.sort(key=lambda e: str(e.get("timestamp", "")))

    def _heuristic_inflection() -> dict[str, str]:
        if not events:
            return {"started": "", "detected": "", "resolved": ""}

        started = ""
        detected = ""
        resolved = ""

        for ev in events:
            text = str(ev.get("event", "")).lower()
            ts = str(ev.get("timestamp", ""))
            if not started and any(k in text for k in _ERROR_KEYWORDS):
                started = ts
            if not detected and any(k in text for k in _DETECT_KEYWORDS):
                detected = ts
            if any(k in text for k in _RESOLVE_KEYWORDS):
                resolved = ts

        if not started:
            started = str(events[0].get("timestamp", ""))
        if not detected:
            detected = started
        if not resolved:
            resolved = str(events[-1].get("timestamp", ""))
        return {"started": started, "detected": detected, "resolved": resolved}

    start = time.perf_counter()
    inflection = _heuristic_inflection()
    durations = _compute_durations(inflection)
    return attach_node_status(
        "timeline",
        {
            "ordered_timeline": events,
            "inflection_points": inflection,
            "durations": durations,
        },
        source="heuristic",
        duration_s=time.perf_counter() - start,
    )
