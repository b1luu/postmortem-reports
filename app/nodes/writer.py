import json
import os
import time

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_llm
from app.runtime import attach_node_status, run_with_status
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
_ENABLE_WRITER_LLM = os.getenv("POSTMORTEM_ENABLE_WRITER_LLM", "").lower() in {
    "1",
    "true",
    "yes",
}


def _fallback_report(state: PostmortemState) -> str:
    incident = state.get("incident", {})
    events = state.get("ordered_timeline", []) or incident.get("events", [])
    services = incident.get("services", [])
    severity = incident.get("severity", "unknown")
    factors = state.get("contributing_factors", [])
    root_cause = state.get("root_cause", "Unknown")
    inflection = state.get("inflection_points", {})

    timeline_lines = [
        f"- {ev.get('timestamp', 'unknown')}"
        + (f" [{ev.get('source')}]" if ev.get("source") else "")
        + f": {ev.get('event', 'unknown event')}"
        for ev in events
    ]
    if inflection.get("started"):
        timeline_lines.append(f"- **Started:** {inflection['started']}")
    if inflection.get("detected"):
        timeline_lines.append(f"- **Detected:** {inflection['detected']}")
    if inflection.get("resolved"):
        timeline_lines.append(f"- **Resolved:** {inflection['resolved']}")

    service_text = ", ".join(services) if services else "unknown"
    summary = (
        f"A {severity} incident affected {service_text}. "
        f"{len(events)} timeline events were observed"
    )
    if inflection.get("started") and inflection.get("resolved"):
        summary += f" between {inflection['started']} and {inflection['resolved']}"
    summary += ". This report was produced from the deterministic heuristic path for faster turnaround."

    factor_lines = (
        "\n".join(f"- {f}" for f in factors) if factors else "- None identified"
    )

    event_text = " ".join(str(ev.get("event", "")) for ev in events).lower()
    actions: list[str] = []
    if "pool" in event_text or "exhaust" in event_text:
        actions.append(
            "Review and raise connection pool / resource limits for affected services, and add utilization alerts."
        )
    if "deploy" in event_text or "rollback" in event_text:
        actions.append(
            "Add pre-deployment canary checks and automated rollback gates tied to error-rate SLOs."
        )
    if (
        inflection.get("started")
        and inflection.get("detected")
        and inflection["started"] != inflection["detected"]
    ):
        actions.append(
            f"Close detection gap ({inflection['started']} → {inflection['detected']}) by alerting on the error signals observed before paging."
        )
    if len(services) > 1:
        actions.append(
            "Audit cross-service dependencies to reduce blast radius of single-service failures."
        )
    if not actions:
        actions = [
            "Add structured incident fields (severity, owners, impact) to improve future analysis quality.",
            "Capture explicit detection and resolution markers in the source data.",
            "Add service ownership and alert metadata to future incident inputs.",
        ]

    action_lines = "\n".join(f"- {a}" for a in actions)

    return f"""# Incident Postmortem

## Summary
{summary}

## Impact
- Severity: {severity}
- Services affected: {service_text}
- User-visible effects: not determinable from the available input.

## Timeline
{chr(10).join(timeline_lines) or "- No timeline events were extracted."}

## Root Cause
{root_cause}

## Contributing Factors
{factor_lines}

## Action Items
{action_lines}
"""


def writer_node(state: PostmortemState) -> PostmortemState:
    start = time.perf_counter()
    if not _ENABLE_WRITER_LLM:
        return attach_node_status(
            "write",
            {"report_markdown": _fallback_report(state)},
            source="heuristic",
            duration_s=time.perf_counter() - start,
        )

    def _llm() -> PostmortemState:
        llm = get_llm(temperature=0.3, timeout=45, num_predict=1200)
        chain = PROMPT | llm
        msg = chain.invoke(
            {
                "incident": json.dumps(
                    state.get("incident", {}), indent=2, default=str
                ),
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
        content = msg.content if hasattr(msg, "content") else str(msg)
        if not content or "## Summary" not in content:
            raise ValueError("writer output missing required sections")
        return {"report_markdown": content}

    def _fallback() -> PostmortemState:
        return {"report_markdown": _fallback_report(state)}

    return run_with_status("write", _llm, _fallback)
