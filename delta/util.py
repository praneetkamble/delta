from __future__ import annotations

from datetime import datetime, timedelta


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_dt(dt: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if dt.date() == now.date():
        return dt.strftime("today %I:%M %p").replace(" 0", " ")
    if dt.date() == (now + timedelta(days=1)).date():
        return dt.strftime("tomorrow %I:%M %p").replace(" 0", " ")
    return dt.strftime("%a %d %b %I:%M %p").replace(" 0", " ")


def fmt_duration(secs: float) -> str:
    secs = int(secs)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s and not h:
        parts.append(f"{s}s")
    return " ".join(parts) or "0s"
