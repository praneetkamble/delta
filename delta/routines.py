"""User-defined routines (macros) in YAML, with optional daily/weekday/weekly schedules."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

log = logging.getLogger("delta")
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class Schedule:
    kind: str                 # daily | weekdays | weekly
    hour: int
    minute: int
    weekday: int | None = None

    @staticmethod
    def parse(text: str) -> "Schedule":
        t = text.strip().lower()
        m = re.fullmatch(r"(daily|weekdays)\s+(\d{1,2}):(\d{2})", t)
        if m:
            return Schedule(m.group(1), int(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"weekly\s+(mon|tue|wed|thu|fri|sat|sun)\w*\s+(\d{1,2}):(\d{2})", t)
        if m:
            return Schedule("weekly", int(m.group(2)), int(m.group(3)), _DAYS.index(m.group(1)))
        raise ValueError(f"bad schedule {text!r} (use 'daily 08:30', 'weekdays 09:00' or 'weekly mon 18:00')")

    def is_due(self, now: datetime, grace: timedelta = timedelta(hours=2)) -> bool:
        """True during the `grace` window after the scheduled time on a matching day (the caller records 'ran today')."""
        if self.kind == "weekdays" and now.weekday() > 4:
            return False
        if self.kind == "weekly" and now.weekday() != self.weekday:
            return False
        at = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        return at <= now < at + grace


    def next_after(self, now: datetime) -> datetime:
        """The next time this schedule fires, strictly after `now` (ignores the 'already ran today' bookkeeping)."""
        for add in range(0, 9):
            day = (now + timedelta(days=add)).replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
            if day <= now:
                continue
            if self.kind == "weekdays" and day.weekday() > 4:
                continue
            if self.kind == "weekly" and day.weekday() != self.weekday:
                continue
            return day
        raise ValueError("no next run found")  # unreachable for valid schedules


@dataclass
class Routine:
    name: str
    description: str = ""
    steps: list[dict] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    schedule: Schedule | None = None
    schedule_text: str = ""


class RoutineBook:
    def __init__(self, routines: list[Routine] | None = None):
        self._r = {r.name.lower(): r for r in (routines or [])}
        self.warnings: list[str] = []

    def all(self) -> list[Routine]:
        return list(self._r.values())

    def find(self, name: str) -> Routine | None:
        n = re.sub(r"\s+", " ", name.strip().lower())
        n = re.sub(r"^(the|my)\s+", "", n)
        n = re.sub(r"\s+(routine|mode)$", "", n) if n not in self._r else n
        for r in self._r.values():
            names = {r.name.lower(), re.sub(r"\s+(routine|mode)$", "", r.name.lower())} | {t.lower() for t in r.triggers}
            if n in names or n + " mode" in names:
                return r
        return None

    @classmethod
    def load(cls, path: Path | str | None) -> "RoutineBook":
        book = cls()
        if not path or not Path(path).exists():
            return book
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            book.warnings.append(f"routines file is not valid YAML: {e}")
            return book
        for name, body in (raw.get("routines") or {}).items():
            try:
                steps = []
                for st in body.get("steps") or []:
                    if not isinstance(st, dict) or not (set(st) & {"do", "tool", "wait"}):
                        raise ValueError(f"step {st!r} needs 'do', 'tool' or 'wait'")
                    steps.append(st)
                sched_text = str(body.get("schedule") or "")
                book._r[str(name).lower()] = Routine(
                    str(name), str(body.get("description") or ""), steps, [str(t) for t in body.get("triggers") or []],
                    Schedule.parse(sched_text) if sched_text else None, sched_text)
            except (ValueError, AttributeError) as e:
                book.warnings.append(f"routine {name!r} skipped: {e}")
        for w in book.warnings:
            log.warning(w)
        return book

    def validate(self, registry) -> list[str]:
        problems = []
        for r in self.all():
            for st in r.steps:
                if "tool" in st and registry.get(st["tool"]) is None:
                    problems.append(f"{r.name}: unknown tool {st['tool']!r}")
        return problems
