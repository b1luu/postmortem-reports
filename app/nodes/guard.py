from app.state import PostmortemState

REQUIRED_SECTIONS = [
    "## Summary",
    "## Impact",
    "## Timeline",
    "## Root Cause",
    "## Contributing Factors",
    "## Action Items",
]


def guard_node(state: PostmortemState) -> PostmortemState:
    report = state.get("report_markdown", "")
    missing = [s for s in REQUIRED_SECTIONS if s not in report]
    return {"review_issues": missing, "review_passed": not missing}
