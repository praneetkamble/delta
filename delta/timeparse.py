"""Small, strict natural-language time parser (no dependencies).

parse_when() only returns a value when the WHOLE text is understood, so callers can try several
split points ("remind me to meet at work in 10 minutes") and pick the one that parses.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_UNITS = {
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
}
_DUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)(?![a-z])", re.I)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_duration(text: str) -> timedelta | None:
    t = text.lower().strip()
    if not t:
        return None
    if re.fullmatch(r"(an?|one)\s+hour", t):
        return timedelta(hours=1)
    if re.fullmatch(r"half\s+an?\s+hour", t):
        return timedelta(minutes=30)
    if re.fullmatch(r"(an?|one)\s+min(ute)?", t):
        return timedelta(minutes=1)
    t2 = _DUR_RE.sub("", t)
    t2 = re.sub(r"\b(and|for|a|an)\b|[,\s]", "", t2)
    parts = _DUR_RE.findall(t)
    if not parts or t2:
        return None
    secs = sum(float(n) * _UNITS[u.lower()] for n, u in parts)
    return timedelta(seconds=secs) if secs > 0 else None


def _parse_clock(s: str) -> tuple[int, int] | None:
    s = s.strip().lower()
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if mi > 59:
        return None
    if ap:
        if not 1 <= h <= 12:
            return None
        ap = ap.replace(".", "")
        h = h % 12 + (12 if ap == "pm" else 0)
    elif h > 23:
        return None
    return h, mi


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now()
    t = re.sub(r"\s+", " ", text.lower().strip().rstrip(".!"))
    if not t:
        return None
    m = re.fullmatch(r"in (.+)", t)
    if m:
        d = parse_duration(m.group(1))
        return now + d if d else None
    day_offset: int | None = None
    rest = t
    m = re.fullmatch(r"(today|tomorrow|tonight)(?: (?:at )?(.+))?", t)
    if m:
        day_offset = {"today": 0, "tonight": 0, "tomorrow": 1}[m.group(1)]
        rest = m.group(2) or ("9:00 pm" if m.group(1) == "tonight" else "9:00")
    else:
        m = re.fullmatch(r"(?:on |next )?(" + "|".join(_WEEKDAYS) + r")(?: (?:at )?(.+))?", t)
        if m:
            target = _WEEKDAYS.index(m.group(1))
            day_offset = (target - now.weekday()) % 7 or 7
            rest = m.group(2) or "9:00"
        else:
            m = re.fullmatch(r"at (.+)", t)
            if m:
                rest = m.group(1)
            else:
                return None
    clock = _parse_clock(rest)
    if not clock:
        return None
    dt = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    if day_offset is not None:
        dt += timedelta(days=day_offset)
        if day_offset == 0 and dt <= now:
            return None
    elif dt <= now:
        dt += timedelta(days=1)
    return dt
