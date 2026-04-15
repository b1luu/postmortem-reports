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
    durations = state.get("durations", {}) or {}
    evidence = state.get("root_cause_evidence", []) or []
    confidence = state.get("root_cause_confidence", "unknown")

    timeline_lines = []
    for ev in events:
        marker = ""
        ts = ev.get("timestamp", "")
        if ts and ts == inflection.get("started"):
            marker = " **[started]**"
        elif ts and ts == inflection.get("detected"):
            marker = " **[detected]**"
        elif ts and ts == inflection.get("resolved"):
            marker = " **[resolved]**"
        timeline_lines.append(
            f"- `{ts or 'unknown'}`"
            + (f" *{ev.get('source')}*" if ev.get("source") else "")
            + f" — {ev.get('event', 'unknown event')}{marker}"
        )

    service_text = ", ".join(services) if services else "unknown"
    mttd_h = durations.get("mttd_human")
    mttr_h = durations.get("mttr_human")
    total_h = durations.get("total_human")

    summary_parts = [
        f"A **{severity}** incident affected {service_text}.",
        f"{len(events)} timeline events were observed",
    ]
    if inflection.get("started") and inflection.get("resolved"):
        summary_parts[-1] += f" between {inflection['started']} and {inflection['resolved']}"
    summary_parts[-1] += "."
    if total_h:
        summary_parts.append(f"Total incident duration: **{total_h}**.")
    if mttd_h:
        summary_parts.append(f"Time to detect (MTTD): **{mttd_h}**.")
    if mttr_h:
        summary_parts.append(f"Time to resolve after detection (MTTR): **{mttr_h}**.")
    summary = " ".join(summary_parts)

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
    generic = [
        "Document the detection signal and update the relevant runbook for on-call engineers.",
        "Add SLO-backed alerts on the leading indicators observed in this incident's timeline.",
        "Capture explicit detection and resolution markers in the source data for future analyses.",
        "Add service ownership and alert metadata to incident intake to shorten triage.",
    ]
    seen = set(actions)
    for g in generic:
        if len(actions) >= 3:
            break
        if g not in seen:
            actions.append(g)
            seen.add(g)

    action_lines = "\n".join(f"- {a}" for a in actions)

    impact_lines = [
        f"- **Severity:** {severity}",
        f"- **Services affected:** {service_text}",
    ]
    if total_h:
        impact_lines.append(f"- **Incident duration:** {total_h}")
    if mttd_h:
        impact_lines.append(f"- **MTTD:** {mttd_h}")
    if mttr_h:
        impact_lines.append(f"- **MTTR:** {mttr_h}")
    impact_lines.append(
        "- **User-visible effects:** inferred from affected services; not independently verified."
    )

    evidence_block = ""
    if evidence:
        evidence_lines = "\n".join(
            f"- `{e.get('timestamp', '')}`"
            + (f" *{e.get('source')}*" if e.get("source") else "")
            + f" — {e.get('event', '')}"
            for e in evidence
        )
        evidence_block = (
            f"\n\n**Supporting evidence ({len(evidence)} events, "
            f"confidence: {confidence}):**\n{evidence_lines}"
        )

    return f"""# Incident Postmortem

## Summary
{summary}

## Impact
{chr(10).join(impact_lines)}

## Timeline
{chr(10).join(timeline_lines) or "- No timeline events were extracted."}

## Root Cause
{root_cause}{evidence_block}

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
