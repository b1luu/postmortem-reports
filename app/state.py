from __future__ import annotations

from typing import Annotated, Any, TypedDict


class TimelineEvent(TypedDict, total=False):
    id: str  # "e{i}" in input order, assigned by parse
    timestamp: str
    event: str
    source: str
    signals: list[str]  # Signal values; only on ordered_timeline entries


class Incident(TypedDict, total=False):
    events: list[TimelineEvent]
    services: list[str]
    error_signals: list[str]
    severity: str


def _merge_dicts(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class PostmortemState(TypedDict, total=False):
    raw_input: str | dict[str, Any] | list[Any]
    incident: Incident
    root_cause: str
    root_cause_confidence: str
    contributing_factors: list[str]
    ordered_timeline: list[TimelineEvent]
    # started/detected/resolved -> timestamp / event id, or None when the
    # input has no event supporting that point.
    inflection_points: dict[str, str | None]
    inflection_event_ids: dict[str, str | None]
    durations: dict[str, Any]
    root_cause_evidence: list[dict[str, Any]]
    report_markdown: str
    review_issues: list[str]
    review_passed: bool
    write_attempts: int
    node_status: Annotated[dict[str, dict[str, Any]], _merge_dicts]
