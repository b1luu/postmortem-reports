import inspect
import json
import os
from pathlib import Path

import pytest

import app
import app.nodes
from app.graph import build_graph, graph
from app.nodes.guard import REQUIRED_SECTIONS
from app.nodes.parser import NO_EVENTS_MSG
from app.schemas import (
    ContributingFactors,
    ParsedIncident,
    RootCauseDraft,
    TimelineEventModel,
)
from tests.fakes import FakeStructuredModel, ForbidLLM

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = sorted((ROOT / "samples").glob("*.json"))
PROSE = "Checkout went down for a while yesterday afternoon."
ALLOWED_SOURCES = {"input", "heuristic", "llm", "fallback"}
NODES = ("parse", "timeline", "root_cause", "factors", "write", "guard")
COMPLETE = "\n".join(["# Incident Postmortem"] + [f"{s}\ntext" for s in REQUIRED_SECTIONS])


def _raw(path: Path):
    return json.loads(path.read_text())["raw_input"]


def test_graph_has_six_nodes():
    assert len(set(graph.get_graph().nodes) - {"__start__", "__end__"}) == 6


def test_env_is_isolated_by_conftest():
    assert app is not None
    assert os.environ["LANGSMITH_TRACING"] == "false"


@pytest.mark.parametrize("sample_path", SAMPLES, ids=lambda p: p.stem)
def test_configurable_heuristic_overrides_env_llm(monkeypatch, sample_path):
    monkeypatch.setenv("POSTMORTEM_MODE", "llm")
    forbid = ForbidLLM()
    config = {"configurable": {"mode": "heuristic", "llm_factory": forbid}}
    out = build_graph().invoke({"raw_input": _raw(sample_path)}, config=config)
    assert forbid.calls == []
    assert all(s["error"] is None for s in out["node_status"].values())
    assert [out["node_status"][n]["source"] for n in NODES] == ["heuristic"] * 6


def test_heuristic_prose_reports_no_events(monkeypatch):
    monkeypatch.setenv("POSTMORTEM_MODE", "llm")
    forbid = ForbidLLM()
    config = {"configurable": {"mode": "heuristic", "llm_factory": forbid}}
    out = build_graph().invoke({"raw_input": PROSE}, config=config)
    assert forbid.calls == []
    assert out["node_status"]["parse"]["error"] == NO_EVENTS_MSG
    others = {k: v["error"] for k, v in out["node_status"].items() if k != "parse"}
    assert all(e is None for e in others.values()), others
    assert [out["node_status"][n]["source"] for n in NODES] == ["heuristic"] * 6


@pytest.mark.parametrize("sample_path", SAMPLES, ids=lambda p: p.stem)
def test_final_state_is_plain_json(sample_path):
    out = graph.invoke({"raw_input": _raw(sample_path)})
    json.dumps(out)  # no default=: everything must be plain JSON
    assert "guard" in out["node_status"]
    assert {s["source"] for s in out["node_status"].values()} <= ALLOWED_SOURCES


def test_nodes_get_a_real_config_annotation():
    for name in app.nodes.__all__:
        fn = getattr(app.nodes, name)
        annotation = inspect.signature(fn).parameters["config"].annotation
        assert not isinstance(annotation, str), name
    for path in [ROOT / "app" / "graph.py", *(ROOT / "app" / "nodes").glob("*.py")]:
        assert "from __future__ import annotations" not in path.read_text(), path


def test_config_reaches_llm_nodes_without_events():
    # Env stays heuristic (conftest); only the configurable switches to llm.
    forbid = ForbidLLM()
    config = {"configurable": {"mode": "llm", "llm_factory": forbid}}
    out = build_graph().invoke({"raw_input": PROSE}, config=config)
    assert forbid.calls == ["parse", "write"]
    for node in forbid.calls:
        status = out["node_status"][node]
        assert status["source"] == "fallback"
        assert "LLM called" in status["error"]
    for node in ("root_cause", "factors"):
        assert out["node_status"][node]["source"] == "heuristic"
        assert out["node_status"][node]["error"] is None


def test_config_reaches_llm_nodes_with_events():
    forbid = ForbidLLM()
    config = {"configurable": {"mode": "llm", "llm_factory": forbid}}
    raw = _raw(ROOT / "samples" / "checkout_pool_exhaustion.json")
    out = build_graph().invoke({"raw_input": raw}, config=config)
    assert forbid.calls == ["root_cause", "factors", "write"]
    for node in forbid.calls:
        status = out["node_status"][node]
        assert status["source"] == "fallback"
        assert "LLM called" in status["error"]
    assert out["node_status"]["parse"]["source"] == "heuristic"
    assert out["node_status"]["parse"]["error"] is None


def _scripted_fake():
    parsed = ParsedIncident(
        events=[
            TimelineEventModel(
                timestamp="2026-04-14T10:00:00Z", event="deploy v1 rolled out", source="a"
            ),
            TimelineEventModel(
                timestamp="2026-04-14T10:01:00Z", event="ERROR pool exhausted", source="a"
            ),
        ],
        services=["a"],
    )
    draft = RootCauseDraft(
        trigger="Deploy v1",
        trigger_event_id="e0",
        evidence_event_ids=["e1"],
        confidence="low",
        reasoning="r",
    )
    return FakeStructuredModel(
        text_responses=[COMPLETE],
        structured_responses={
            "ParsedIncident": [parsed],
            "RootCauseDraft": [draft],
            "ContributingFactors": [ContributingFactors()],
        },
    )


LLM_NODES = ("parse", "root_cause", "factors", "write")


def test_llm_metadata_on_every_call(monkeypatch):
    monkeypatch.setenv("POSTMORTEM_MODE", "llm")
    fake = _scripted_fake()
    config = {"configurable": {"llm_factory": lambda **_: fake}}
    out = build_graph().invoke({"raw_input": PROSE}, config=config)
    assert [c["metadata"] for c in fake.calls] == [
        {"mode": "llm", "node": n} for n in LLM_NODES
    ]
    for node in LLM_NODES:
        assert out["node_status"][node]["source"] == "llm"
        assert out["node_status"][node]["error"] is None


def test_config_is_not_stored():
    fake = _scripted_fake()
    config = {"configurable": {"mode": "llm", "llm_factory": lambda **_: fake}}
    out = build_graph().invoke({"raw_input": PROSE}, config=config)
    assert [c["schema"] for c in fake.calls] == [
        "ParsedIncident",
        "RootCauseDraft",
        "ContributingFactors",
        None,
    ]
    for node in LLM_NODES:
        assert out["node_status"][node]["source"] == "llm"
        assert out["node_status"][node]["error"] is None
    serialized = json.dumps(out)
    assert "llm_factory" not in serialized
    assert "__pregel" not in serialized
