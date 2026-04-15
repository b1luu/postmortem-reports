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
    g.add_edge("guard", END)

    return g.compile()


graph = build_graph()
