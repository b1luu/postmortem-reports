import time

from langchain_core.runnables import RunnableConfig

from app.runtime import attach_node_status
from app.signals import Signal, classify, signal_values
from app.state import PostmortemState
from app.timeutil import parse_ts


def _sort_key(event: dict) -> tuple:
    """Chronological order; unparseable timestamps go last in input order.

    Sorting the raw strings breaks on mixed UTC offsets
    ("10:05+02:00" is earlier than "09:00Z"). Unparseable keys are all equal,
    so the stable sort keeps them in the order they were logged.
    """
    parsed = parse_ts(event.get("timestamp", ""))
    return (0, parsed) if parsed else (1,)


def _format_delta(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours, rem = divmod(seconds, 3600)
    return f"{hours}h {rem // 60}m"


# (result key prefix, warning label, earlier point, later point)
_DELTAS = (
    ("mttd", "MTTD", "started", "detected"),
    ("mttr", "MTTR", "detected", "resolved"),
    ("total", "Total duration", "started", "resolved"),
)


def _compute_durations(points: dict[str, str | None]) -> dict:
    """Durations between inflection points; None when an end is missing.

    A negative delta means the input contradicts itself (e.g. an alert logged
    before the first error); it is reported as a warning, never clamped to 0.
    """
    result: dict = {}
    warnings: list[str] = []
    for key, label, earlier, later in _DELTAS:
        a = parse_ts(points.get(earlier) or "")
        b = parse_ts(points.get(later) or "")
        seconds = None
        if a and b:
            seconds = (b - a).total_seconds()
            if seconds < 0:
                warnings.append(
                    f"{label} omitted: {later} ({points[later]}) precedes "
                    f"{earlier} ({points[earlier]})"
                )
                seconds = None
        result[f"{key}_seconds"] = seconds
    for key, *_ in _DELTAS:
        seconds = result[f"{key}_seconds"]
        result[f"{key}_human"] = _format_delta(seconds) if seconds is not None else None
    result["warnings"] = warnings
    return result


def timeline_node(state: PostmortemState, config: RunnableConfig | None = None) -> PostmortemState:
    start = time.perf_counter()
    events = [dict(ev) for ev in state.get("incident", {}).get("events", [])]
    events.sort(key=_sort_key)
    for ev in events:
        ev["signals"] = signal_values(classify(str(ev.get("event", ""))))

    def _first(*wanted: Signal) -> dict | None:
        return next((ev for ev in events if set(ev["signals"]) & set(wanted)), None)

    resolutions = [ev for ev in events if Signal.RESOLUTION in ev["signals"]]
    chosen = {
        "started": _first(Signal.ERROR, Signal.PRECURSOR),
        "detected": _first(Signal.DETECTION),
        "resolved": resolutions[-1] if resolutions else None,
    }
    inflection = {k: (ev.get("timestamp") if ev else None) for k, ev in chosen.items()}
    inflection_ids = {k: (ev.get("id") if ev else None) for k, ev in chosen.items()}

    return attach_node_status(
        "timeline",
        {
            "ordered_timeline": events,
            "inflection_points": inflection,
            "inflection_event_ids": inflection_ids,
            "durations": _compute_durations(inflection),
        },
        source="heuristic",
        duration_s=time.perf_counter() - start,
    )
