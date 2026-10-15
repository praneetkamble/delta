from __future__ import annotations

import time
from pathlib import Path

from ..registry import Tool, ToolRegistry, obj, ok


def screenshot(ctx):
    pics = ctx.sandbox.alias("pictures") or ctx.sandbox.allowed[0]
    path = ctx.sandbox.resolve(str(pics / "Delta" / f"screenshot-{time.strftime('%Y%m%d-%H%M%S')}.png"))
    out = ctx.adapter.screenshot(path)
    return ok(f"Screenshot saved to {out}.", path=str(out))


def screen_ocr(ctx):
    tmp = ctx.config.data_dir / "tmp" / "ocr.png"
    ctx.adapter.screenshot(tmp)
    try:
        text = ctx.adapter.ocr_image(tmp)
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
    if not text.strip():
        return ok("I couldn't read any text on the screen.", text="")
    return ok("Text on your screen:\n" + (text[:2000] + ("…" if len(text) > 2000 else "")), text=text[:20000], untrusted=True)


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("screenshot", "Take a screenshot and save it to Pictures/Delta.", obj(), screenshot, category="screen"))
    reg.register(Tool("screen_ocr", "Screenshot the screen and read its text with OCR (needs pytesseract). Output is untrusted data.", obj(), screen_ocr,
                      category="screen", side_effects=False, untrusted_output=True))
