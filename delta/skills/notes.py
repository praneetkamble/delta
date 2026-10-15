"""Notes, to-dos and remembered facts about the user."""
from __future__ import annotations

from ..memory import SecretRefused
from ..registry import B, I, Tool, ToolRegistry, fail, obj, ok, S


def add_note(ctx, text: str):
    nid = ctx.memory.add_note(text)
    return ok(f"Saved note #{nid}.", id=nid)


def list_notes(ctx, limit: int = 10):
    rows = ctx.memory.notes(limit)
    return ok("Your notes:\n" + "\n".join(f"#{r['id']} {r['text']}" for r in rows), notes=rows) if rows else ok("You have no notes yet.", notes=[])


def add_todo(ctx, text: str):
    tid = ctx.memory.add_todo(text)
    return ok(f"Added to your to-do list: {text} (#{tid}).", id=tid)


def list_todos(ctx, include_done: bool = False):
    rows = ctx.memory.todos(include_done)
    if not rows:
        return ok("Your to-do list is empty.", todos=[])
    return ok("To-do:\n" + "\n".join(f"{'☑' if r['done'] else '☐'} #{r['id']} {r['text']}" for r in rows), todos=rows)


def complete_todo(ctx, id: int):
    return ok(f"Done: #{id}. Nice.") if ctx.memory.complete_todo(id) else fail(f"No open to-do #{id}.")


def delete_todo(ctx, id: int):
    return ok(f"Removed to-do #{id}.") if ctx.memory.delete_todo(id) else fail(f"No to-do #{id}.")


def remember_fact(ctx, text: str):
    try:
        fid = ctx.memory.add_fact(text)
    except SecretRefused as e:
        return fail(str(e))
    return ok(f"Got it, I'll remember that. (#{fid})", id=fid)


def list_facts(ctx):
    rows = ctx.memory.facts()
    return ok("What I remember about you:\n" + "\n".join(f"#{r['id']} {r['text']}" for r in rows), facts=rows) if rows else ok("I don't have any saved facts about you yet. Say “remember that …”.", facts=[])


def forget_fact(ctx, id: int):
    return ok(f"Forgot #{id}.") if ctx.memory.forget_fact(id) else fail(f"No fact #{id}.")


def register(reg: ToolRegistry) -> None:
    c = "notes"
    reg.register(Tool("add_note", "Save a note.", obj({"text": S}, ["text"]), add_note, category=c))
    reg.register(Tool("list_notes", "Show recent notes.", obj({"limit": {**I, "minimum": 1, "maximum": 50}}), list_notes, category=c, side_effects=False))
    reg.register(Tool("add_todo", "Add a to-do item.", obj({"text": S}, ["text"]), add_todo, category=c))
    reg.register(Tool("list_todos", "Show the to-do list.", obj({"include_done": B}), list_todos, category=c, side_effects=False))
    reg.register(Tool("complete_todo", "Mark a to-do done by id.", obj({"id": I}, ["id"]), complete_todo, category=c))
    reg.register(Tool("delete_todo", "Delete a to-do by id.", obj({"id": I}, ["id"]), delete_todo, category=c))
    reg.register(Tool("remember_fact", "Remember a fact about the user (never passwords, keys, PINs or card numbers).", obj({"text": S}, ["text"]), remember_fact, category=c, taint_sensitive=True))
    reg.register(Tool("list_facts", "List remembered facts.", obj(), list_facts, category=c, side_effects=False))
    reg.register(Tool("forget_fact", "Forget a remembered fact by id.", obj({"id": I}, ["id"]), forget_fact, category=c))
