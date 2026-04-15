import json
import re
import time

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import attach_node_status, run_with_status
from app.schemas import ParsedIncident
from app.state import Incident, PostmortemState

SYSTEM = """You are an SRE assistant. Extract a structured incident from raw input.
Return ONLY the fields requested. If a field is unknown, use an empty list or "unknown".
Severity must be one of: sev1, sev2, sev3, sev4, unknown.
Prefer exact service names and timestamps as they appear in the input."""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM), ("human", "Raw incident input:\n\n{raw}")]
)

_TIMESTAMP_RE = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T[^\s]+)\s+(?:\[(?P<source>[^\]]+)\]\s+)?(?P<event>.+)"
)
_SEV_RE = re.compile(r"\bsev[1-4]\b", re.IGNORECASE)
_ERROR_KEYWORDS = (
    "error",
    "exception",
    "timeout",
    "latency",
    "exhausted",
    "failed",
    "failure",
    "unavailable",
    "crash",
    "5\\d\\d",
)
_ERROR_RE = re.compile("|".join(_ERROR_KEYWORDS), re.IGNORECASE)


def _coerce_raw(raw) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, indent=2, default=str)
    except Exception:
        return str(raw)


def _heuristic_parse(raw) -> Incident:
    raw_text = _coerce_raw(raw)
    events: list[dict] = []
    services_seen: list[str] = []

    chunks: list[str] = []
    for line in raw_text.splitlines():
        chunks.extend(part.strip() for part in line.split(";") if part.strip())

    for chunk in chunks:
        match = _TIMESTAMP_RE.match(chunk)
        if not match:
            continue
        source = (match.group("source") or "").strip()
        events.append(
            {
                "timestamp": match.group("timestamp"),
                "event": match.group("event").strip(" ;"),
                "source": source,
            }
        )
        if source and source not in services_seen:
            services_seen.append(source)

    sev_match = _SEV_RE.search(raw_text)
    severity = sev_match.group(0).lower() if sev_match else "unknown"

    error_signals: list[str] = []
    for hit in _ERROR_RE.findall(raw_text):
        token = hit.lower()
        if token not in error_signals:
            error_signals.append(token)

    return {
        "events": events,
        "services": services_seen,
        "error_signals": error_signals,
        "severity": severity,
    }


def _structured_dict_fast_path(raw) -> Incident | None:
    if isinstance(raw, dict) and any(
        k in raw for k in ("events", "services", "error_signals", "severity")
    ):
        return {
            "events": raw.get("events", []),
            "services": raw.get("services", []),
            "error_signals": raw.get("error_signals", []),
            "severity": raw.get("severity", "unknown"),
        }
    return None


def input_parser_node(state: PostmortemState) -> PostmortemState:
    raw = state.get("raw_input", "")
    start = time.perf_counter()

    fast = _structured_dict_fast_path(raw)
    if fast is not None:
        return attach_node_status(
            "parse",
            {"incident": fast},
            source="input",
            duration_s=time.perf_counter() - start,
        )

    baseline = _heuristic_parse(raw)
    if baseline["events"]:
        return attach_node_status(
            "parse",
            {"incident": baseline},
            source="heuristic",
            duration_s=time.perf_counter() - start,
        )

    def _llm() -> PostmortemState:
        llm = get_llm(temperature=0.0, timeout=25, num_predict=512).with_structured_output(
            ParsedIncident
        )
        parsed: ParsedIncident = (PROMPT | llm).invoke({"raw": _coerce_raw(raw)})

        llm_events = [e.model_dump() for e in parsed.events]
        merged: Incident = {
            "events": llm_events or baseline["events"],
            "services": parsed.services or baseline["services"],
            "error_signals": parsed.error_signals or baseline["error_signals"],
            "severity": parsed.severity
            if parsed.severity and parsed.severity != "unknown"
            else baseline["severity"],
        }
        return {"incident": merged}

    def _fallback() -> PostmortemState:
        return {"incident": baseline}

    return run_with_status("parse", _llm, _fallback)
