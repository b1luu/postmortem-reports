"""Timestamp parsing that behaves the same on Python 3.10 and 3.12.

3.11 widened ``datetime.fromisoformat``; this normalises the common log
variants first and then gates on the subset 3.10 accepts, so both versions
agree on what parses.
"""

import re
from datetime import datetime, timezone

_BASIC_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(.*)$")
_ZULU_RE = re.compile(r"[Zz]$")
_FRACTION_RE = re.compile(r"^(.+?[T ]\d{2}:\d{2}:\d{2})[.,](\d+)(.*)$")
_OFFSET_RE = re.compile(r"^(.*\d{2}:\d{2}(?::\d{2}(?:\.\d{6})?)?)([+-]\d{2}):?(\d{2})?$")
_GATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{6})?)?(?:[+-]\d{2}:\d{2})?)?$"
)


def parse_ts(ts: object) -> datetime | None:
    """Parse a log timestamp to an aware UTC datetime, or None."""
    s = str(ts).strip()
    if not s:
        return None
    m = _BASIC_RE.match(s)
    if m:
        s = f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}{m[7]}"
    s = _ZULU_RE.sub("+00:00", s)
    m = _FRACTION_RE.match(s)
    if m:
        s = m[1] + "." + m[2][:6].ljust(6, "0") + m[3]
    m = _OFFSET_RE.match(s)
    if m:
        s = m[1] + m[2] + ":" + (m[3] or "00")
    if not _GATE_RE.fullmatch(s):
        return None
    try:
        parsed = datetime.fromisoformat(s)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
