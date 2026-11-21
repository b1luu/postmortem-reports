import inspect
import json
import os
from pathlib import Path

import pytest

import app
import app.nodes
from app.graph import build_graph, graph
from app.nodes.parser import NO_EVENTS_MSG
from tests.fakes import ForbidLLM

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = sorted((ROOT / "samples").glob("*.json"))
PROSE = "Checkout went down for a while yesterday afternoon."
ALLOWED_SOURCES = {"input", "heuristic", "llm", "fallback"}


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


def test_heuristic_prose_reports_no_events(monkeypatch):
    monkeypatch.setenv("POSTMORTEM_MODE", "llm")
    forbid = ForbidLLM()
    config = {"configurable": {"mode": "heuristic", "llm_factory": forbid}}
    out = build_graph().invoke({"raw_input": PROSE}, config=config)
    assert forbid.calls == []
    assert out["node_status"]["parse"]["error"] == NO_EVENTS_MSG
    others = {k: v["error"] for k, v in out["node_status"].items() if k != "parse"}
    assert all(e is None for e in others.values()), others


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


def test_config_reaches_every_llm_capable_node():
    # Env stays heuristic (conftest); only the configurable switches to llm.
    forbid = ForbidLLM()
    config = {"configurable": {"mode": "llm", "llm_factory": forbid}}
    out = build_graph().invoke({"raw_input": PROSE}, config=config)
    assert forbid.calls == ["parse", "root_cause", "factors", "write"]
    for node in forbid.calls:
        status = out["node_status"][node]
        assert status["source"] == "fallback"
        assert "LLM called" in status["error"]
