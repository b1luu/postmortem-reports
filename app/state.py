from __future__ import annotations

from typing import Annotated, Any, TypedDict


class TimelineEvent(TypedDict, total=False):
    timestamp: str
    event: str
    source: str


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
    inflection_points: dict[str, str]
    report_markdown: str
    review_issues: list[str]
    review_passed: bool
    node_status: Annotated[dict[str, dict[str, Any]], _merge_dicts]
