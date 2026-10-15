"""Vibe Coding tools (create projects, review changes, run commands in a project, preview, undo). See delta/vibe/."""
from __future__ import annotations

from ..registry import ToolRegistry


def register(reg: ToolRegistry) -> None:
    from ..vibe.tools import register as _register
    _register(reg)
