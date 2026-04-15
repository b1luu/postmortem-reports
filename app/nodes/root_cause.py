import json

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import logger, timed_node
from app.schemas import RootCause
from app.state import PostmortemState

SYSTEM = """You are a senior SRE performing root cause analysis.
Given a structured incident, identify the SINGLE most likely root cause.
Be specific. Ground your answer in the error signals and timeline.
Confidence must be one of: high, medium, low."""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM), ("human", "Incident:\n{incident}")]
)


def root_cause_node(state: PostmortemState) -> PostmortemState:
    def _fallback() -> PostmortemState:
        incident = state.get("incident", {})
        events = incident.get("events", [])
        candidate = ""
        if len(events) >= 2:
            candidate = str(events[1].get("event", ""))
        elif events:
            candidate = str(events[0].get("event", ""))
        elif incident.get("error_signals"):
            candidate = str(incident["error_signals"][0])
        else:
            candidate = "Insufficient incident detail to determine a single root cause."

        return {
            "root_cause": (
                f"Most likely root cause: {candidate}.\n\n"
                "_Reasoning:_ Derived from the earliest available incident signals "
                "without full model analysis."
            ),
            "root_cause_confidence": "low",
        }

    def _run() -> PostmortemState:
        incident = state.get("incident", {})
        try:
            llm = get_llm(temperature=0.1).with_structured_output(RootCause)
            chain = PROMPT | llm
            result: RootCause = chain.invoke(
                {"incident": json.dumps(incident, indent=2, default=str)}
            )
            return {
                "root_cause": f"{result.root_cause}\n\n_Reasoning:_ {result.reasoning}",
                "root_cause_confidence": result.confidence,
            }
        except Exception:
            logger.exception("root_cause_fallback heuristic=true")
            return _fallback()

    return timed_node("root_cause", _run)
