from __future__ import annotations

from pydantic import BaseModel, Field


class TimelineEventModel(BaseModel):
    timestamp: str = Field(description="ISO 8601 or original timestamp string")
    event: str = Field(description="What happened")
    source: str = Field(default="", description="Service or log source, if known")


class ParsedIncident(BaseModel):
    events: list[TimelineEventModel] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    error_signals: list[str] = Field(
        default_factory=list,
        description="Key error messages, exceptions, or anomaly signals",
    )
    severity: str = Field(
        default="unknown",
        description="One of: sev1, sev2, sev3, sev4, unknown",
    )


class RootCause(BaseModel):
    root_cause: str = Field(description="The most likely root cause, one paragraph")
    confidence: str = Field(description="One of: high, medium, low")
    reasoning: str = Field(description="Why this is the most likely cause")


class ContributingFactors(BaseModel):
    factors: list[str] = Field(
        default_factory=list,
        description="Secondary factors: config issues, cascading failures, missing alerts, etc.",
    )


class InflectionPoints(BaseModel):
    started: str = Field(default="", description="Timestamp when the incident began")
    detected: str = Field(default="", description="Timestamp when detected")
    resolved: str = Field(default="", description="Timestamp when resolved")
