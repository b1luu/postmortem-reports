from __future__ import annotations

from typing import Any, TypedDict


class TimelineEvent(TypedDict, total=False):
    timestamp: str
    event: str
    source: str


class Incident(TypedDict, total=False):
    events: list[TimelineEvent]
    services: list[str]
    error_signals: list[str]
    severity: str


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
