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


def test_guard_requires_headers_on_their_own_lines():
    md = "# Incident Postmortem\n## Summary ## Impact\n" + "\n".join(REQUIRED_SECTIONS[2:])
    out = guard_node({"report_markdown": md})
    assert out["review_passed"] is False
    assert out["review_issues"] == ["## Summary", "## Impact"]


def test_guard_reports_node_status():
    out = guard_node({"report_markdown": ""})
    assert out["node_status"]["guard"]["source"] == "heuristic"
