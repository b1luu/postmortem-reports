"""The write -> guard loop: a draft that fails review is rewritten with feedback,
and the final attempt falls back to the template, so a run always ends."""

from app.config import MAX_WRITE_ATTEMPTS
from app.graph import build_graph
from app.nodes.guard import REQUIRED_SECTIONS
from app.schemas import ContributingFactors, RootCauseDraft
from tests.fakes import FakeStructuredModel

RAW = """2026-04-14T09:58:12Z [checkout-svc] INFO deploy v412 started
2026-04-14T10:01:04Z [checkout-svc] ERROR db pool exhausted
2026-04-14T10:03:11Z [pagerduty] alert fired for checkout error rate
2026-04-14T10:12:45Z [checkout-svc] rollback complete"""

INCOMPLETE = "# Incident Postmortem\n## Summary\nPool exhausted."
COMPLETE = "\n".join(["# Incident Postmortem"] + [f"{s}\ntext" for s in REQUIRED_SECTIONS])


def _run(responses):
    draft = RootCauseDraft(
        trigger="deploy",
        trigger_event_id="e0",
        evidence_event_ids=["e1"],
        confidence="low",
        reasoning="r",
    )
    fake = FakeStructuredModel(
        text_responses=list(responses),
        structured_responses={
            "RootCauseDraft": [draft],
            "ContributingFactors": [ContributingFactors()],
        },
    )
    config = {"configurable": {"mode": "llm", "llm_factory": lambda **_: fake}}
    return fake, build_graph().invoke({"raw_input": RAW}, config=config)


def _assert_analysis_nodes_used_llm(out):
    for node in ("root_cause", "factors"):
        assert out["node_status"][node]["source"] == "llm"
        assert out["node_status"][node]["error"] is None


def test_failed_review_is_rewritten_and_passes():
    fake, out = _run([INCOMPLETE, COMPLETE])
    assert [c["kind"] for c in fake.calls] == ["structured", "structured", "text", "text"]
    _assert_analysis_nodes_used_llm(out)
    assert out["review_passed"] is True
    assert out["write_attempts"] == 2
    assert out["node_status"]["write"]["source"] == "llm"
    assert out["node_status"]["write"]["error"] is None
    # The second draft was asked for with the reviewer's feedback.
    assert "failed review" not in fake.calls[2]["input"]
    assert "failed review" in fake.calls[3]["input"]


def test_repeated_failure_ends_on_template():
    fake, out = _run([INCOMPLETE, INCOMPLETE, INCOMPLETE])
    # The last attempt uses the template without asking the model.
    assert [c["kind"] for c in fake.calls] == ["structured", "structured", "text", "text"]
    assert sum(c["kind"] == "text" for c in fake.calls) == MAX_WRITE_ATTEMPTS - 1
    assert "failed review" in fake.calls[3]["input"]
    _assert_analysis_nodes_used_llm(out)
    assert out["review_passed"] is True
    assert out["write_attempts"] == MAX_WRITE_ATTEMPTS
    assert out["node_status"]["write"]["source"] == "fallback"
    assert out["node_status"]["write"]["error"] is None


def test_heuristic_mode_passes_first_time():
    out = build_graph().invoke({"raw_input": RAW})
    assert out["review_passed"] is True
    assert out["write_attempts"] == 1
    assert out["node_status"]["write"]["source"] == "heuristic"
