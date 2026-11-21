"""Root cause must be chosen in time order, not input order."""

from app.graph import build_graph
from app.nodes.timeline import timeline_node

# Merged multi-source logs: the downstream 503 is listed before the pool error.
OUT_OF_ORDER = """2026-04-14T10:05:00Z [api-gateway] 503 upstream checkout-svc unavailable
2026-04-14T10:01:04Z [checkout-svc] ERROR db pool exhausted
2026-04-14T10:03:11Z [pagerduty] alert fired
2026-04-14T10:12:45Z [checkout-svc] rollback complete"""


def test_root_cause_uses_earliest_error_not_first_line():
    out = build_graph().invoke({"raw_input": OUT_OF_ORDER})
    first_line = out["root_cause"].splitlines()[0]
    assert "pool exhausted" in first_line
    assert "2026-04-14T10:01:04Z" in first_line
    # Root cause and timeline agree on when the incident started.
    assert out["inflection_points"]["started"] == "2026-04-14T10:01:04Z"
    assert out["root_cause_evidence"][0]["timestamp"] == "2026-04-14T10:01:04Z"


def test_timeline_sorts_mixed_utc_offsets_chronologically():
    # 10:30+02:00 is 08:30Z, so it comes first even though it sorts last as text.
    state = {
        "incident": {
            "events": [
                {"timestamp": "2026-04-14T09:00:00Z", "event": "b"},
                {"timestamp": "2026-04-14T10:30:00+02:00", "event": "a"},
                {"timestamp": "zzz-not-a-time", "event": "c"},
                {"timestamp": "aaa-not-a-time", "event": "d"},
            ]
        }
    }
    order = [e["event"] for e in timeline_node(state)["ordered_timeline"]]
    # Unparseable timestamps keep input order rather than sorting as text.
    assert order == ["a", "b", "c", "d"]
