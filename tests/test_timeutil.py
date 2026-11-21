from datetime import datetime, timezone

import pytest

from app.timeutil import parse_ts

UTC = timezone.utc

PARSED = [
    ("2026-04-14T10:01:04.123456789Z", datetime(2026, 4, 14, 10, 1, 4, 123456, UTC)),
    ("2026-04-14T10:01:04.12345Z", datetime(2026, 4, 14, 10, 1, 4, 123450, UTC)),
    ("2026-04-14T10:01:04,123Z", datetime(2026, 4, 14, 10, 1, 4, 123000, UTC)),
    ("2026-04-14T10:01:04+0200", datetime(2026, 4, 14, 8, 1, 4, 0, UTC)),
    ("2026-04-14T10:01:04+02", datetime(2026, 4, 14, 8, 1, 4, 0, UTC)),
    ("20260414T100104Z", datetime(2026, 4, 14, 10, 1, 4, 0, UTC)),
    ("2026-04-14 10:01:04", datetime(2026, 4, 14, 10, 1, 4, 0, UTC)),
    ("2026-04-14T10:01:04", datetime(2026, 4, 14, 10, 1, 4, 0, UTC)),  # naive -> UTC
]

UNPARSEABLE = ["20260414", "2026-04-14T1001", "2026-W16-2", "2026-04-14+02:00", "garbage", ""]


@pytest.mark.parametrize("text,expected", PARSED, ids=[p[0] for p in PARSED])
def test_parses_to_utc(text, expected):
    parsed = parse_ts(text)
    assert parsed == expected
    assert parsed.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("text", UNPARSEABLE)
def test_rejects(text):
    assert parse_ts(text) is None
