import json

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import logger, timed_node
from app.schemas import InflectionPoints
from app.state import PostmortemState

SYSTEM = """Given a chronological list of incident events, identify three key
inflection points by timestamp: when the incident STARTED, when it was DETECTED,
and when it was RESOLVED. Use the exact timestamp strings from the events.
If a point cannot be determined, return an empty string for that field."""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM), ("human", "Events:\n{events}")]
)


def timeline_node(state: PostmortemState) -> PostmortemState:
    def _fallback(events: list[dict]) -> PostmortemState:
        inflection: dict[str, str] = {"started": "", "detected": "", "resolved": ""}
        if not events:
            return {"ordered_timeline": events, "inflection_points": inflection}

        inflection["started"] = str(events[0].get("timestamp", ""))
        inflection["resolved"] = str(events[-1].get("timestamp", ""))

        for event in events:
            description = str(event.get("event", "")).lower()
            if any(word in description for word in ("detected", "alert", "page", "latency", "error")):
                inflection["detected"] = str(event.get("timestamp", ""))
                break

        if not inflection["detected"]:
            inflection["detected"] = inflection["started"]

        return {"ordered_timeline": events, "inflection_points": inflection}

    def _run() -> PostmortemState:
        events = list(state.get("incident", {}).get("events", []))
        events.sort(key=lambda e: str(e.get("timestamp", "")))

        if not events:
            return _fallback(events)

        try:
            llm = get_llm(temperature=0.0).with_structured_output(InflectionPoints)
            chain = PROMPT | llm
            result: InflectionPoints = chain.invoke(
                {"events": json.dumps(events, indent=2, default=str)}
            )
            return {
                "ordered_timeline": events,
                "inflection_points": {
                    "started": result.started,
                    "detected": result.detected,
                    "resolved": result.resolved,
                },
            }
        except Exception:
            logger.exception("timeline_fallback heuristic=true")
            return _fallback(events)

    return timed_node("timeline", _run)
