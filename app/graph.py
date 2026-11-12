from langgraph.graph import END, START, StateGraph

from app.nodes import (
    contributing_factors_node,
    guard_node,
    input_parser_node,
    root_cause_node,
    timeline_node,
    writer_node,
)
from app.state import PostmortemState

# write -> guard can loop: a report that fails review is rewritten with the
# reviewer's feedback, and the last attempt uses the deterministic template,
# which always has every required section.
MAX_WRITE_ATTEMPTS = 3


def route_after_guard(state: PostmortemState) -> str:
    if state.get("review_passed"):
        return END
    if state.get("write_attempts", 0) >= MAX_WRITE_ATTEMPTS:
        return END
    return "write"


def build_graph():
    g = StateGraph(PostmortemState)
    g.add_node("parse", input_parser_node)
    g.add_node("root_cause", root_cause_node)
    g.add_node("factors", contributing_factors_node)
    g.add_node("timeline", timeline_node)
    g.add_node("write", writer_node)
    g.add_node("guard", guard_node)

    g.add_edge(START, "parse")
    g.add_edge("parse", "root_cause")
    g.add_edge("root_cause", "factors")
    g.add_edge("factors", "timeline")
    g.add_edge("timeline", "write")
    g.add_edge("write", "guard")
    g.add_conditional_edges("guard", route_after_guard, {"write": "write", END: END})

    return g.compile()


graph = build_graph()
