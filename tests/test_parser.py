from app.nodes.parser import _heuristic_parse


def test_parses_events_sources_and_severity():
    raw = (
        "2026-04-14T10:00:00Z [svc-a] INFO deploy started\n"
        "2026-04-14T10:01:00Z [svc-a] ERROR db pool exhausted sev2\n"
        "2026-04-14T10:02:00Z [svc-b] 503 upstream unavailable"
    )
    inc = _heuristic_parse(raw)
    assert len(inc["events"]) == 3
    assert "svc-a" in inc["services"] and "svc-b" in inc["services"]
    assert inc["severity"] == "sev2"
    assert any("error" in s for s in inc["error_signals"])


def test_parses_semicolon_joined_line():
    raw = "2026-04-14T10:00:00Z [a] INFO x; 2026-04-14T10:01:00Z [b] ERROR y"
    inc = _heuristic_parse(raw)
    assert len(inc["events"]) == 2
    assert inc["events"][0]["source"] == "a"
    assert inc["events"][1]["source"] == "b"


def test_empty_input_degrades_gracefully():
    inc = _heuristic_parse("nothing useful here")
    assert inc["events"] == []
    assert inc["severity"] == "unknown"
