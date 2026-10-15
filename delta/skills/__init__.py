from __future__ import annotations

from ..registry import ToolRegistry


def register_all(reg: ToolRegistry) -> ToolRegistry:
    from . import (apps, briefing, clipboard, files, media, notes, plugins, reminders, routine_tools, screen,
                   shell, sysinfo, system_control, vibe, web, windows_mgmt)
    for mod in (apps, system_control, files, clipboard, screen, windows_mgmt, sysinfo, web, reminders, notes, media,
                shell, briefing, routine_tools, plugins, vibe):
        mod.register(reg)
    return reg
