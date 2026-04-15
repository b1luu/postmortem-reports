import json
import time

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import attach_node_status, run_with_status
from app.schemas import RootCause
from app.state import PostmortemState

SYSTEM = """You are a senior SRE performing root cause analysis.
Given a structured incident, identify the SINGLE most likely root cause.
Be specific. Ground your answer in the error signals and timeline.
Confidence must be one of: high, medium, low."""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM), ("human", "Incident:\n{incident}")]
)

_ROOT_CAUSE_KEYWORDS = (
    "error",
    "fail",
    "exhaust",
    "timeout",
    "unavailable",
    "crash",
    "503",
    "500",
)


def root_cause_node(state: PostmortemState) -> PostmortemState:
    incident = state.get("incident", {})

    def _heuristic() -> PostmortemState:
        events = incident.get("events", [])
        error_signals = incident.get("error_signals", [])

        candidate = ""
        for ev in events:
            text = str(ev.get("event", "")).lower()
            if any(k in text for k in _ROOT_CAUSE_KEYWORDS):
                ts = ev.get("timestamp", "unknown time")
                src = ev.get("source", "")
                candidate = f"{ev.get('event', '').strip()} (at {ts}"
                candidate += f", source={src})" if src else ")"
                break

        if not candidate and error_signals:
            candidate = f"Error signal: {error_signals[0]}"
        if not candidate and events:
            candidate = str(events[0].get("event", "")).strip()
        if not candidate:
            candidate = "Insufficient incident detail to determine a single root cause."

        return {
            "root_cause": (
                f"Most likely root cause: {candidate}\n\n"
                "_Reasoning:_ Heuristically derived from the earliest error signal "
                "in the timeline without full model analysis."
            ),
            "root_cause_confidence": "low",
        }

    start = time.perf_counter()
    if incident.get("events") or incident.get("error_signals"):
        return attach_node_status(
            "root_cause",
            _heuristic(),
            source="heuristic",
            duration_s=time.perf_counter() - start,
        )

    def _llm() -> PostmortemState:
        llm = get_llm(temperature=0.1, timeout=20, num_predict=384).with_structured_output(
            RootCause
        )
        result: RootCause = (PROMPT | llm).invoke(
            {"incident": json.dumps(incident, indent=2, default=str)}
        )
        return {
            "root_cause": f"{result.root_cause}\n\n_Reasoning:_ {result.reasoning}",
            "root_cause_confidence": result.confidence,
        }

    return run_with_status("root_cause", _llm, _heuristic)
