import pytest

from app.nodes.parser import NO_EVENTS_MSG, _heuristic_parse, input_parser_node
from app.schemas import ParsedIncident, TimelineEventModel
from tests.fakes import FakeStructuredModel, ForbidLLM

LINE_A = "2026-04-14T10:00:00Z [svc-a] INFO deploy started"
LINE_B = "2026-04-14T10:01:00Z [svc-b] ERROR db pool exhausted"
PROSE = "Checkout went down for a while yesterday afternoon."


def _parse(raw, mode="heuristic", factory=None):
    configurable = {"mode": mode}
    if factory is not None:
        configurable["llm_factory"] = factory
    out = input_parser_node({"raw_input": raw}, {"configurable": configurable})
    return out["incident"], out["node_status"]["parse"]


def _ids(incident):
    return [ev["id"] for ev in incident["events"]]


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


def test_ids_on_text_path():
    inc, status = _parse(f"{LINE_A}\n{LINE_B}")
    assert _ids(inc) == ["e0", "e1"]
    assert status["source"] == "heuristic"


def test_ids_on_dict_path_overwrite_caller_ids():
    raw = {
        "events": [
            {"id": "x9", "timestamp": "2026-04-14T10:00:00Z", "event": "a"},
            {"timestamp": "2026-04-14T10:01:00Z", "event": "b", "source": "svc"},
        ]
    }
    inc, status = _parse(raw)
    assert _ids(inc) == ["e0", "e1"]
    assert inc["services"] == ["svc"]
    assert status["source"] == "input"


def test_list_of_log_lines_needs_no_llm():
    forbid = ForbidLLM()
    inc, status = _parse([LINE_A, LINE_B], mode="llm", factory=forbid)
    assert _ids(inc) == ["e0", "e1"]
    assert forbid.calls == []
    assert status["source"] == "heuristic"
    assert status["error"] is None


def test_mixed_list_keeps_lines_and_dicts():
    raw = [LINE_A, {"timestamp": "2026-04-14T10:02:00Z", "message": "x"}, 42]
    inc, status = _parse(raw)
    assert _ids(inc) == ["e0", "e1"]
    assert inc["events"][1]["event"] == "x"
    assert status["source"] == "heuristic"


def test_malformed_events_are_skipped():
    raw = {"events": ["junk", 42, {"timestamp": 1713088864, "event": "x"}]}
    inc, status = _parse(raw)
    assert len(inc["events"]) == 1
    assert inc["events"][0]["id"] == "e0"
    assert inc["events"][0]["timestamp"] == "1713088864"
    assert status["error"] is None


def test_missing_dict_timestamp_is_empty_not_none_string():
    inc, _ = _parse({"events": [{"timestamp": None, "event": "x"}]})
    assert inc["events"][0]["timestamp"] == ""


def test_dict_input_never_calls_llm():
    forbid = ForbidLLM()
    inc, status = _parse({"severity": "sev1"}, mode="llm", factory=forbid)
    assert inc["events"] == []
    assert inc["severity"] == "sev1"
    assert forbid.calls == []
    assert status["source"] == "input"
    assert status["error"] is None


def test_space_separated_timestamp():
    inc, _ = _parse("2026-04-14 10:01:04 [svc] ERROR db pool exhausted")
    assert inc["events"][0]["timestamp"] == "2026-04-14 10:01:04"
    assert inc["events"][0]["source"] == "svc"


def test_llm_extraction_for_prose_in_llm_mode():
    parsed = ParsedIncident(
        events=[
            TimelineEventModel(timestamp="2026-04-14T10:00:00Z", event="checkout down"),
            TimelineEventModel(timestamp="2026-04-14T10:30:00Z", event="recovered"),
        ],
        services=["checkout"],
        severity="sev2",
    )
    fake = FakeStructuredModel(structured_responses={"ParsedIncident": [parsed]})
    inc, status = _parse(PROSE, mode="llm", factory=lambda **_: fake)
    assert len(fake.calls) == 1
    assert status["source"] == "llm"
    assert status["error"] is None
    assert _ids(inc) == ["e0", "e1"]
    assert inc["severity"] == "sev2"


def test_heuristic_prose_makes_no_llm_call():
    forbid = ForbidLLM()
    inc, status = _parse(PROSE, factory=forbid)
    assert inc["events"] == []
    assert forbid.calls == []
    assert status["source"] == "heuristic"
    assert status["error"] == NO_EVENTS_MSG


@pytest.mark.parametrize("mode", ["heuristic", "llm"])
@pytest.mark.parametrize("raw", ["", [], {}], ids=["str", "list", "dict"])
def test_empty_input_has_no_error_and_no_llm(raw, mode):
    forbid = ForbidLLM()
    inc, status = _parse(raw, mode=mode, factory=forbid)
    assert inc["events"] == []
    assert forbid.calls == []
    assert status["source"] == "heuristic"  # {} has no incident keys
    assert status["error"] is None
