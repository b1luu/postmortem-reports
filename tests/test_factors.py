import json
from pathlib import Path

import pytest

from app.graph import build_graph
from app.nodes.factors import contributing_factors_node
from app.nodes.guard import REQUIRED_SECTIONS
from app.nodes.parser import input_parser_node
from app.nodes.timeline import timeline_node
from app.schemas import ContributingFactor, ContributingFactors, RootCauseDraft, Symptom
from tests.fakes import FakeStructuredModel

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

RESOURCE = "Resource exhaustion"
EARLY = "Early degradation"
SPREAD = "Failures spread"
CHANGE = "A change"
MULTIPLE = "Multiple services"
ALERTING = "Alerting fired"

EXPECTED = {
    "auth_cert_expiry": ([SPREAD, MULTIPLE, ALERTING], 3),
    "cache_stampede": ([EARLY, SPREAD, MULTIPLE, ALERTING], 3),
    "checkout_pool_exhaustion": ([RESOURCE, SPREAD, MULTIPLE, ALERTING], 4),
    "kafka_lag_backpressure": ([EARLY, MULTIPLE, ALERTING], 3),
}

CANARY = "Add pre-deployment canary checks"
COMPLETE = "\n".join(["# Incident Postmortem"] + [f"{s}\ntext" for s in REQUIRED_SECTIONS])
NO_VALID_FACTORS = "ValueError: no valid factors after validation"
HEURISTIC_PREFIXES = [RESOURCE, SPREAD, MULTIPLE, ALERTING]


def _run(name: str) -> dict:
    sample = json.loads((SAMPLES_DIR / f"{name}.json").read_text())
    return build_graph().invoke({"raw_input": sample["raw_input"]})


def _action_items(report: str) -> list[str]:
    block = report.split("## Action Items", 1)[-1]
    return [ln for ln in block.splitlines() if ln.startswith("- ")]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_sample_factors_and_action_count(name):
    prefixes, n_actions = EXPECTED[name]
    out = _run(name)
    factors = out["contributing_factors"]
    assert len(factors) == len(prefixes), factors
    for factor, prefix in zip(factors, prefixes):
        assert factor.startswith(prefix), (factor, prefix)
    assert len(_action_items(out["report_markdown"])) == n_actions


def test_checkout_trigger_is_not_repeated_as_a_factor():
    out = _run("checkout_pool_exhaustion")
    assert not any(f.startswith(CHANGE) for f in out["contributing_factors"])
    assert out["root_cause_analysis"]["trigger_event_id"] == "e1"
    assert any(CANARY in a for a in _action_items(out["report_markdown"]))


def test_change_after_onset_is_not_a_trigger():
    # cache_stampede's "jittered cache refill deployed" comes after onset.
    out = _run("cache_stampede")
    assert not any(f.startswith(CHANGE) for f in out["contributing_factors"])
    assert not any(CANARY in a for a in _action_items(out["report_markdown"]))


def test_precursor_without_error_is_not_early_degradation():
    state = input_parser_node(
        {
            "raw_input": "2026-04-14T10:00:00Z [svc] WARN consumer lag 50000 and growing\n"
            "2026-04-14T10:05:00Z [svc] queue drained"
        }
    )
    state.update(timeline_node(state))
    factors = contributing_factors_node(state)["contributing_factors"]
    assert not any(f.startswith(EARLY) for f in factors)


def test_precursor_after_first_error_is_not_early_degradation():
    state = input_parser_node(
        {
            "raw_input": "2026-04-14T10:00:00Z [svc] ERROR db pool exhausted\n"
            "2026-04-14T10:01:00Z [svc] WARN latency p99 high\n"
            "2026-04-14T10:02:00Z [svc] ERROR timeout fetching orders"
        }
    )
    state.update(timeline_node(state))
    assert [ev["signals"] for ev in state["ordered_timeline"]] == [
        ["error"],
        ["precursor"],
        ["error"],
    ]
    factors = contributing_factors_node(state)["contributing_factors"]
    assert not any(f.startswith(EARLY) for f in factors)


def _llm_run(factors, trigger_id="e1"):
    draft = RootCauseDraft(
        trigger="Deploy v412",
        trigger_event_id=trigger_id,
        symptoms=[Symptom(event_id="e2", description="pool exhausted")],
        evidence_event_ids=["e2", "e3", "e4"],
        confidence="high",
        reasoning="Deploy then pool.",
    )
    fake = FakeStructuredModel(
        text_responses=[COMPLETE],
        structured_responses={
            "RootCauseDraft": [draft],
            "ContributingFactors": [ContributingFactors(factors=factors)],
        },
    )
    sample = json.loads((SAMPLES_DIR / "checkout_pool_exhaustion.json").read_text())
    config = {"configurable": {"mode": "llm", "llm_factory": lambda **_: fake}}
    return fake, build_graph().invoke({"raw_input": sample["raw_input"]}, config=config)


def _factor(category, ids, text="Rollback took a manual step"):
    return ContributingFactor(factor=text, category=category, evidence_event_ids=ids)


LLM_ROWS = [
    ("valid", [_factor("process", ["e6"])], "llm", [["e6"]], None),
    ("empty", [], "llm", [], None),
    ("only trigger and symptom ids", [_factor("change", ["e1", "e2"])], "fallback", None, NO_VALID_FACTORS),
    ("mixed ids", [_factor("process", ["e2", "e6", "e99"])], "llm", [["e6"]], None),
    (
        "detection with only an alert id",
        [_factor("detection", ["e5"], "DB vendor shipped a corrupt driver")],
        "llm",
        [[]],
        None,
    ),
    ("process with only an alert id", [_factor("process", ["e5"])], "fallback", None, NO_VALID_FACTORS),
]


@pytest.mark.parametrize(
    "factors,source,stored,error", [r[1:] for r in LLM_ROWS], ids=[r[0] for r in LLM_ROWS]
)
def test_llm_factors_table(factors, source, stored, error):
    fake, out = _llm_run(factors)
    assert [c["schema"] for c in fake.calls] == ["RootCauseDraft", "ContributingFactors", None]
    assert out["node_status"]["factors"]["source"] == source
    assert out["node_status"]["factors"]["error"] == error
    for node in ("root_cause", "write"):
        assert out["node_status"][node]["source"] == "llm"
        assert out["node_status"][node]["error"] is None
    details = out["contributing_factor_details"]
    assert out["contributing_factors"] == [d["factor"] for d in details]
    if stored is None:
        assert len(details) == len(HEURISTIC_PREFIXES)
        for detail, prefix in zip(details, HEURISTIC_PREFIXES):
            assert detail["factor"].startswith(prefix)
    else:
        assert [d["evidence_event_ids"] for d in details] == stored
    if factors and factors[0].factor.startswith("DB vendor"):
        assert details[0]["factor"].startswith("Alerting fired 2m 7s")
        assert "DB vendor" not in json.dumps(out["contributing_factors"])


def test_fallback_keeps_change_when_llm_named_another_trigger():
    fake, out = _llm_run([_factor("process", ["e99"])], trigger_id="e0")
    assert [c["schema"] for c in fake.calls] == ["RootCauseDraft", "ContributingFactors", None]
    for node in ("root_cause", "write"):
        assert out["node_status"][node]["source"] == "llm"
        assert out["node_status"][node]["error"] is None
    assert out["node_status"]["factors"]["source"] == "fallback"
    assert out["node_status"]["factors"]["error"] == NO_VALID_FACTORS
    change = [d for d in out["contributing_factor_details"] if d["category"] == "change"]
    assert change == [
        {
            "factor": "A change shortly preceded incident onset "
            "(deploy v412 healthy at 2026-04-14T10:00:31Z).",
            "category": "change",
            "evidence_event_ids": ["e1"],
        }
    ]
