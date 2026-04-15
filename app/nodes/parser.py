import json
import re

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import logger, timed_node
from app.schemas import ParsedIncident
from app.state import Incident, PostmortemState

SYSTEM = """You are an SRE assistant. Extract a structured incident from raw input.
Return ONLY the fields requested. If a field is unknown, use an empty list or "unknown".
Severity must be one of: sev1, sev2, sev3, sev4, unknown."""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM), ("human", "Raw incident input:\n\n{raw}")]
)


def _coerce_raw(raw) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, indent=2, default=str)
    except Exception:
        return str(raw)


def _heuristic_parse(raw) -> Incident:
    raw_text = _coerce_raw(raw)
    events = []
    chunks = []
    for line in raw_text.splitlines():
        chunks.extend(part.strip() for part in line.split(";") if part.strip())

    for chunk in chunks:
        match = re.match(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}T[^\s]+)\s+(?P<event>.+)",
            chunk,
        )
        if match:
            events.append(
                {
                    "timestamp": match.group("timestamp"),
                    "event": match.group("event").strip(" ;"),
                    "source": "",
                }
            )

    lowered = raw_text.lower()
    severity = "unknown"
    for candidate in ("sev1", "sev2", "sev3", "sev4"):
        if candidate in lowered:
            severity = candidate
            break

    error_signals = []
    for keyword in (
        "error",
        "exception",
        "timeout",
        "latency",
        "exhausted",
        "failed",
        "failure",
        "unavailable",
    ):
        if keyword in lowered:
            error_signals.append(keyword)

    return {
        "events": events,
        "services": [],
        "error_signals": error_signals,
        "severity": severity,
    }


def input_parser_node(state: PostmortemState) -> PostmortemState:
    def _run() -> PostmortemState:
        raw = state.get("raw_input", "")

        # Fast path: already-structured dict that looks like an Incident.
        if isinstance(raw, dict) and any(
            k in raw for k in ("events", "services", "error_signals", "severity")
        ):
            incident: Incident = {
                "events": raw.get("events", []),
                "services": raw.get("services", []),
                "error_signals": raw.get("error_signals", []),
                "severity": raw.get("severity", "unknown"),
            }
            return {"incident": incident}

        heuristic = _heuristic_parse(raw)
        if heuristic["events"]:
            return {"incident": heuristic}

        try:
            llm = get_llm(temperature=0.0).with_structured_output(ParsedIncident)
            chain = PROMPT | llm
            parsed: ParsedIncident = chain.invoke({"raw": _coerce_raw(raw)})
            incident: Incident = {
                "events": [e.model_dump() for e in parsed.events],
                "services": parsed.services,
                "error_signals": parsed.error_signals,
                "severity": parsed.severity or "unknown",
            }
            return {"incident": incident}
        except Exception:
            logger.exception("parser_fallback heuristic=true")
            return {"incident": heuristic}

    return timed_node("parse", _run)
