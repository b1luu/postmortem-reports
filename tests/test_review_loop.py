"""The write -> guard loop: a draft that fails review is rewritten with feedback,
and the final attempt falls back to the template, so a run always ends."""

from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.graph import MAX_WRITE_ATTEMPTS, build_graph
from app.nodes import writer
from app.nodes.guard import REQUIRED_SECTIONS

RAW = """2026-04-14T09:58:12Z [checkout-svc] INFO deploy v412 started
2026-04-14T10:01:04Z [checkout-svc] ERROR db pool exhausted
2026-04-14T10:03:11Z [pagerduty] alert fired for checkout error rate
2026-04-14T10:12:45Z [checkout-svc] rollback complete"""

INCOMPLETE = "# Incident Postmortem\n## Summary\nPool exhausted."
COMPLETE = "\n".join(["# Incident Postmortem"] + [f"{s}\ntext" for s in REQUIRED_SECTIONS])


def _run(responses):
    fake = FakeListChatModel(responses=responses)
    with patch.object(writer, "_ENABLE_WRITER_LLM", True), patch.object(
        writer, "get_llm", lambda **_: fake
    ):
        return build_graph().invoke({"raw_input": RAW})


def test_failed_review_is_rewritten_and_passes():
    out = _run([INCOMPLETE, COMPLETE])
    assert out["review_passed"] is True
    assert out["write_attempts"] == 2
    assert out["node_status"]["write"]["source"] == "llm"


def test_repeated_failure_ends_on_template():
    out = _run([INCOMPLETE, INCOMPLETE, INCOMPLETE])
    assert out["review_passed"] is True
    assert out["write_attempts"] == MAX_WRITE_ATTEMPTS
    assert out["node_status"]["write"]["source"] == "fallback"


def test_heuristic_mode_passes_first_time():
    out = build_graph().invoke({"raw_input": RAW})
    assert out["review_passed"] is True
    assert out["write_attempts"] == 1
