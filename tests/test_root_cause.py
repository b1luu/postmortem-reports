import json
from pathlib import Path

from app.graph import build_graph
from app.nodes.root_cause import root_cause_node

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


def test_attaches_evidence_for_error_events():
    state = {
        "incident": {
            "events": [
                {"timestamp": "t1", "event": "INFO healthy", "source": "a"},
                {"timestamp": "t2", "event": "ERROR pool exhausted", "source": "a"},
                {"timestamp": "t3", "event": "503 upstream unavailable", "source": "b"},
            ],
            "error_signals": ["error"],
        }
    }
    out = root_cause_node(state)
    assert "pool" in out["root_cause"].lower()
    assert len(out["root_cause_evidence"]) >= 2
    assert out["root_cause_confidence"] in ("low", "medium", "high")
    # Events without ids (direct call, no parse) give id None.
    assert out["root_cause_evidence"][0]["id"] is None


def test_checkout_evidence_excludes_detection():
    sample = json.loads((SAMPLES_DIR / "checkout_pool_exhaustion.json").read_text())
    out = build_graph().invoke({"raw_input": sample["raw_input"]})
    evidence = out["root_cause_evidence"]
    # e5 is the PagerDuty alert "... for checkout error rate": DETECTION, not evidence.
    assert [e["id"] for e in evidence] == ["e2", "e3", "e4"]
    for item in evidence:
        assert set(item) >= {"id", "signals"}
        assert set(item["signals"]) & {"error", "precursor"}


def test_same_second_change_is_trigger_and_earlier_error_is_not_a_symptom():
    out = build_graph().invoke(
        {
            "raw_input": "2026-04-14T10:00:00Z [a] ERROR pool exhausted\n"
            "2026-04-14T10:00:00Z [b] deploy v2 failed\n"
            "2026-04-14T10:01:00Z [a] ERROR timeout"
        }
    )
    analysis = out["root_cause_analysis"]
    assert analysis["trigger_event_id"] == "e1"
    assert [s["event_id"] for s in analysis["symptoms"]] == ["e2"]
    assert out["root_cause_evidence"][0]["id"] == out["inflection_event_ids"]["started"]


def test_same_second_change_with_no_later_error_has_no_symptoms():
    out = build_graph().invoke(
        {
            "raw_input": "2026-04-14T10:00:00Z [a] ERROR pool exhausted\n"
            "2026-04-14T10:00:00Z [b] deploy v2 rolled out"
        }
    )
    analysis = out["root_cause_analysis"]
    assert analysis["trigger_event_id"] == "e1"
    assert analysis["symptoms"] == []
    assert "First symptom" not in out["root_cause"]
