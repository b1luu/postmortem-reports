import json
import time

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from app.config import Mode, get_chat_model, get_mode
from app.runtime import attach_node_status, run_with_status
from app.schemas import RootCause
from app.signals import Signal, event_signals, signal_values
from app.state import PostmortemState

SYSTEM = """You are a senior SRE performing root cause analysis.
Given a structured incident, identify the SINGLE most likely root cause.
Be specific. Ground your answer in the error signals and timeline.
Confidence must be one of: high, medium, low."""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM), ("human", "Incident:\n{incident}")]
)

_CAUSE_SIGNALS = {Signal.ERROR, Signal.PRECURSOR}


def root_cause_node(
    state: PostmortemState, config: RunnableConfig | None = None
) -> PostmortemState:
    mode = get_mode(config)
    incident = state.get("incident", {})
    # Prefer the timeline node's chronologically sorted events; raw incident
    # events are in input order, which is arbitrary for merged multi-source logs.
    events = state.get("ordered_timeline") or incident.get("events", [])

    def _heuristic() -> PostmortemState:
        error_signals = incident.get("error_signals", [])

        primary_event = None
        evidence: list[dict] = []
        for ev in events:
            signals = event_signals(ev)
            if signals & _CAUSE_SIGNALS:
                if primary_event is None:
                    primary_event = ev
                evidence.append(
                    {
                        "id": ev.get("id"),
                        "timestamp": ev.get("timestamp", ""),
                        "source": ev.get("source", ""),
                        "event": ev.get("event", ""),
                        "signals": signal_values(signals),
                    }
                )
            if len(evidence) >= 4:
                break

        if primary_event is not None:
            ts = primary_event.get("timestamp", "unknown time")
            src = primary_event.get("source", "")
            candidate = f"{primary_event.get('event', '').strip()} (at {ts}"
            candidate += f", source={src})" if src else ")"
        elif error_signals:
            candidate = f"Error signal: {error_signals[0]}"
        elif events:
            candidate = str(events[0].get("event", "")).strip()
        else:
            candidate = "Insufficient incident detail to determine a single root cause."

        confidence = "medium" if primary_event and len(evidence) >= 2 else "low"

        return {
            "root_cause": (
                f"Most likely root cause: {candidate}\n\n"
                "_Reasoning:_ Heuristically derived from the earliest error signal "
                "in the timeline, corroborated by "
                f"{len(evidence)} supporting event(s)."
            ),
            "root_cause_confidence": confidence,
            "root_cause_evidence": evidence,
        }

    start = time.perf_counter()
    if mode is Mode.HEURISTIC or events or incident.get("error_signals"):
        return attach_node_status(
            "root_cause",
            _heuristic(),
            source="heuristic",
            duration_s=time.perf_counter() - start,
        )

    def _llm() -> PostmortemState:
        llm = get_chat_model(
            config, node="root_cause", temperature=0.1, timeout=20, num_predict=384
        ).with_structured_output(RootCause)
        result: RootCause = (PROMPT | llm).invoke(
            {
                "incident": json.dumps(
                    {**incident, "events": events}, indent=2, default=str
                )
            }
        )
        return {
            "root_cause": f"{result.root_cause}\n\n_Reasoning:_ {result.reasoning}",
            "root_cause_confidence": result.confidence,
        }

    return run_with_status("root_cause", _llm, _heuristic)
