from __future__ import annotations

from ..registry import Tool, ToolRegistry, fail, obj, ok, S


def run_routine(ctx, name: str):
    r = ctx.routines.find(name)
    if not r:
        return fail(f"No routine called “{name}”. Known: {', '.join(x.name for x in ctx.routines.all()) or 'none'}.")
    results = ctx.engine.run_routine(r.name, origin="routine")
    done = sum(1 for x in results if x.status in ("ok", "dry_run"))
    pend = sum(1 for x in results if x.status == "pending")
    text = f"Ran “{r.name}”: {done}/{len(results)} steps done" + (f", {pend} waiting for your approval" if pend else "") + "."
    failed = [x.text for x in results if x.status in ("error", "blocked")]
    if failed:
        text += "\n" + "\n".join("• " + f for f in failed[:5])
    return ok(text, steps=[x.to_dict() for x in results])


def list_routines(ctx):
    rs = ctx.routines.all()
    if not rs:
        return ok("No routines yet. Copy routines.example.yaml to routines.yaml and edit it.", routines=[])
    return ok("Routines:\n" + "\n".join(f"• {r.name}: {r.description or str(len(r.steps)) + ' steps'}" + (f" (scheduled {r.schedule_text})" if r.schedule else "") for r in rs))


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("run_routine", "Run a user-defined routine (macro) by name, e.g. 'work mode'. Each step is still permission-checked.",
                      obj({"name": S}, ["name"]), run_routine, category="routines", taint_sensitive=True))
    reg.register(Tool("list_routines", "List the user's routines.", obj(), list_routines, category="routines", side_effects=False))
