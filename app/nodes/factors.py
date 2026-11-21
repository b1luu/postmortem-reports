import json
import time

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from app.config import Mode, get_chat_model, get_mode
from app.runtime import attach_node_status, run_with_status
from app.schemas import ContributingFactors
from app.signals import (
    RESOURCE_RE,
    Signal,
    display_text,
    event_signals,
    latest_change_before,
)
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


def contributing_factors_node(
    state: PostmortemState, config: RunnableConfig | None = None
) -> PostmortemState:
    mode = get_mode(config)
    incident = state.get("incident", {})
    events = state.get("ordered_timeline") or incident.get("events", [])

    def _heuristic() -> PostmortemState:
        services = incident.get("services", [])
        started_id = (state.get("inflection_event_ids") or {}).get("started")
        durations = state.get("durations") or {}
        labelled = [(ev, event_signals(ev)) for ev in events]
        errors = [ev for ev, sigs in labelled if Signal.ERROR in sigs]

        factors: list[str] = []
        if any(RESOURCE_RE.search(str(ev.get("event", ""))) for ev in errors):
            factors.append(
                "Resource exhaustion (connection or thread pool) limited recovery "
                "headroom during the incident."
            )
        error_idx = [i for i, (_, sigs) in enumerate(labelled) if Signal.ERROR in sigs]
        if error_idx and any(
            Signal.PRECURSOR in sigs for _, sigs in labelled[: error_idx[0]]
        ):
            factors.append(
                "Early degradation signals (lag, latency, backlog) preceded hard "
                "failures, so the issue was visible before the outage."
            )
        error_sources: list[str] = []
        for ev in errors:
            src = ev.get("source", "")
            if src and src not in error_sources:
                error_sources.append(src)
        if len(error_sources) >= 2:
            factors.append(
                f"Failures spread across services ({', '.join(error_sources)}), "
                "indicating cascading impact through dependencies."
            )
        change = latest_change_before(events, started_id)
        if change is not None:
            factors.append(
                "A change shortly preceded incident onset "
                f"({display_text(str(change.get('event', '')))} at "
                f"{change.get('timestamp', '')}); treat it as a suspected trigger."
            )
        if len(services) > 1:
            factors.append(
                f"Multiple services were affected ({', '.join(services)}), "
                "amplifying user-visible impact."
            )
        if (durations.get("mttd_seconds") or 0) > 0:
            factors.append(
                f"Alerting fired {durations.get('mttd_human')} after the first error "
                "or degradation signal, indicating a detection gap."
            )

        if not factors:
            factors.append(
                "Limited incident detail made secondary contributing factors "
                "hard to confirm."
            )
        return {"contributing_factors": factors}

    start = time.perf_counter()
    if mode is Mode.HEURISTIC or events:
        return attach_node_status(
            "factors",
            _heuristic(),
            source="heuristic",
            duration_s=time.perf_counter() - start,
        )

    def _llm() -> PostmortemState:
        llm = get_chat_model(
            config, node="factors", temperature=0.2, timeout=20, num_predict=384
        ).with_structured_output(ContributingFactors)
        result: ContributingFactors = (PROMPT | llm).invoke(
            {
                "incident": json.dumps(incident, indent=2, default=str),
                "root_cause": state.get("root_cause", ""),
            }
        )
        return {"contributing_factors": result.factors}

    return run_with_status("factors", _llm, _heuristic)
