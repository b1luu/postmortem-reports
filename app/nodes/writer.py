import json

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import logger, timed_node
from app.state import PostmortemState

SYSTEM = """You are a staff SRE writing a formal incident postmortem in Markdown.
Use EXACTLY these section headers, in this order, and include all of them:

# Incident Postmortem

## Summary
## Impact
## Timeline
## Root Cause
## Contributing Factors
## Action Items

Rules:
- Summary: 2-4 sentences, plain English.
- Impact: services affected, severity, user-visible effects.
- Timeline: bulleted list with timestamps; call out started/detected/resolved.
- Root Cause: the primary cause and why.
- Contributing Factors: bulleted list.
- Action Items: 3-6 concrete, owner-agnostic follow-ups.
- Do not invent facts not supported by the input. If unknown, say so."""

HUMAN = """Incident:
{incident}

Ordered timeline:
{timeline}

Inflection points:
{inflection}

Root cause (with confidence={confidence}):
{root_cause}

Contributing factors:
{factors}
"""

PROMPT = ChatPromptTemplate.from_messages([("system", SYSTEM), ("human", HUMAN)])


def _fallback_report(state: PostmortemState) -> str:
    incident = state.get("incident", {})
    events = state.get("ordered_timeline", [])
    services = incident.get("services", [])
    severity = incident.get("severity", "unknown")
    factors = state.get("contributing_factors", [])
    root_cause = state.get("root_cause", "Unknown")
    inflection = state.get("inflection_points", {})

    timeline_lines = []
    for event in events:
        timeline_lines.append(f"- {event.get('timestamp', 'unknown')}: {event.get('event', 'unknown event')}")

    if inflection.get("started"):
        timeline_lines.append(f"- Started: {inflection['started']}")
    if inflection.get("detected"):
        timeline_lines.append(f"- Detected: {inflection['detected']}")
    if inflection.get("resolved"):
        timeline_lines.append(f"- Resolved: {inflection['resolved']}")

    factor_lines = "\n".join(f"- {factor}" for factor in factors) or "- None identified"
    service_text = ", ".join(services) if services else "Unknown"

    return f"""# Incident Postmortem

## Summary
An incident was analyzed from the provided input. This report may include heuristic fallbacks where model output was unavailable.

## Impact
Severity: {severity}
Services affected: {service_text}
User-visible effects: Unknown from the available input.

## Timeline
{chr(10).join(timeline_lines) or "- No timeline events were extracted."}

## Root Cause
{root_cause}

## Contributing Factors
{factor_lines}

## Action Items
- Add more structured incident fields to improve analysis quality.
- Capture explicit detection and resolution markers in the source data.
- Add service ownership and alert metadata to future incident inputs.
"""


def writer_node(state: PostmortemState) -> PostmortemState:
    def _run() -> PostmortemState:
        try:
            llm = get_llm(temperature=0.3)
            chain = PROMPT | llm
            msg = chain.invoke(
                {
                    "incident": json.dumps(state.get("incident", {}), indent=2, default=str),
                    "timeline": json.dumps(
                        state.get("ordered_timeline", []), indent=2, default=str
                    ),
                    "inflection": json.dumps(
                        state.get("inflection_points", {}), indent=2, default=str
                    ),
                    "confidence": state.get("root_cause_confidence", "unknown"),
                    "root_cause": state.get("root_cause", ""),
                    "factors": "\n".join(
                        f"- {f}" for f in state.get("contributing_factors", [])
                    )
                    or "- (none identified)",
                }
            )
            return {"report_markdown": msg.content if hasattr(msg, "content") else str(msg)}
        except Exception:
            logger.exception("writer_fallback heuristic=true")
            return {"report_markdown": _fallback_report(state)}

    return timed_node("write", _run)
