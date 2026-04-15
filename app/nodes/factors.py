import json
import time

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import attach_node_status, run_with_status
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
    incident = state.get("incident", {})

    def _heuristic() -> PostmortemState:
        events = incident.get("events", [])
        services = incident.get("services", [])
        event_text = " ".join(str(ev.get("event", "")) for ev in events).lower()

        factors: list[str] = []
        if "exhaust" in event_text or "pool" in event_text:
            factors.append(
                "Resource exhaustion (connection or thread pool) limited recovery "
                "headroom during the incident."
            )
        if "latency" in event_text:
            factors.append(
                "Elevated latency preceded hard failures, suggesting degradation "
                "was visible before outage."
            )
        if "503" in event_text or "upstream" in event_text:
            factors.append(
                "Cascading failures propagated across services via upstream "
                "dependencies."
            )
        if "rollback" in event_text or "deploy" in event_text:
            factors.append(
                "A recent deployment correlates with incident onset; rollback "
                "was the recovery path."
            )
        if len(services) > 1:
            factors.append(
                f"Multiple services were affected ({', '.join(services)}), "
                "amplifying user-visible impact."
            )
        if any("alert" in str(ev.get("event", "")).lower() for ev in events) and any(
            "error" in str(ev.get("event", "")).lower() for ev in events
        ):
            factors.append(
                "Alerting fired after error-log signals were already visible, "
                "indicating a detection-gap between logs and paging."
            )

        if not factors:
            factors.append(
                "Limited incident detail made secondary contributing factors "
                "hard to confirm."
            )
        return {"contributing_factors": factors}

    start = time.perf_counter()
    if incident.get("events"):
        return attach_node_status(
            "factors",
            _heuristic(),
            source="heuristic",
            duration_s=time.perf_counter() - start,
        )

    def _llm() -> PostmortemState:
        llm = get_llm(temperature=0.2, timeout=20, num_predict=384).with_structured_output(
            ContributingFactors
        )
        result: ContributingFactors = (PROMPT | llm).invoke(
            {
                "incident": json.dumps(incident, indent=2, default=str),
                "root_cause": state.get("root_cause", ""),
            }
        )
        return {"contributing_factors": result.factors}

    return run_with_status("factors", _llm, _heuristic)
