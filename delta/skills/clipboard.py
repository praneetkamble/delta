from __future__ import annotations

from ..registry import Tool, ToolRegistry, fail, obj, ok, S


def clipboard_read(ctx):
    text = ctx.adapter.clipboard_get()
    if not text:
        return ok("The clipboard is empty.", text="")
    shown = text if len(text) <= 1500 else text[:1500] + f"… (+{len(text) - 1500} chars)"
    return ok(f"On your clipboard:\n{shown}", text=text[:20000], untrusted=True)


def clipboard_write(ctx, text: str):
    ctx.adapter.clipboard_set(text)
    return ok(f"Copied {len(text)} characters to the clipboard.")


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("clipboard_read", "Read the current clipboard text (treated as untrusted data).", obj(), clipboard_read,
                      category="clipboard", side_effects=False, untrusted_output=True))
    reg.register(Tool("clipboard_write", "Put text on the clipboard.", obj({"text": S}, ["text"]), clipboard_write,
                      category="clipboard", taint_sensitive=True, audit_hide_args=("text",)))
