"""Facts pack for LLM prompts, and code-side validation of what the LLM returns."""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.schemas import (
    ContributingFactor,
    ContributingFactors,
    RootCauseAnalysis,
    RootCauseDraft,
    Symptom,
)
from app.signals import Signal, display_text, event_signals, signal_values
from app.timeutil import parse_ts

MAX_EVENT_CHARS = 300
MAX_FACTORS = 6
NO_TRIGGER_TEXT = "No single triggering event identified"
_TIMESTAMP_RE = re.compile(
    r"(?<![\d.:/-])\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?"
    r"|(?<!\d)\d{8}T\d{4,6}Z?"
    r"|(?<![\d:.])(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?!\d)"
    r"|(?<![\w.:-])(?:0?[1-9]|1[0-2])\s?[AaPp]\.?[Mm]\b"
    r"|(?<![\w.:-])(?:[01]\d|2[0-3])[0-5]\d\s?(?:UTC|GMT|Z)\b"
    r"|(?<![\d.:/-])\d{1,2}/\d{1,2}/\d{4}(?!\d)"
    r"|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}\b"
)
_EVENT_ID_RE = re.compile(r"\b[eE]\d+\b")
_NULL_IDS = {"", "null", "none"}
_NOT_CITABLE = {Signal.DETECTION, Signal.RESOLUTION}
CAUSE_SIGNALS = {Signal.ERROR, Signal.PRECURSOR}
_CONFIDENCE_ORDER = ("low", "medium", "high")


def one_line(text: Any) -> str:
    return " ".join(str(text).split())


def detection_gap_text(mttd_human: Any) -> str:
    return (
        f"Alerting fired {mttd_human} after the first error or degradation signal, "
        "indicating a detection gap."
    )


def facts_pack(state: Mapping, *, with_timestamps: bool = False) -> dict[str, Any]:
    events = state.get("ordered_timeline") or []
    parsed = [parse_ts(ev.get("timestamp", "")) for ev in events]
    base = next((ts for ts in parsed if ts is not None), None)
    timeline = []
    for ev, ts in zip(events, parsed):
        item: dict[str, Any] = {
            "id": ev.get("id"),
            "t_plus_s": int((ts - base).total_seconds()) if ts is not None else None,
            "source": ev.get("source", ""),
            "event": str(ev.get("event", ""))[:MAX_EVENT_CHARS],
            "signals": list(ev.get("signals") or []),
        }
        if with_timestamps:
            item["timestamp"] = ev.get("timestamp", "")
        timeline.append(item)

    durations = state.get("durations") or {}
    if not with_timestamps:
        # Warnings contain timestamps, so only their presence is passed on.
        durations = {
            "mttd_seconds": durations.get("mttd_seconds"),
            "mttr_seconds": durations.get("mttr_seconds"),
            "total_seconds": durations.get("total_seconds"),
            "timing_conflict": bool(durations.get("warnings")),
        }
    return {
        "ordered_timeline": timeline,
        "inflection_event_ids": state.get("inflection_event_ids") or {},
        "durations": durations,
    }


def prompt_json(value: Any) -> str:
    """JSON for a prompt; "<" is escaped so log text cannot close a delimiter tag."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")


def events_after(trigger_ev: Mapping, events: Sequence[Mapping]) -> list[Mapping]:
    """Events after the trigger in timeline order; equal timestamps keep log order.

    Unparseable events sort last, so their position proves nothing when the
    trigger has a real timestamp.
    """
    position = next(i for i, ev in enumerate(events) if ev is trigger_ev)
    later = list(events[position + 1 :])
    if parse_ts(trigger_ev.get("timestamp", "")) is None:
        return later
    return [ev for ev in later if parse_ts(ev.get("timestamp", "")) is not None]


def _text_problem(
    text: str, index: Mapping[str, Mapping], cited: Sequence[Mapping]
) -> str | None:
    cited_text = [str(ev.get("event", "")) for ev in cited]
    cited_times = {m.group(0) for t in cited_text for m in _TIMESTAMP_RE.finditer(t)}
    cited_tokens = {m.group(0) for t in cited_text for m in _EVENT_ID_RE.finditer(t)}
    for match in _TIMESTAMP_RE.finditer(text):
        if match.group(0) not in cited_times:
            return f"free text contains a timestamp not quoted from a cited event: {match.group(0)}"
    for match in _EVENT_ID_RE.finditer(text):
        token = match.group(0)
        if token.lower() not in index and token not in cited_tokens:
            return f"free text references an unknown event id: {token}"
    return None


def _citable(ids: Sequence[str], index: Mapping[str, Mapping], excluded: set) -> list[str]:
    """Known, citable, not excluded, de-duplicated, in timeline order."""
    wanted = set(ids)
    return [
        eid
        for eid, ev in index.items()
        if eid in wanted and eid not in excluded and not event_signals(ev) & _NOT_CITABLE
    ]


def _check_trigger(trigger_id: str, index: Mapping[str, Mapping], started_id: str | None) -> None:
    if trigger_id not in index:
        raise ValueError(f"trigger {trigger_id} is not a known event")
    if event_signals(index[trigger_id]) & _NOT_CITABLE:
        raise ValueError(f"trigger {trigger_id} is a detection or resolution event")
    if started_id is None or trigger_id == started_id:
        return
    trigger_ts = parse_ts(index[trigger_id].get("timestamp", ""))
    if trigger_ts is None:
        raise ValueError(f"trigger {trigger_id} has an unparseable timestamp")
    started_ts = parse_ts(index[started_id].get("timestamp", "")) if started_id in index else None
    if started_ts is None:
        raise ValueError(f"started event {started_id} has an unparseable timestamp")
    if trigger_ts > started_ts:
        raise ValueError(f"trigger {trigger_id} is after the started event {started_id}")


def _trigger_kind(ev: Mapping | None) -> str:
    if ev is None:
        return "unknown"
    signals = event_signals(ev)
    if Signal.CHANGE in signals:
        return "suspected_change"
    return "first_signal" if signals & CAUSE_SIGNALS else "unknown"


def validate_root_cause(
    draft: RootCauseDraft, events: Sequence[Mapping], started_id: str | None
) -> RootCauseAnalysis:
    index = {ev["id"]: ev for ev in events if ev.get("id")}

    trigger_id: str | None = (draft.trigger_event_id or "").strip()
    if trigger_id.lower() in _NULL_IDS:
        trigger_id = None
    if trigger_id is not None:
        _check_trigger(trigger_id, index, started_id)
    trigger_ev = index[trigger_id] if trigger_id is not None else None
    kind = _trigger_kind(trigger_ev)

    # A deploy can't be its own proof; an error or degradation trigger can be cited.
    not_evidence = set()
    if trigger_ev is not None and not event_signals(trigger_ev) & CAUSE_SIGNALS:
        not_evidence.add(trigger_id)
    evidence = _citable(draft.evidence_event_ids, index, not_evidence)
    if not evidence:
        raise ValueError("no valid evidence events after validation")

    # The model's trigger and symptom wording is discarded: stored text is the cited event's.
    symptom_ids = {symptom.event_id for symptom in draft.symptoms}
    candidates = events_after(trigger_ev, events) if trigger_ev is not None else events
    symptom_events = [
        ev
        for ev in candidates
        if ev.get("id") in symptom_ids and not event_signals(ev) & _NOT_CITABLE
    ]
    symptoms = [
        Symptom(event_id=ev["id"], description=one_line(display_text(str(ev.get("event", "")))))
        for ev in symptom_events
    ]

    if trigger_ev is None:
        trigger = NO_TRIGGER_TEXT
    else:
        trigger = one_line(display_text(str(trigger_ev.get("event", ""))))
    reasoning = one_line(draft.reasoning)

    evidence_events = [index[eid] for eid in evidence]
    cited = [*([trigger_ev] if trigger_ev is not None else []), *evidence_events, *symptom_events]
    problem = _text_problem(reasoning, index, cited)
    if problem:
        raise ValueError(problem)

    strong = sum(1 for ev in evidence_events if event_signals(ev) & CAUSE_SIGNALS)
    if strong < 2 or kind == "unknown" or started_id is None:
        cap = "low"
    else:
        cap = "medium" if strong == 2 else "high"
    confidence = min(draft.confidence, cap, key=_CONFIDENCE_ORDER.index)

    return RootCauseAnalysis(
        trigger=trigger,
        trigger_event_id=trigger_id,
        trigger_kind=kind,
        symptoms=symptoms,
        evidence_event_ids=evidence,
        confidence=confidence,
        reasoning=reasoning,
    )


def excluded_factor_ids(analysis: Mapping) -> list[str]:
    ids = [analysis.get("trigger_event_id")]
    ids += [s.get("event_id") for s in analysis.get("symptoms") or []]
    return [i for i in ids if i]


def validate_factors(
    draft: ContributingFactors,
    analysis: Mapping,
    events: Sequence[Mapping],
    durations: Mapping,
) -> list[ContributingFactor]:
    index = {ev["id"]: ev for ev in events if ev.get("id")}
    excluded = set(excluded_factor_ids(analysis))
    kept: list[ContributingFactor] = []
    measured_added = False
    for item in draft.factors:
        ids = _citable(item.evidence_event_ids, index, excluded)
        if not ids:
            # The model's text is never used here: only the measured delay is stated.
            if (
                item.category == "detection"
                and (durations.get("mttd_seconds") or 0) > 0
                and not measured_added
            ):
                kept.append(
                    ContributingFactor(
                        factor=detection_gap_text(durations.get("mttd_human")),
                        category="detection",
                        evidence_event_ids=[],
                    )
                )
                measured_added = True
            continue
        text = one_line(item.factor)
        if not text or _text_problem(text, index, [index[eid] for eid in ids]):
            continue
        kept.append(ContributingFactor(factor=text, category=item.category, evidence_event_ids=ids))
    if draft.factors and not kept:
        raise ValueError("no valid factors after validation")
    return kept[:MAX_FACTORS]


def render_root_cause(
    analysis: Mapping, trigger_ev: Mapping | None, symptom_ev: Mapping | None
) -> str:
    def _clean(text: Any) -> str:
        collapsed = one_line(text)
        return collapsed.rstrip(" .") or collapsed

    def _at(ev: Mapping) -> str:
        ts = ev.get("timestamp") or "unknown time"
        src = ev.get("source", "")
        return f" (at {ts}, source={src})" if src else f" (at {ts})"

    if trigger_ev is not None:
        headline = _clean(display_text(str(trigger_ev.get("event", "")))) + _at(trigger_ev)
    else:
        headline = _clean(analysis["trigger"])
    line = f"Most likely root cause: {headline}"
    if analysis["trigger_kind"] == "suspected_change":
        line += ", a change that preceded onset"
    line += "."
    if symptom_ev is not None:
        symptom = _clean(display_text(str(symptom_ev.get("event", ""))))
        line += f" First symptom: {symptom}{_at(symptom_ev)}."
    return f"{line}\n\n_Reasoning:_ {analysis['reasoning']}"


def evidence_item(ev: Mapping) -> dict[str, Any]:
    return {
        "id": ev.get("id"),
        "timestamp": ev.get("timestamp", ""),
        "source": ev.get("source", ""),
        "event": ev.get("event", ""),
        "signals": signal_values(event_signals(ev)),
    }
