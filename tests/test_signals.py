import pytest

from app.signals import Signal, affected_services, classify, latest_change_before

C, P, E, D, R, M = (
    Signal.CHANGE,
    Signal.PRECURSOR,
    Signal.ERROR,
    Signal.DETECTION,
    Signal.RESOLUTION,
    Signal.MITIGATION,
)

ROWS = [
    ("alert fired for checkout error rate", {D}),
    ("errors back to normal, recovered", {R}),
    ("rolling back to v411", {M}),
    ("ERROR stack trace attached", {E}),
    ("homepage served from cache", set()),
    ("WARN consumer lag 50000 and growing", {P}),
    ("p99 1500ms", set()),
    ("HTTP 503 from upstream", {E}),
    ("issue unresolved, still failing", {E}),
    ("not recovered yet", set()),
    ("partially recovered, still failing", {E}),
    ("recovered; errors still elevated", {E}),
    ("recovered, latency still elevated", {P}),
    ("no errors in 10m", set()),
    ("0 errors in last 10m", set()),
    ("failover complete", {M}),
    ("rolled back deploy v412", {M}),
    ("jittered cache refill deployed", {C}),
    ("config pushed to prod", {C}),
    ("connection pool released", set()),
    ("released v2.3.1", {C}),
    ("rollback complete", {M, R}),
    ("ERROR tls: certificate has expired", {E}),
    ("alert resolved", {R}),
]


@pytest.mark.parametrize("text,expected", ROWS, ids=[r[0] for r in ROWS])
def test_classify(text, expected):
    assert classify(text) == frozenset(expected)


def test_signal_str_is_value():
    assert str(Signal.ERROR) == "error"


def _events(change_ts: str, started_ts: str = "2026-04-14T10:30:00Z"):
    return [
        {"id": "e0", "timestamp": change_ts, "event": "deploy v412 started"},
        {"id": "e1", "timestamp": started_ts, "event": "ERROR db pool exhausted"},
    ]


def test_latest_change_before_window():
    assert latest_change_before(_events("2026-04-14T09:59:00Z"), "e1") is None  # 31m
    assert latest_change_before(_events("2026-04-14T10:01:00Z"), "e1")["id"] == "e0"  # 29m
    assert latest_change_before(_events("2026-04-14T10:30:00Z"), "e1")["id"] == "e0"  # same ts


def test_latest_change_before_picks_latest_and_skips_started():
    events = [
        {"id": "e0", "timestamp": "2026-04-14T10:00:00Z", "event": "deploy v1"},
        {"id": "e1", "timestamp": "2026-04-14T10:10:00Z", "event": "deploy v2"},
        {"id": "e2", "timestamp": "2026-04-14T10:20:00Z", "event": "deploy v3 failed"},
    ]
    # e2 is itself a CHANGE (and the started event); it is never returned.
    assert latest_change_before(events, "e2")["id"] == "e1"


def test_latest_change_before_tie_goes_to_later_position():
    events = [
        {"id": "e0", "timestamp": "2026-04-14T10:10:00Z", "event": "deploy api v1"},
        {"id": "e1", "timestamp": "2026-04-14T10:10:00Z", "event": "deploy web v2"},
        {"id": "e2", "timestamp": "2026-04-14T10:20:00Z", "event": "ERROR pool exhausted"},
    ]
    assert latest_change_before(events, "e2")["id"] == "e1"


def test_latest_change_before_needs_a_parseable_started_event():
    assert latest_change_before(_events("2026-04-14T10:01:00Z", "garbage"), "e1") is None
    assert latest_change_before(_events("2026-04-14T10:01:00Z"), "e9") is None
    assert latest_change_before(_events("2026-04-14T10:01:00Z"), None) is None


MONITOR_ROWS = [
    ("alert only", ["alert fired"], []),
    ("alert and alert resolved", ["alert fired", "alert resolved"], []),
    ("alert and incident resolved", ["alert fired", "incident resolved"], []),
    ("alert resolved alone", ["alert resolved"], []),
    ("incident resolved alone", ["incident resolved"], ["mon"]),
    ("detection and error", ["alert fired", "ERROR pool exhausted"], ["mon"]),
    ("alert and recovered", ["alert fired", "recovered"], ["mon"]),
]


@pytest.mark.parametrize("texts,expected", [r[1:] for r in MONITOR_ROWS], ids=[r[0] for r in MONITOR_ROWS])
def test_affected_services_drops_monitoring_sources(texts, expected):
    events = [{"source": "mon", "event": text} for text in texts]
    assert affected_services(["mon"], events) == expected


def test_affected_services_keeps_source_with_no_events():
    assert affected_services(["quiet"], [{"source": "other", "event": "alert fired"}]) == ["quiet"]


def test_affected_services_preserves_order():
    events = [
        {"source": "pagerduty", "event": "alert fired"},
        {"source": "b", "event": "ERROR x"},
        {"source": "a", "event": "ERROR y"},
    ]
    assert affected_services(["b", "pagerduty", "a"], events) == ["b", "a"]
