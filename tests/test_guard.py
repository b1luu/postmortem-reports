from app.nodes.guard import REQUIRED_SECTIONS, guard_node


def test_guard_flags_missing_sections():
    out = guard_node({"report_markdown": "# Incident Postmortem\n## Summary\nnope"})
    assert out["review_passed"] is False
    assert "## Impact" in out["review_issues"]


def test_guard_passes_complete_report():
    md = "\n".join(["# Incident Postmortem"] + REQUIRED_SECTIONS)
    out = guard_node({"report_markdown": md})
    assert out["review_passed"] is True
    assert out["review_issues"] == []
