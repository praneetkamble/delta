"""OPTIONAL PLUGIN STUBS: Gmail and Calendar.

These are intentionally NOT implemented and handle NO credentials. They exist so the tool names, permission levels and
the extension point are clear. To implement one, use Google's official OAuth client in a separate module, keep the token
in the OS keyring (never in Delta's config/DB/audit log), mark read tools SAFE + untrusted_output=True (mail text is
attacker-controlled!) and any send/delete tool CONFIRM + always_confirm=True.
"""
from __future__ import annotations

from ..registry import Tool, ToolRegistry, fail, obj, I


def gmail_unread(ctx, limit: int = 5):
    return fail("The Gmail plugin is an optional stub and is not set up. See delta/skills/plugins.py for how to add it.")


def calendar_today(ctx):
    return fail("The Calendar plugin is an optional stub and is not set up. See delta/skills/plugins.py for how to add it.")


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("gmail_unread", "[STUB, not implemented] Summarise unread Gmail.", obj({"limit": I}), gmail_unread,
                      category="plugins", side_effects=False, untrusted_output=True, expose_to_llm=False))
    reg.register(Tool("calendar_today", "[STUB, not implemented] Today's calendar events.", obj(), calendar_today,
                      category="plugins", side_effects=False, untrusted_output=True, expose_to_llm=False))
