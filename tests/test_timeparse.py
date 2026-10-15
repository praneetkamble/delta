from datetime import datetime, timedelta

import pytest

from delta.timeparse import parse_duration, parse_when

NOW = datetime(2026, 10, 15, 10, 0, 0)  # a Thursday


@pytest.mark.parametrize("text,secs", [
    ("5 minutes", 300), ("5 min", 300), ("1h30m", 5400), ("1 hour 30 minutes", 5400), ("90 seconds", 90),
    ("an hour", 3600), ("half an hour", 1800), ("2 hrs", 7200), ("1.5 hours", 5400),
])
def test_parse_duration_ok(text, secs):
    assert parse_duration(text) == timedelta(seconds=secs)


@pytest.mark.parametrize("text", ["", "soon", "5 parsecs", "banana 5 minutes", "0 minutes"])
def test_parse_duration_rejects(text):
    assert parse_duration(text) is None


@pytest.mark.parametrize("text,expected", [
    ("in 10 minutes", NOW + timedelta(minutes=10)),
    ("at 5pm", datetime(2026, 10, 15, 17, 0)),
    ("at 5:30 pm", datetime(2026, 10, 15, 17, 30)),
    ("at 17:45", datetime(2026, 10, 15, 17, 45)),
    ("at 9am", datetime(2026, 10, 16, 9, 0)),          # already past today -> tomorrow
    ("tomorrow at 9", datetime(2026, 10, 16, 9, 0)),
    ("tomorrow", datetime(2026, 10, 16, 9, 0)),
    ("tomorrow 7:30 am", datetime(2026, 10, 16, 7, 30)),
    ("today at 6pm", datetime(2026, 10, 15, 18, 0)),
    ("on monday at 8am", datetime(2026, 10, 19, 8, 0)),
])
def test_parse_when_ok(text, expected):
    assert parse_when(text, NOW) == expected


@pytest.mark.parametrize("text", ["at work in 10 minutes", "at 25:00", "at 13pm", "today at 8am", "whenever", "in banana", ""])
def test_parse_when_is_strict(text):
    assert parse_when(text, NOW) is None
