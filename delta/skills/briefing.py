from __future__ import annotations

from datetime import datetime

from ..registry import Tool, ToolRegistry, obj, ok
from ..util import fmt_dt


def daily_briefing(ctx):
    now = ctx.now()
    name = ctx.config.get("user_name", "")
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    lines = [f"Good {part}{', ' + name if name else ''}. It's {now.strftime('%A, %d %B %Y')}, {now.strftime('%I:%M %p').lstrip('0')}."]
    rem = [r for r in ctx.memory.reminders("pending") if datetime.fromtimestamp(r["due_ts"]).date() <= now.date()]
    if rem:
        lines.append("Today's reminders: " + "; ".join(f"{r['text']} ({datetime.fromtimestamp(r['due_ts']).strftime('%I:%M %p').lstrip('0')})" for r in rem[:6]))
    else:
        lines.append("No reminders left for today.")
    todos = ctx.memory.todos()
    if todos:
        lines.append(f"{len(todos)} open to-do{'s' if len(todos) != 1 else ''}: " + "; ".join(t["text"] for t in todos[:5]) + ("…" if len(todos) > 5 else ""))
    else:
        lines.append("Your to-do list is empty.")
    try:
        b = ctx.adapter.battery()
        if b:
            lines.append(f"Battery {b['percent']}% ({'charging' if b['plugged'] else 'on battery'})" + (". Consider plugging in." if b["percent"] < 25 and not b["plugged"] else "."))
    except Exception:
        pass
    sched = [r for r in getattr(ctx, "routines", None).all() if r.schedule] if getattr(ctx, "routines", None) else []
    if sched:
        lines.append("Scheduled routines: " + ", ".join(f"{r.name} ({r.schedule_text})" for r in sched))
    lines.append("(Weather, mail and calendar are not connected: they are optional plugins.)")
    return ok("\n".join(lines))


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("daily_briefing", "Date, reminders, to-dos, battery and scheduled routines for today.", obj(), daily_briefing, category="briefing", side_effects=False))
    _register_time(reg)
    reg.register(Tool("list_capabilities", "List what Delta can do.", obj(), list_capabilities, category="briefing", side_effects=False))


def current_time(ctx):
    now = ctx.now()
    return ok(f"It's {now.strftime('%I:%M %p').lstrip('0')} on {now.strftime('%A, %d %B %Y')}.")


def _register_time(reg: ToolRegistry) -> None:
    reg.register(Tool("current_time", "Current local date and time.", obj(), current_time, category="briefing", side_effects=False))


def list_capabilities(ctx):
    cats: dict[str, list[str]] = {}
    for t in ctx.registry.all():
        if t.expose_to_llm:
            cats.setdefault(t.category, []).append(t.name + (" (asks first)" if t.always_confirm or t.level.value == "confirm" else ""))
    lines = [f"{c}: {', '.join(v)}" for c, v in sorted(cats.items())]
    return ok("I can do these things (see the cheat sheet in the README for example phrases):\n" + "\n".join(lines))
