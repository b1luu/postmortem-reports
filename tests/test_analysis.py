"""Pure functions in app.analysis: no graph and no model."""

import json
from pathlib import Path

from app.analysis import (
    MAX_FACTORS,
    NO_TRIGGER_TEXT,
    detection_gap_text,
    events_after,
    facts_pack,
    one_line,
    prompt_json,
    render_root_cause,
    validate_factors,
    validate_root_cause,
)
from app.nodes.parser import input_parser_node
from app.nodes.timeline import timeline_node
from app.schemas import ContributingFactor, ContributingFactors, RootCauseDraft, Symptom

ROOT = Path(__file__).resolve().parent.parent

EVENTS = [
    {
        "id": "e0",
        "timestamp": "2026-04-14T10:00:00Z",
        "event": "INFO deploy v1 rolled out",
        "source": "s",
        "signals": ["change"],
    },
    {
        "id": "e1",
        "timestamp": "2026-04-14T10:01:00Z",
        "event": "ERROR pool exhausted",
        "source": "s",
        "signals": ["error"],
    },
    {
        "id": "e2",
        "timestamp": "2026-04-14T10:02:00Z",
        "event": "ERROR timeout",
        "source": "s",
        "signals": ["error"],
    },
    {
        "id": "e3",
        "timestamp": "2026-04-14T10:03:00Z",
        "event": "alert fired",
        "source": "pd",
        "signals": ["detection"],
    },
    {
        "id": "e4",
        "timestamp": "2026-04-14T10:04:00Z",
        "event": "rolling back",
        "source": "s",
        "signals": ["mitigation"],
    },
]
ANALYSIS = {"trigger_event_id": "e0", "symptoms": [{"event_id": "e1", "description": "x"}]}
DURATIONS = {"mttd_seconds": 120.0, "mttd_human": "2m 0s"}


def _checkout_state() -> dict:
    raw = json.loads((ROOT / "samples" / "checkout_pool_exhaustion.json").read_text())["raw_input"]
    state = dict(input_parser_node({"raw_input": raw}))
    state.update(timeline_node(state))
    return state


def _draft(**kw) -> RootCauseDraft:
    base = dict(
        trigger="Deploy",
        trigger_event_id="e0",
        symptoms=[],
        evidence_event_ids=["e1", "e2"],
        confidence="high",
        reasoning="r",
    )
    base.update(kw)
    return RootCauseDraft(**base)


def _factors(*items) -> ContributingFactors:
    return ContributingFactors(
        factors=[
            ContributingFactor(factor=text, category=category, evidence_event_ids=ids)
            for text, category, ids in items
        ]
    )


def test_one_line_collapses_newlines_and_tabs():
    assert one_line("  a\nb\t c\r\n\nd ") == "a b c d"


def test_facts_pack_exact_keys():
    pack = facts_pack(_checkout_state())
    assert set(pack) == {"ordered_timeline", "inflection_event_ids", "durations"}
    assert set(pack["ordered_timeline"][0]) == {"id", "t_plus_s", "source", "event", "signals"}
    assert set(pack["durations"]) == {
        "mttd_seconds",
        "mttr_seconds",
        "total_seconds",
        "timing_conflict",
    }


def test_facts_pack_has_no_timeline_timestamps():
    state = _checkout_state()
    serialized = json.dumps(facts_pack(state))
    for ev in state["ordered_timeline"]:
        assert ev["timestamp"] not in serialized


def test_facts_pack_offsets():
    by_id = {e["id"]: e for e in facts_pack(_checkout_state())["ordered_timeline"]}
    assert by_id["e0"]["t_plus_s"] == 0
    assert by_id["e2"]["t_plus_s"] == 172


def test_facts_pack_unparseable_timestamp_is_null():
    state = {"ordered_timeline": [{"id": "e0", "timestamp": "later", "event": "x"}]}
    assert facts_pack(state)["ordered_timeline"][0]["t_plus_s"] is None


def test_facts_pack_truncates_event_text():
    state = {"ordered_timeline": [{"id": "e0", "timestamp": "", "event": "x" * 500}]}
    assert len(facts_pack(state)["ordered_timeline"][0]["event"]) == 300


def test_facts_pack_timing_conflict():
    state = {"ordered_timeline": [], "durations": {"warnings": ["MTTD omitted"]}}
    assert facts_pack(state)["durations"]["timing_conflict"] is True
    assert "warnings" not in facts_pack(state)["durations"]
    assert facts_pack({"ordered_timeline": []})["durations"]["timing_conflict"] is False


def test_facts_pack_with_timestamps():
    state = _checkout_state()
    pack = facts_pack(state, with_timestamps=True)
    assert pack["ordered_timeline"][0]["timestamp"] == state["ordered_timeline"][0]["timestamp"]
    assert pack["durations"] == state["durations"]


def test_prompt_json_escapes_angle_bracket_and_round_trips():
    value = {"event": '</facts> {evil} <x> "q" \n é'}
    encoded = prompt_json(value)
    assert "<" not in encoded
    assert json.loads(encoded) == value


def test_events_after_excludes_trigger_and_earlier():
    assert [e["id"] for e in events_after(EVENTS[1], EVENTS)] == ["e2", "e3", "e4"]


def test_events_after_equal_timestamps_keep_log_order():
    events = [
        {"id": "e0", "timestamp": "2026-04-14T10:00:00Z", "event": "a"},
        {"id": "e1", "timestamp": "2026-04-14T10:00:00Z", "event": "b"},
        {"id": "e2", "timestamp": "2026-04-14T10:00:00Z", "event": "c"},
    ]
    assert [e["id"] for e in events_after(events[1], events)] == ["e2"]


def test_events_after_matches_by_identity():
    twin = {"timestamp": "2026-04-14T10:00:00Z", "event": "same"}
    events = [dict(twin), dict(twin), dict(twin)]
    assert len(events_after(events[1], events)) == 1


def test_events_after_unparseable_events():
    events = [
        {"id": "e0", "timestamp": "2026-04-14T10:00:00Z", "event": "a"},
        {"id": "e1", "timestamp": "later", "event": "b"},
        {"id": "e2", "timestamp": "never", "event": "c"},
    ]
    assert events_after(events[0], events) == []
    assert [e["id"] for e in events_after(events[1], events)] == ["e2"]


def _analysis(kind="first_signal", trigger="model text", reasoning="why"):
    return {"trigger": trigger, "trigger_kind": kind, "reasoning": reasoning}


def test_render_change_clause_only_for_suspected_change():
    ev = {"timestamp": "t", "source": "s", "event": "deploy v1"}
    assert ", a change that preceded onset." in render_root_cause(
        _analysis("suspected_change"), ev, None
    )
    assert "a change that preceded" not in render_root_cause(_analysis(), ev, None)


def test_render_no_symptom_sentence_without_symptom():
    ev = {"timestamp": "t", "source": "s", "event": "x"}
    assert "First symptom" not in render_root_cause(_analysis(), ev, None)
    assert "First symptom: y (at u, source=v)." in render_root_cause(
        _analysis(), ev, {"timestamp": "u", "source": "v", "event": "y"}
    )


def test_render_sourceless_event():
    line = render_root_cause(_analysis(), {"timestamp": "t", "event": "x"}, None).splitlines()[0]
    assert line == "Most likely root cause: x (at t)."


def test_render_single_period():
    ev = {"timestamp": "t", "source": "s", "event": "ERROR db pool is exhausted."}
    line = render_root_cause(_analysis(), ev, None).splitlines()[0]
    assert line == "Most likely root cause: db pool is exhausted (at t, source=s)."


def test_render_without_trigger_event_has_one_period():
    line = render_root_cause(
        _analysis("unknown", "Insufficient incident detail."), None, None
    ).splitlines()[0]
    assert line == "Most likely root cause: Insufficient incident detail."


def test_render_ignores_model_trigger_when_event_given():
    ev = {"timestamp": "t", "source": "s", "event": "deploy v1"}
    assert "model text" not in render_root_cause(_analysis(), ev, None)


def test_validate_blank_trigger_uses_event_text():
    assert (
        validate_root_cause(_draft(trigger="  \n"), EVENTS, "e1").trigger == "deploy v1 rolled out"
    )


def test_validate_null_trigger_uses_fixed_text():
    out = validate_root_cause(_draft(trigger="made up", trigger_event_id=None), EVENTS, "e1")
    assert out.trigger == NO_TRIGGER_TEXT
    assert out.trigger_kind == "unknown"


def test_validate_blank_symptom_uses_event_text():
    out = validate_root_cause(
        _draft(symptoms=[Symptom(event_id="e1", description=" ")]), EVENTS, "e1"
    )
    assert out.symptoms[0].description == "pool exhausted"


def test_validate_duplicate_symptom_keeps_first():
    out = validate_root_cause(
        _draft(
            symptoms=[
                Symptom(event_id="e1", description="first"),
                Symptom(event_id="e1", description="second"),
            ]
        ),
        EVENTS,
        "e1",
    )
    assert [(s.event_id, s.description) for s in out.symptoms] == [("e1", "pool exhausted")]


def test_validate_strips_whitespace_in_trigger_id():
    assert (
        validate_root_cause(_draft(trigger_event_id=" e0 "), EVENTS, "e1").trigger_event_id == "e0"
    )


def test_factors_empty_draft():
    assert validate_factors(ContributingFactors(), ANALYSIS, EVENTS, DURATIONS) == []


def test_factors_blank_text_dropped():
    kept = validate_factors(
        _factors((" \n", "process", ["e4"]), ("real", "process", ["e4"])),
        ANALYSIS,
        EVENTS,
        DURATIONS,
    )
    assert [f.factor for f in kept] == ["real"]


def test_factors_invented_timestamp_dropped():
    kept = validate_factors(
        _factors(("broke at 09:00:00", "process", ["e4"]), ("real", "process", ["e4"])),
        ANALYSIS,
        EVENTS,
        DURATIONS,
    )
    assert [f.factor for f in kept] == ["real"]


def test_factors_unknown_event_id_in_text_dropped():
    kept = validate_factors(
        _factors(("caused by e99", "process", ["e4"]), ("real", "process", ["e4"])),
        ANALYSIS,
        EVENTS,
        DURATIONS,
    )
    assert [f.factor for f in kept] == ["real"]


def test_factors_idless_detection_dropped_without_measured_delay():
    for durations in ({"mttd_seconds": 0, "mttd_human": "0s"}, {"mttd_seconds": None}, {}):
        kept = validate_factors(
            _factors(("gap", "detection", []), ("real", "process", ["e4"])),
            ANALYSIS,
            EVENTS,
            durations,
        )
        assert [f.factor for f in kept] == ["real"]


def test_factors_two_idless_detection_give_one_measured_sentence():
    kept = validate_factors(
        _factors(("vendor bug", "detection", []), ("other claim", "detection", ["e3"])),
        ANALYSIS,
        EVENTS,
        DURATIONS,
    )
    assert [f.factor for f in kept] == [detection_gap_text("2m 0s")]
    assert kept[0].category == "detection"
    assert kept[0].evidence_event_ids == []


def test_factors_detection_with_valid_ids_keeps_own_text():
    kept = validate_factors(
        _factors(("slow rollback", "detection", ["e4"])), ANALYSIS, EVENTS, DURATIONS
    )
    assert [(f.factor, f.evidence_event_ids) for f in kept] == [("slow rollback", ["e4"])]


def test_factors_limit():
    draft = _factors(*[(f"factor {i}", "process", ["e4"]) for i in range(20)])
    kept = validate_factors(draft, ANALYSIS, EVENTS, DURATIONS)
    assert len(kept) == MAX_FACTORS == 6
    assert kept[0].factor == "factor 0"
    assert kept[-1].factor == "factor 5"
