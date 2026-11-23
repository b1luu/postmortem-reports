"""Event classification: the single source of incident keywords.

Every node that needs to know whether an event is an error, an alert, a fix,
etc. asks ``classify`` / ``event_signals`` rather than keeping its own list.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum

from app.timeutil import parse_ts


class Signal(str, Enum):
    CHANGE = "change"
    PRECURSOR = "precursor"
    ERROR = "error"
    DETECTION = "detection"
    RESOLUTION = "resolution"
    MITIGATION = "mitigation"

    def __str__(self) -> str:
        return self.value


_ALTERNATIVES: dict[Signal, str] = {
    Signal.CHANGE: (
        r"deploy(?:s|ed|ing|ment)?|redeploy(?:ed)?|release[sd]?\s+v?\d[\w.-]*"
        r"|rolled out|rolling out|rollout"
        r"|config(?:uration)? (?:change[sd]?|push(?:ed|es)?|update[sd]?)"
        r"|migrat(?:ion|ed|ing)|feature flag|flag (?:enabled|flipped|toggled)|upgrade[sd]?"
    ),
    Signal.PRECURSOR: (
        r"(?:consumer|replication|replica) lag|lag(?:ging)? (?:\d+|behind|growing)"
        r"|backlog|queue depth|latency|slow(?:ness|down)?|degraded|saturat(?:ed|ion)"
        r"|near(?:ing)? (?:limit|capacity)"
        r"|cert(?:ificate)? (?:expir(?:es|ing|ed)|has expired)|retr(?:y|ies|ying)"
    ),
    Signal.ERROR: (
        r"errors?|exceptions?|fail(?:s|ed|ing|ure|ures)?|exhausted|exhaustion"
        r"|timeouts?|timed out|unavailable|unreachable|unresponsive"
        r"|crash(?:ed|es|ing)?|panic(?:ked)?|fatal|oom(?:killed)?|out of memory"
        r"|refused|5\d\d"
    ),
    Signal.DETECTION: (
        r"alert(?:s|ed|ing)?|alarm(?:s|ed)?|paged|paging|pagerduty|opsgenie"
        r"|on-?call (?:paged|notified|ack(?:ed|nowledged)?)|acknowledged"
        r"|incident (?:declared|opened|created)"
    ),
    Signal.RESOLUTION: (
        r"resolved|recovered|recovery complete|mitigated"
        r"|(?:back|returned) to (?:normal|baseline)|resumed|drained"
        r"|rollback completed?|all clear|incident closed"
    ),
    Signal.MITIGATION: (
        r"roll(?:ing|ed)? back|rollback|revert(?:ed|ing)?|fail(?:ing|ed)? over|failover"
        r"|scaled|scaling (?:up|out)|rotated|rotating|restart(?:ed|ing)?"
        r"|hotfix(?:ed)?|throttl(?:ed|ing)|load shedding"
    ),
}

PATTERNS: dict[Signal, re.Pattern] = {
    sig: re.compile(rf"\b(?:{alt})\b", re.IGNORECASE) for sig, alt in _ALTERNATIVES.items()
}
RESOURCE_RE = re.compile(r"\b(?:pool|exhaust\w*)\b", re.IGNORECASE)
NEGATION_BEFORE_RE = re.compile(
    r"(?:\b(?:no|not|never|without|zero|0|yet to|failed to)\b|n't)(?:\s+\S+){0,2}\s+$",
    re.IGNORECASE,
)
STILL_BEFORE_RE = re.compile(r"\bstill(?:\s+\S+){0,2}\s+$", re.IGNORECASE)
STILL_AFTER_RE = re.compile(r"^\s*(?:\S+\s+)?still\b", re.IGNORECASE)
# Case-sensitive on purpose: only strip an upper-case log level prefix.
LEVEL_PREFIX_RE = re.compile(r"^(?:TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\s+")

_INCIDENT_RE = re.compile(r"\bincident\b", re.IGNORECASE)

_NEGATABLE = (Signal.RESOLUTION, Signal.ERROR)


def classify(text: str) -> frozenset[Signal]:
    surviving: dict[Signal, list[re.Match]] = {}
    for sig, pattern in PATTERNS.items():
        matches = list(pattern.finditer(text))
        if sig in _NEGATABLE:
            matches = [m for m in matches if not NEGATION_BEFORE_RE.search(text[: m.start()])]
        surviving[sig] = matches

    out = {sig for sig, matches in surviving.items() if matches}

    # "recovered; errors still elevated" is not a resolution.
    if any(
        STILL_BEFORE_RE.search(text[: m.start()]) or STILL_AFTER_RE.search(text[m.end() :])
        for sig in (Signal.ERROR, Signal.PRECURSOR)
        for m in surviving[sig]
    ):
        out.discard(Signal.RESOLUTION)

    if Signal.RESOLUTION in out:
        out -= {Signal.ERROR, Signal.PRECURSOR, Signal.DETECTION}
    if Signal.DETECTION in out:
        out -= {Signal.ERROR, Signal.PRECURSOR}
    if Signal.ERROR in out:
        out.discard(Signal.PRECURSOR)
    if Signal.MITIGATION in out:
        out.discard(Signal.CHANGE)
    return frozenset(out)


def signal_values(signals: Iterable[Signal]) -> list[str]:
    present = set(signals)
    return [sig.value for sig in Signal if sig in present]


def event_signals(ev: Mapping) -> frozenset[Signal]:
    if "signals" in ev:
        return frozenset(Signal(s) for s in ev["signals"])
    return classify(str(ev.get("event", "")))


def latest_change_before(
    events: Sequence[Mapping], started_id: str | None, window_s: float = 1800
) -> Mapping | None:
    """The most recent CHANGE event at or before the started event, within window_s."""
    if started_id is None:
        return None
    started = next((ev for ev in events if ev.get("id") == started_id), None)
    if started is None:
        return None
    started_ts = parse_ts(started.get("timestamp", ""))
    if started_ts is None:
        return None

    best = None
    best_ts = None
    for ev in events:
        if ev.get("id") == started_id or Signal.CHANGE not in event_signals(ev):
            continue
        ts = parse_ts(ev.get("timestamp", ""))
        if ts is None or not 0 <= (started_ts - ts).total_seconds() <= window_s:
            continue
        if best_ts is None or ts >= best_ts:  # ">=": later list position wins ties
            best, best_ts = ev, ts
    return best


def is_alert_event(ev: Mapping) -> bool:
    """An alert, or the alert lifecycle closing ("alert resolved", "incident resolved")."""
    signals = event_signals(ev)
    if Signal.DETECTION in signals:
        return True
    text = str(ev.get("event", ""))
    return Signal.RESOLUTION in signals and bool(
        PATTERNS[Signal.DETECTION].search(text) or _INCIDENT_RE.search(text)
    )


def affected_services(services: Iterable[str], events: Sequence[Mapping]) -> list[str]:
    """Services without monitoring sources: those that only report on alerts."""
    kept: list[str] = []
    for service in services:
        own = [ev for ev in events if ev.get("source") == service]
        monitoring = (
            bool(own)
            and all(is_alert_event(ev) for ev in own)
            and any(PATTERNS[Signal.DETECTION].search(str(ev.get("event", ""))) for ev in own)
        )
        if not monitoring:
            kept.append(service)
    return kept


def error_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for m in PATTERNS[Signal.ERROR].finditer(text):
        token = m.group(0).lower()
        if token not in tokens:
            tokens.append(token)
    return tokens


def display_text(text: str) -> str:
    """Event text without a leading log level, for display only."""
    return LEVEL_PREFIX_RE.sub("", text.strip(), count=1)
