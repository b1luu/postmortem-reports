import json

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import logger, timed_node
from app.schemas import ContributingFactors
from app.state import PostmortemState

SYSTEM = """You are a senior SRE. Identify SECONDARY contributing factors that
compounded the incident beyond the primary root cause. Examples: misconfiguration,
cascading failures, missing alerts, insufficient runbooks, capacity gaps.
Return 0-6 concise bullet-sized factors. Do not restate the root cause."""

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM),
        (
            "human",
            "Incident:\n{incident}\n\nPrimary root cause:\n{root_cause}",
        ),
    ]
)


def contributing_factors_node(state: PostmortemState) -> PostmortemState:
    def _fallback() -> PostmortemState:
        incident = state.get("incident", {})
        factors = []
        events_text = " ".join(
            str(event.get("event", "")) for event in incident.get("events", [])
        ).lower()

        if "latency" in events_text:
            factors.append("Elevated latency was visible before full service degradation.")
        if "exhausted" in events_text:
            factors.append("Resource exhaustion reduced recovery headroom during the incident.")
        if not factors:
            factors.append("Limited incident detail made secondary contributing factors hard to confirm.")

        return {"contributing_factors": factors}

    def _run() -> PostmortemState:
        try:
            llm = get_llm(temperature=0.2).with_structured_output(ContributingFactors)
            chain = PROMPT | llm
            result: ContributingFactors = chain.invoke(
                {
                    "incident": json.dumps(state.get("incident", {}), indent=2, default=str),
                    "root_cause": state.get("root_cause", ""),
                }
            )
            return {"contributing_factors": result.factors}
        except Exception:
            logger.exception("factors_fallback heuristic=true")
            return _fallback()

    return timed_node("factors", _run)
