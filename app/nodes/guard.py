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


def guard_node(
    state: PostmortemState, config: RunnableConfig | None = None
) -> PostmortemState:
    start = time.perf_counter()
    report = state.get("report_markdown", "")
    # Each header must be a line of its own, not just a substring somewhere.
    missing = [
        s for s in REQUIRED_SECTIONS if not re.search(rf"^{re.escape(s)}\s*$", report, re.M)
    ]
    return attach_node_status(
        "guard",
        {"review_issues": missing, "review_passed": not missing},
        source="heuristic",
        duration_s=time.perf_counter() - start,
    )
