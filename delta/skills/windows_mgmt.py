from __future__ import annotations

from ..registry import Level, Tool, ToolRegistry, fail, obj, ok, S

ACTIONS = ["minimize", "maximize", "restore", "snap_left", "snap_right", "close"]


def list_windows(ctx):
    ws = ctx.adapter.list_windows()
    if not ws:
        return ok("No open windows found.", windows=[])
    return ok("Open windows:\n" + "\n".join(f"• {w['title']}  ({w['process']})" for w in ws[:25]), windows=ws)


def window_action(ctx, action: str, title: str = "active"):
    t = ctx.adapter.window_action(title, action)
    return ok(f"{action.replace('_', ' ').capitalize()}: {t}.", title=t) if t else fail(f"No window matches “{title}”.")


def _classify(ctx, args):
    return Level.CONFIRM if args.get("action") == "close" else Level.SAFE


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("list_windows", "List visible application windows.", obj(), list_windows, category="windows", side_effects=False))
    reg.register(Tool("window_action", "Minimize, maximize, restore, snap left/right or close a window ('active' = the focused one).",
                      obj({"action": {**S, "enum": ACTIONS}, "title": S}, ["action"]), window_action, Level.SAFE, "windows", classify=_classify,
                      describe=lambda c, a: f"Close the window “{a.get('title', 'active')}”"))
