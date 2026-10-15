"""Reminders, timers, alarms (persisted in SQLite; fired by the scheduler as desktop toasts)."""
from __future__ import annotations

from datetime import datetime

from ..registry import I, Tool, ToolRegistry, fail, obj, ok, S
from ..timeparse import parse_duration, parse_when
from ..util import fmt_dt, fmt_duration


def _parse_any(ctx, when: str) -> datetime | None:
    now = ctx.now()
    dt = parse_when(when, now)
    if dt:
        return dt
    try:  # ISO timestamps from an LLM
        iso = datetime.fromisoformat(when.strip())
        return iso if iso.tzinfo is None else iso.astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def set_reminder(ctx, text: str, when: str, kind: str = "reminder"):
    dt = _parse_any(ctx, when)
    if not dt:
        return fail(f"I couldn't understand the time “{when}”. Try “in 20 minutes”, “at 5pm” or “tomorrow at 9”.")
    if dt <= ctx.now():
        return fail("That time is in the past.")
    rid = ctx.memory.add_reminder(text, dt, kind)
    return ok(f"Okay, I'll remind you to {text} {fmt_dt(dt, ctx.now())}. (#{rid})", id=rid, due=dt.isoformat())


def set_timer(ctx, duration: str, label: str = "Timer"):
    d = parse_duration(duration)
    if not d:
        return fail(f"I couldn't understand the duration “{duration}”. Try “10 minutes” or “1h30m”.")
    dt = ctx.now() + d
    rid = ctx.memory.add_reminder(label or "Timer", dt, "timer")
    return ok(f"Timer set for {fmt_duration(d.total_seconds())} (rings {fmt_dt(dt, ctx.now())}). (#{rid})", id=rid, due=dt.isoformat())


def set_alarm(ctx, time: str, label: str = "Alarm"):
    when = time if time.lower().startswith(("at ", "tomorrow", "today", "on ", "in ")) else "at " + time
    dt = _parse_any(ctx, when)
    if not dt:
        return fail(f"I couldn't understand the time “{time}”. Try “7:30 am” or “tomorrow at 6”.")
    rid = ctx.memory.add_reminder(label or "Alarm", dt, "alarm")
    return ok(f"Alarm set for {fmt_dt(dt, ctx.now())}. (#{rid})", id=rid, due=dt.isoformat())


def list_reminders(ctx):
    rows = ctx.memory.reminders("pending")
    if not rows:
        return ok("You have no pending reminders, timers or alarms.", reminders=[])
    now = ctx.now()
    lines = [f"#{r['id']} {r['kind']}: {r['text']} — {fmt_dt(datetime.fromtimestamp(r['due_ts']), now)}" for r in rows]
    return ok("Pending:\n" + "\n".join(lines), reminders=rows)


def cancel_reminder(ctx, id: int):
    return ok(f"Cancelled #{id}.") if ctx.memory.cancel_reminder(id) else fail(f"No pending reminder #{id}.")


def register(reg: ToolRegistry) -> None:
    c = "reminders"
    reg.register(Tool("set_reminder", "Create a reminder. `when` like 'in 20 minutes', 'at 5pm', 'tomorrow at 9am', or ISO time.",
                      obj({"text": S, "when": S}, ["text", "when"]), set_reminder, category=c))
    reg.register(Tool("set_timer", "Start a countdown timer, e.g. duration '10 minutes'.", obj({"duration": S, "label": S}, ["duration"]), set_timer, category=c))
    reg.register(Tool("set_alarm", "Set an alarm for a clock time, e.g. '7:30 am'.", obj({"time": S, "label": S}, ["time"]), set_alarm, category=c))
    reg.register(Tool("list_reminders", "List pending reminders, timers and alarms.", obj(), list_reminders, category=c, side_effects=False))
    reg.register(Tool("cancel_reminder", "Cancel a pending reminder/timer/alarm by id.", obj({"id": I}, ["id"]), cancel_reminder, category=c))
