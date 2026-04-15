import json
import re
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

_HTTP_ERROR_RE = re.compile(r"\b(?:5\d\d|50[03])\b", re.IGNORECASE)
_PRECURSOR_RE = re.compile(
    r"\b(?:consumer lag|replication lag|certificate has expired|cert(?:ificate)? expired)\b",
    re.IGNORECASE,
)


def _matches_root_cause_signal(text: str) -> bool:
    if _PRECURSOR_RE.search(text) is not None:
        return True
    if any(k in text for k in ("error", "fail", "exhaust", "timeout", "unavailable", "crash")):
        return True
    return _HTTP_ERROR_RE.search(text) is not None


def root_cause_node(state: PostmortemState) -> PostmortemState:
    incident = state.get("incident", {})

    def _heuristic() -> PostmortemState:
        events = incident.get("events", [])
        error_signals = incident.get("error_signals", [])

        primary_event = None
        evidence: list[dict] = []
        for ev in events:
            text = str(ev.get("event", "")).lower()
            if _matches_root_cause_signal(text):
                if primary_event is None:
                    primary_event = ev
                evidence.append(
                    {
                        "timestamp": ev.get("timestamp", ""),
                        "source": ev.get("source", ""),
                        "event": ev.get("event", ""),
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
