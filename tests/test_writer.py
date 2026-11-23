from app.nodes import writer as writer_mod
from app.nodes.parser import input_parser_node
from app.nodes.timeline import timeline_node
from app.nodes.writer import _fallback_report, writer_node
from tests.fakes import FakeStructuredModel


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


def test_monitoring_source_is_not_a_service_affected():
    state = _state(
        "2026-04-14T10:00:00Z [svc-a] ERROR db pool exhausted\n"
        "2026-04-14T10:01:00Z [svc-b] 503 upstream unavailable\n"
        "2026-04-14T10:02:00Z [pagerduty] alert fired"
    )
    report = _fallback_report(state)
    assert "- **Services affected:** svc-a, svc-b\n" in report
    assert "pagerduty" in state["incident"]["services"]


def _section(report: str, heading: str) -> str:
    after = report.split(heading, 1)[1]
    return after.split("\n## ", 1)[0]


def test_resolved_incident_renders_summary_window_and_total_duration():
    state = _state(
        "2026-04-14T10:00:00Z [svc-a] ERROR db pool exhausted\n"
        "2026-04-14T10:02:00Z [pd] alert fired\n"
        "2026-04-14T10:10:00Z [svc-a] recovered"
    )
    report = _fallback_report(state)
    summary = _section(report, "## Summary")
    impact = _section(report, "## Impact")

    assert (
        "3 timeline events were observed between 2026-04-14T10:00:00Z and 2026-04-14T10:10:00Z."
        in summary
    )
    assert "Total incident duration: **10m 0s**." in summary
    assert "- **Incident duration:** 10m 0s" in impact


def test_unresolved_incident_omits_window_and_total_duration():
    state = _state(
        "2026-04-14T10:00:00Z [svc-a] ERROR db pool exhausted\n"
        "2026-04-14T10:02:00Z [pd] alert fired"
    )
    report = _fallback_report(state)
    summary = _section(report, "## Summary")
    impact = _section(report, "## Impact")

    assert "2 timeline events were observed." in summary
    assert "between " not in summary
    assert "Total incident duration" not in summary
    assert "Incident duration" not in impact


def test_fallback_report_uses_incident_events_when_ordered_timeline_is_absent():
    state = {
        "incident": {
            "severity": "sev2",
            "services": ["checkout"],
            "events": [
                {
                    "id": "e0",
                    "timestamp": "2026-04-14T10:00:00Z",
                    "source": "checkout",
                    "event": "ERROR upstream 503",
                    "signals": ["error"],
                }
            ],
        }
    }
    report = _fallback_report(state)
    assert "- `2026-04-14T10:00:00Z` *checkout* — ERROR upstream 503" in report


def test_non_error_resource_log_and_single_service_do_not_trigger_extra_actions():
    state = _state(
        "2026-04-14T10:00:00Z [svc-a] INFO connection pool initialized\n"
        "2026-04-14T10:01:00Z [svc-a] ERROR upstream 503\n"
        "2026-04-14T10:01:00Z [pd] alert fired"
    )
    actions = _section(_fallback_report(state), "## Action Items")

    assert "connection pool / resource limits" not in actions
    assert "cross-service dependencies" not in actions
    assert "Close detection gap" not in actions


def test_one_second_detection_gap_adds_detection_gap_action_but_missing_detection_does_not():
    one_sec = _state(
        "2026-04-14T10:00:00Z [svc-a] ERROR upstream 503\n" "2026-04-14T10:00:01Z [pd] alert fired"
    )
    assert "Close detection gap" in _section(_fallback_report(one_sec), "## Action Items")

    no_detect = _state("2026-04-14T10:00:00Z [svc-a] ERROR upstream 503")
    assert "Close detection gap" not in _section(_fallback_report(no_detect), "## Action Items")


def test_root_cause_evidence_block_renders_only_when_evidence_is_present():
    base = _state("2026-04-14T10:00:00Z [svc-a] ERROR upstream 503")
    base["root_cause"] = "Upstream failure."

    without_evidence = _fallback_report({**base, "root_cause_evidence": None})
    assert "Supporting evidence" not in without_evidence

    with_evidence = _fallback_report(
        {
            **base,
            "root_cause_confidence": "medium",
            "root_cause_evidence": [
                {
                    "timestamp": "2026-04-14T10:00:00Z",
                    "source": "svc-a",
                    "event": "ERROR upstream 503",
                }
            ],
        }
    )
    root_cause_sec = _section(with_evidence, "## Root Cause")
    assert "**Supporting evidence (1 events, confidence: medium):**" in root_cause_sec
    assert "- `2026-04-14T10:00:00Z` *svc-a* — ERROR upstream 503" in root_cause_sec


def test_llm_writer_rejects_non_empty_output_without_summary_and_uses_incident_events():
    fake = FakeStructuredModel(text_responses=["Just prose with no required headings."])
    config = {"configurable": {"mode": "llm", "llm_factory": lambda **_: fake}}
    state = {
        "incident": {
            "severity": "sev2",
            "services": ["checkout"],
            "events": [
                {
                    "id": "e0",
                    "timestamp": "2026-04-14T10:00:00Z",
                    "source": "checkout",
                    "event": "ERROR upstream 503",
                    "signals": ["error"],
                }
            ],
        }
    }

    out = writer_node(state, config=config)

    assert len(fake.calls) == 1
    assert "checkout" in fake.calls[0]["input"]
    assert out["node_status"]["write"]["source"] == "fallback"
    assert "missing required sections" in out["node_status"]["write"]["error"]
    assert "## Summary" in out["report_markdown"]


def test_heuristic_writer_records_elapsed_duration(monkeypatch):
    state = _state("2026-04-14T10:00:00Z [svc-a] ERROR upstream 503")
    ticks = iter([20.0, 20.05])
    monkeypatch.setattr(writer_mod.time, "perf_counter", lambda: next(ticks))

    out = writer_node(state)

    assert out["node_status"]["write"]["source"] == "heuristic"
    assert out["node_status"]["write"]["duration_s"] == 0.05
