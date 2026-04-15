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
