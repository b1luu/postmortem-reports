import re
import time

from langchain_core.runnables import RunnableConfig

from app.runtime import attach_node_status
from app.state import PostmortemState

REQUIRED_SECTIONS = [
    "## Summary",
    "## Impact",
    "## Timeline",
    "## Root Cause",
    "## Contributing Factors",
    "## Action Items",
]

NO_EVENTS = "no timeline events were extracted from the input"
NO_EVIDENCE = "root cause has no supporting evidence events"


def missing_sections(report: str) -> list[str]:
    # Each header must be a line of its own, not just a substring somewhere.
    return [s for s in REQUIRED_SECTIONS if not re.search(rf"^{re.escape(s)}\s*$", report, re.M)]


def analysis_blockers(state: PostmortemState) -> list[str]:
    """Problems in the analysis itself. A rewrite of the report can't fix
    these, so the graph stops instead of looping back to the writer."""
    events = (state.get("incident") or {}).get("events") or []
    if not events:
        return [NO_EVENTS]
    if not state.get("root_cause_evidence"):
        return [NO_EVIDENCE]
    return []


def guard_node(state: PostmortemState, config: RunnableConfig | None = None) -> PostmortemState:
    start = time.perf_counter()
    missing = missing_sections(state.get("report_markdown", ""))
    blockers = analysis_blockers(state)
    return attach_node_status(
        "guard",
        {
            "review_issues": missing + blockers,
            "review_blockers": blockers,
            "review_passed": not missing and not blockers,
        },
        source="heuristic",
        duration_s=time.perf_counter() - start,
    )
