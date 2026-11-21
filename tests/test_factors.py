import json
from pathlib import Path

import pytest

from app.graph import build_graph
from app.nodes.factors import contributing_factors_node
from app.nodes.parser import input_parser_node
from app.nodes.timeline import timeline_node

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
    "checkout_pool_exhaustion": ([RESOURCE, SPREAD, CHANGE, MULTIPLE, ALERTING], 4),
    "kafka_lag_backpressure": ([EARLY, MULTIPLE, ALERTING], 3),
}

CANARY = "Add pre-deployment canary checks"
CHECKOUT_CHANGE = (
    "A change shortly preceded incident onset (deploy v412 healthy at "
    "2026-04-14T10:00:31Z); treat it as a suspected trigger."
)


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


def test_checkout_change_factor_exact_text():
    assert CHECKOUT_CHANGE in _run("checkout_pool_exhaustion")["contributing_factors"]


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
