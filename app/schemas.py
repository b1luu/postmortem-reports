from __future__ import annotations

from typing import Literal

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


class Symptom(BaseModel):
    event_id: str = Field(description="Id of the event showing this symptom, e.g. e3")
    description: str = Field(description="The observed effect, in a few words")


class RootCauseDraft(BaseModel):
    """What the LLM returns. Code validates it and derives trigger_kind."""

    trigger: str = Field(description="One sentence naming what set the incident off")
    trigger_event_id: str | None = Field(
        default=None, description="Id of the triggering event, or null if none explains onset"
    )
    symptoms: list[Symptom] = Field(default_factory=list)
    evidence_event_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    reasoning: str = Field(description="2-4 sentences explaining the causal chain")


class RootCauseAnalysis(RootCauseDraft):
    """The validated analysis stored in state as root_cause_analysis."""

    trigger_kind: Literal["suspected_change", "first_signal", "unknown"]


class ContributingFactor(BaseModel):
    factor: str = Field(description="One secondary factor, one sentence")
    category: Literal["change", "resource", "dependency", "detection", "process", "other"]
    evidence_event_ids: list[str] = Field(default_factory=list)


class ContributingFactors(BaseModel):
    factors: list[ContributingFactor] = Field(default_factory=list)


class InflectionPoints(BaseModel):
    started: str = Field(default="", description="Timestamp when the incident began")
    detected: str = Field(default="", description="Timestamp when detected")
    resolved: str = Field(default="", description="Timestamp when resolved")
