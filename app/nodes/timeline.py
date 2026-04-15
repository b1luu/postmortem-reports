import time

from app.runtime import attach_node_status
from app.state import PostmortemState

_DETECT_KEYWORDS = ("alert", "page", "detected", "pagerduty", "ack")
_RESOLVE_KEYWORDS = ("resolved", "normal", "recovered", "rollback complete", "mitigated")
_ERROR_KEYWORDS = ("error", "fail", "exhaust", "timeout", "unavailable", "503", "500")


def timeline_node(state: PostmortemState) -> PostmortemState:
    events = list(state.get("incident", {}).get("events", []))
    events.sort(key=lambda e: str(e.get("timestamp", "")))

    def _heuristic_inflection() -> dict[str, str]:
        if not events:
            return {"started": "", "detected": "", "resolved": ""}

        started = ""
        detected = ""
        resolved = str(events[-1].get("timestamp", ""))

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
        return {"started": started, "detected": detected, "resolved": resolved}

    start = time.perf_counter()
    return attach_node_status(
        "timeline",
        {
            "ordered_timeline": events,
            "inflection_points": _heuristic_inflection(),
        },
        source="heuristic",
        duration_s=time.perf_counter() - start,
    )
