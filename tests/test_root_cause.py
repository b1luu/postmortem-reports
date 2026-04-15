from app.nodes.root_cause import root_cause_node


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
