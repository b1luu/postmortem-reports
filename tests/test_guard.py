from app.graph import build_graph
from app.nodes.guard import (
    NO_EVENTS,
    NO_EVIDENCE,
    REQUIRED_SECTIONS,
    guard_node,
)

COMPLETE_MD = "\n".join(["# Incident Postmortem"] + REQUIRED_SECTIONS)
EVENT = {"id": "e0", "timestamp": "2026-04-14T10:01:04Z", "event": "ERROR pool exhausted"}
SUPPORTED = {
    "incident": {"events": [EVENT]},
    "root_cause_evidence": [EVENT],
}


def test_guard_flags_missing_sections():
    out = guard_node({**SUPPORTED, "report_markdown": "# Incident Postmortem\n## Summary\nnope"})
    assert out["review_passed"] is False
    assert "## Impact" in out["review_issues"]
    assert out["review_blockers"] == []


def test_guard_passes_complete_supported_report():
    out = guard_node({**SUPPORTED, "report_markdown": COMPLETE_MD})
    assert out["review_passed"] is True
    assert out["review_issues"] == []
    assert out["review_blockers"] == []


def test_guard_requires_headers_on_their_own_lines():
    md = "# Incident Postmortem\n## Summary ## Impact\n" + "\n".join(REQUIRED_SECTIONS[2:])
    out = guard_node({**SUPPORTED, "report_markdown": md})
    assert out["review_passed"] is False
    assert out["review_issues"] == ["## Summary", "## Impact"]


def test_guard_reports_node_status():
    out = guard_node({"report_markdown": ""})
    assert out["node_status"]["guard"]["source"] == "heuristic"


def test_complete_report_with_no_events_fails_review():
    out = guard_node({"report_markdown": COMPLETE_MD, "incident": {"events": []}})
    assert out["review_passed"] is False
    assert out["review_blockers"] == [NO_EVENTS]
    assert NO_EVENTS in out["review_issues"]


def test_complete_report_with_no_evidence_fails_review():
    out = guard_node({"report_markdown": COMPLETE_MD, "incident": {"events": [EVENT]}})
    assert out["review_passed"] is False
    assert out["review_blockers"] == [NO_EVIDENCE]


def test_prose_input_fails_review_without_looping():
    prose = (
        "Around 2pm checkout started failing after the deploy. "
        "We rolled back at 2:20 and it recovered."
    )
    out = build_graph().invoke({"raw_input": prose})
    assert out["review_passed"] is False
    assert out["review_blockers"] == [NO_EVENTS]
    # A blocker ends the run: the writer is not called again for nothing.
    assert out["write_attempts"] == 1


def test_info_only_log_fails_review_for_missing_evidence():
    raw = (
        "2026-04-14T10:00:00Z [svc] INFO deploy started\n"
        "2026-04-14T10:05:00Z [svc] INFO deploy finished"
    )
    out = build_graph().invoke({"raw_input": raw})
    assert out["review_passed"] is False
    assert out["review_blockers"] == [NO_EVIDENCE]
    assert out["write_attempts"] == 1
