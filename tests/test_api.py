import time

from fastapi.testclient import TestClient

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

    # Runs endpoint lists this run
    runs = client.get("/api/runs").json()
    assert any(r["id"] == report_id for r in runs)
