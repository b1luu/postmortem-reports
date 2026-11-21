from app.nodes.parser import input_parser_node
from app.nodes.timeline import timeline_node
from app.nodes.writer import _fallback_report


def _state(raw: str) -> dict:
    state = dict(input_parser_node({"raw_input": raw}))
    state.update(timeline_node(state))
    return state


def _timeline_lines(report: str) -> list[str]:
    block = report.split("## Timeline", 1)[1].split("## Root Cause", 1)[0]
    return [ln for ln in block.splitlines() if ln.startswith("- ")]


def test_markers_follow_event_ids_not_timestamps():
    state = _state(
        "2026-04-14T10:01:04Z [a] INFO cache warmed\n"
        "2026-04-14T10:01:04Z [b] ERROR db pool exhausted\n"
        "2026-04-14T10:03:00Z [pd] alert fired\n"
        "2026-04-14T10:09:00Z [b] recovered"
    )
    lines = _timeline_lines(_fallback_report(state))
    # Same timestamp as the started event, but not the started event.
    assert "[started]" not in lines[0]
    assert lines[1].endswith("**[started]**")
    assert lines[2].endswith("**[detected]**")
    assert lines[3].endswith("**[resolved]**")


def test_no_detection_or_resolution_means_no_mttd_mttr():
    report = _fallback_report(
        _state(
            "2026-04-14T10:01:04Z [b] ERROR db pool exhausted\n"
            "2026-04-14T10:02:00Z [b] ERROR still exhausted"
        )
    )
    assert "MTTD" not in report
    assert "MTTR" not in report
    assert "[detected]" not in report
    assert "[resolved]" not in report


def test_negative_mttd_is_a_timing_caveat():
    report = _fallback_report(
        _state(
            "2026-04-14T10:00:00Z [pd] alert fired\n"
            "2026-04-14T10:05:00Z [b] ERROR db pool exhausted"
        )
    )
    assert (
        "- **Timing caveat:** MTTD omitted: detected (2026-04-14T10:00:00Z) "
        "precedes started (2026-04-14T10:05:00Z)"
    ) in report
    assert "- **MTTD:**" not in report
