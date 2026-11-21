from app.nodes.timeline import _compute_durations, _format_delta, timeline_node


def test_format_delta_ranges():
    assert _format_delta(42) == "42s"
    assert _format_delta(125) == "2m 5s"
    assert _format_delta(3725) == "1h 2m"


def test_compute_durations_basic():
    d = _compute_durations(
        {
            "started": "2026-04-14T10:00:00Z",
            "detected": "2026-04-14T10:02:00Z",
            "resolved": "2026-04-14T10:12:00Z",
        }
    )
    assert d["mttd_seconds"] == 120
    assert d["mttr_seconds"] == 600
    assert d["total_seconds"] == 720
    assert d["mttd_human"] == "2m 0s"


def test_timeline_node_identifies_inflection_points():
    state = {
        "incident": {
            "events": [
                {"timestamp": "2026-04-14T10:00:00Z", "event": "deploy started", "source": "a"},
                {"timestamp": "2026-04-14T10:01:00Z", "event": "ERROR pool exhausted", "source": "a"},
                {"timestamp": "2026-04-14T10:03:00Z", "event": "pagerduty alert fired", "source": "pd"},
                {"timestamp": "2026-04-14T10:10:00Z", "event": "rollback complete", "source": "a"},
            ]
        }
    }
    out = timeline_node(state)
    inf = out["inflection_points"]
    assert inf["started"] == "2026-04-14T10:01:00Z"
    assert inf["detected"] == "2026-04-14T10:03:00Z"
    assert inf["resolved"] == "2026-04-14T10:10:00Z"
    assert out["durations"]["mttd_human"] == "2m 0s"
    assert out["durations"]["mttr_human"] == "7m 0s"


def _timeline(lines: list[str]) -> dict:
    events = [
        {"id": f"e{i}", "timestamp": ts, "event": text, "source": "s"}
        for i, (ts, text) in enumerate(line.split(" ", 1) for line in lines)
    ]
    return timeline_node({"incident": {"events": events}})


def test_entries_are_labelled_and_inflections_carry_ids():
    out = _timeline(
        [
            "2026-04-14T10:00:00Z deploy v412 started",
            "2026-04-14T10:01:00Z ERROR db pool exhausted",
            "2026-04-14T10:03:00Z pagerduty alert fired",
            "2026-04-14T10:10:00Z rollback complete",
        ]
    )
    assert [ev["signals"] for ev in out["ordered_timeline"]] == [
        ["change"],
        ["error"],
        ["detection"],
        ["resolution", "mitigation"],
    ]
    assert out["inflection_event_ids"] == {"started": "e1", "detected": "e2", "resolved": "e3"}


def test_unsupported_points_are_none_not_guessed():
    out = _timeline(["2026-04-14T10:01:00Z ERROR db pool exhausted"])
    assert out["inflection_points"] == {
        "started": "2026-04-14T10:01:00Z",
        "detected": None,
        "resolved": None,
    }
    assert out["inflection_event_ids"] == {"started": "e0", "detected": None, "resolved": None}
    assert out["durations"]["mttd_seconds"] is None
    assert out["durations"]["total_seconds"] is None


def test_negative_mttd_is_omitted_with_warning():
    out = _timeline(
        [
            "2026-04-14T10:00:00Z alert fired",
            "2026-04-14T10:05:00Z ERROR db pool exhausted",
        ]
    )
    assert out["durations"]["mttd_seconds"] is None
    assert out["durations"]["warnings"] == [
        "MTTD omitted: detected (2026-04-14T10:00:00Z) precedes started (2026-04-14T10:05:00Z)"
    ]
