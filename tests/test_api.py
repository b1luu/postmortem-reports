import time
import uuid

from fastapi.testclient import TestClient

from app.db import create_pending_report, init_db, save_report
from app.main import app


def test_full_api_roundtrip():
    with TestClient(app) as client:
        _roundtrip(client)


def _roundtrip(client):
    # Samples endpoint
    samples = client.get("/api/samples").json()
    assert samples, "no samples served"
    sample = samples[0]
    assert "raw_input" in sample

    # Analyze
    resp = client.post("/analyze", json={"raw_input": sample["raw_input"]})
    assert resp.status_code == 202
    report_id = resp.json()["id"]

    # Poll until ready (background task)
    deadline = time.time() + 10
    report = None
    while time.time() < deadline:
        report = client.get(f"/report/{report_id}").json()
        if report["status"] == "ready":
            break
        time.sleep(0.05)
    assert report is not None and report["status"] == "ready", report
    assert report["review_passed"] is True
    assert "## Summary" in report["report_markdown"]
    assert report["durations"].get("mttr_human")
    assert report["inflection_event_ids"]["started"]

    # Runs endpoint lists this run
    runs = client.get("/api/runs").json()
    assert any(r["id"] == report_id for r in runs)


REPORT_KEYS = {
    "id",
    "created_at",
    "status",
    "review_passed",
    "report_markdown",
    "node_status",
    "durations",
    "inflection_points",
    "inflection_event_ids",
    "incident",
    "root_cause_evidence",
    "root_cause_analysis",
    "contributing_factor_details",
    "error",
}


def test_report_reads_legacy_state_row():
    # A row saved before 2a: no ids/signals, no inflection_event_ids, no warnings.
    legacy_state = {
        "report_markdown": "# Incident Postmortem\n## Summary\nold",
        "inflection_points": {
            "started": "2026-04-14T10:01:04Z",
            "detected": "2026-04-14T10:03:11Z",
            "resolved": "2026-04-14T10:13:10Z",
        },
        "durations": {"mttd_seconds": 127.0, "mttd_human": "2m 7s"},
        "incident": {
            "events": [{"timestamp": "2026-04-14T10:01:04Z", "event": "ERROR pool", "source": "a"}]
        },
        "node_status": {"parse": {"source": "heuristic", "duration_s": 0.0, "error": None}},
        "review_passed": True,
    }
    with TestClient(app) as client:
        init_db()
        report_id = uuid.uuid4().hex
        create_pending_report(report_id, "x")
        save_report(report_id, legacy_state)
        current = client.post("/analyze", json={"raw_input": "x"}).json()["id"]

        resp = client.get(f"/report/{report_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == REPORT_KEYS
        assert set(client.get(f"/report/{current}").json()) == REPORT_KEYS
        assert body["inflection_event_ids"] == {}


def test_report_exposes_analysis_fields():
    with TestClient(app) as client:
        init_db()
        legacy_id = uuid.uuid4().hex
        create_pending_report(legacy_id, "x")
        save_report(legacy_id, {"report_markdown": "old", "node_status": {}})
        legacy = client.get(f"/report/{legacy_id}").json()
        assert legacy["root_cause_analysis"] == {}
        assert legacy["contributing_factor_details"] == []

        sample = client.get("/api/samples").json()[0]
        report_id = client.post("/analyze", json={"raw_input": sample["raw_input"]}).json()["id"]
        deadline = time.time() + 10
        report = {}
        while time.time() < deadline:
            report = client.get(f"/report/{report_id}").json()
            if report["status"] == "ready":
                break
            time.sleep(0.05)
        assert report["status"] == "ready", report
        assert report["root_cause_analysis"]["trigger_kind"]
        assert report["contributing_factor_details"]
