"""Volume, mute, brightness, lock, sleep, shutdown, restart."""
from __future__ import annotations

from ..registry import I, Level, Tool, ToolRegistry, fail, obj, ok, S


def set_volume(ctx, percent: int):
    p = max(0, min(100, percent))
    ctx.adapter.set_volume(p)
    return ok(f"Volume set to {p}%.", volume=p)


def change_volume(ctx, delta: int):
    cur = ctx.adapter.get_volume()
    p = max(0, min(100, cur + delta))
    ctx.adapter.set_volume(p)
    if p > 0 and ctx.adapter.get_muted():
        ctx.adapter.set_muted(False)
    return ok(f"Volume {'up' if delta > 0 else 'down'} to {p}%.", volume=p)


def set_mute(ctx, state: str = "toggle"):
    cur = ctx.adapter.get_muted()
    new = (not cur) if state == "toggle" else state == "on"
    ctx.adapter.set_muted(new)
    return ok("Muted." if new else "Unmuted.", muted=new)


def set_brightness(ctx, percent: int):
    p = max(0, min(100, percent))
    ctx.adapter.set_brightness(p)
    return ok(f"Brightness set to {p}%.", brightness=p)


def change_brightness(ctx, delta: int):
    cur = ctx.adapter.get_brightness()
    if cur is None:
        return fail("I can't read this display's brightness (desktop monitors usually can't be changed in software).")
    p = max(0, min(100, cur + delta))
    ctx.adapter.set_brightness(p)
    return ok(f"Brightness {'up' if delta > 0 else 'down'} to {p}%.", brightness=p)


def lock_screen(ctx):
    ctx.adapter.lock()
    return ok("Locking the screen.")


def sleep_pc(ctx):
    ctx.adapter.sleep()
    return ok("Going to sleep.")


def shutdown_pc(ctx, delay_seconds: int = 30):
    ctx.adapter.shutdown(delay_seconds)
    return ok(f"Shutting down in {delay_seconds} seconds. Say “cancel shutdown” to stop it.")


def restart_pc(ctx, delay_seconds: int = 30):
    ctx.adapter.restart(delay_seconds)
    return ok(f"Restarting in {delay_seconds} seconds. Say “cancel shutdown” to stop it.")


def cancel_shutdown(ctx):
    ctx.adapter.cancel_shutdown()
    return ok("Cancelled the pending shutdown/restart.")


def register(reg: ToolRegistry) -> None:
    cat = "system"
    reg.register(Tool("set_volume", "Set master volume 0-100.", obj({"percent": {**I, "minimum": 0, "maximum": 100}}, ["percent"]), set_volume, category=cat))
    reg.register(Tool("change_volume", "Raise or lower volume by delta percent (negative = down).", obj({"delta": {**I, "minimum": -100, "maximum": 100}}, ["delta"]), change_volume, category=cat))
    reg.register(Tool("set_mute", "Mute, unmute or toggle sound.", obj({"state": {**S, "enum": ["on", "off", "toggle"]}}), set_mute, category=cat))
    reg.register(Tool("set_brightness", "Set screen brightness 0-100 (laptop/internal displays).", obj({"percent": {**I, "minimum": 0, "maximum": 100}}, ["percent"]), set_brightness, category=cat))
    reg.register(Tool("change_brightness", "Raise or lower brightness by delta percent.", obj({"delta": {**I, "minimum": -100, "maximum": 100}}, ["delta"]), change_brightness, category=cat))
    reg.register(Tool("lock_screen", "Lock the Windows session.", obj(), lock_screen, category=cat))
    reg.register(Tool("sleep_pc", "Put the PC to sleep.", obj(), sleep_pc, category=cat, taint_sensitive=True))
    reg.register(Tool("shutdown_pc", "Shut the PC down after a delay (always asks first).",
                      obj({"delay_seconds": {**I, "minimum": 5, "maximum": 600}}), shutdown_pc, Level.CONFIRM, cat, always_confirm=True,
                      describe=lambda c, a: f"SHUT DOWN the PC in {a.get('delay_seconds', 30)} seconds (unsaved work will be lost)"))
    reg.register(Tool("restart_pc", "Restart the PC after a delay (always asks first).",
                      obj({"delay_seconds": {**I, "minimum": 5, "maximum": 600}}), restart_pc, Level.CONFIRM, cat, always_confirm=True,
                      describe=lambda c, a: f"RESTART the PC in {a.get('delay_seconds', 30)} seconds (unsaved work will be lost)"))
    reg.register(Tool("cancel_shutdown", "Cancel a pending shutdown or restart.", obj(), cancel_shutdown, category=cat))
