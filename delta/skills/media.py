from __future__ import annotations

from ..registry import Tool, ToolRegistry, obj, ok, S

LABELS = {"play_pause": "Play/pause", "next": "Next track", "previous": "Previous track", "stop": "Stopped media"}


def media_control(ctx, action: str):
    ctx.adapter.media_key(action)
    return ok(f"{LABELS[action]}.")


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("media_control", "Send a media key: play_pause, next, previous, stop (works with Spotify, YouTube, VLC...).",
                      obj({"action": {**S, "enum": list(LABELS)}}, ["action"]), media_control, category="media"))
