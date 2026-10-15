"""Open / close / focus applications."""
from __future__ import annotations

import os
import re

from ..adapters.base import APP_PROCESSES, DEFAULT_APPS
from ..registry import Level, Tool, ToolRegistry, fail, obj, ok, S


def _clean(name: str) -> str:
    n = name.strip().strip('"').lower()
    n = re.sub(r"^(the|my)\s+", "", n)
    n = re.sub(r"\s+(app|application|program)$", "", n)
    return n


def app_table(ctx) -> dict[str, str]:
    t = dict(DEFAULT_APPS)
    t.update({str(k).lower(): str(v) for k, v in (ctx.config.get("apps", {}) or {}).items()})
    return t


def resolve_app(ctx, name: str) -> tuple[str, str | None, bool]:
    """-> (launch target, process name for closing, known?)"""
    key = _clean(name)
    table = app_table(ctx)
    if key in table:
        target = table[key]
        proc = APP_PROCESSES.get(key)
        if not proc:
            base = os.path.basename(target.replace("\\", "/"))
            proc = base if base.lower().endswith(".exe") else (base + ".exe" if base and not base.endswith(":") else None)
        return target, proc, True
    base = os.path.basename(name.strip().replace("\\", "/"))
    return name.strip(), (base if base.lower().endswith(".exe") else base + ".exe"), False


def _classify_open(ctx, args):
    return Level.SAFE if resolve_app(ctx, args["name"])[2] else Level.CONFIRM


def open_app(ctx, name: str):
    target, _, known = resolve_app(ctx, name)
    msg = ctx.adapter.open_app(target)
    return ok(f"Opening {name.strip()}." if known else f"Launching {name.strip()}.", detail=msg)


def close_app(ctx, name: str):
    _, proc, _ = resolve_app(ctx, name)
    if not proc:
        return fail(f"I don't know the process name for {name}.")
    n = ctx.adapter.close_app(proc)
    return ok(f"Asked {name.strip()} to close ({n} process{'es' if n != 1 else ''}).") if n else fail(f"{name.strip()} doesn't seem to be running.")


def focus_window(ctx, title: str):
    t = ctx.adapter.focus_window(title)
    return ok(f"Switched to “{t}”.", title=t) if t else fail(f"No open window matches “{title}”.")


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("open_app", "Open an application by friendly name (chrome, vs code, spotify, notepad...). Unknown programs need confirmation.",
                      obj({"name": {**S, "description": "App name or alias"}}, ["name"]), open_app, Level.SAFE,
                      "apps", classify=_classify_open,
                      describe=lambda c, a: f"Launch the program “{a['name']}”, which is not in your app list"))
    reg.register(Tool("close_app", "Politely ask an application to close (it may prompt to save work).",
                      obj({"name": S}, ["name"]), close_app, Level.CONFIRM, "apps",
                      describe=lambda c, a: f"Close {a['name']} (unsaved work in it could be lost)"))
    reg.register(Tool("focus_window", "Bring a window to the front by (part of) its title or process name.",
                      obj({"title": S}, ["title"]), focus_window, Level.SAFE, "apps"))
