"""Gate-facing tools for Vibe Coding. All are `expose_to_llm=False` (the normal chat LLM can't call them) and run through
Engine.execute like every other action. The coding agent reaches the file/command ones through a FIXED name map (agent.py),
the dashboard buttons reach the rest with origin="user"."""
from __future__ import annotations

import fnmatch
import re
import uuid
from typing import Any

from ..registry import B, I, Level, Tool, ToolRegistry, ToolResult, fail, obj, ok, S
from .commands import CommandError, clean_env, is_long_running, resolve_argv, start_job, tokenize, venv_python
from .difftools import PatchError
from .pathsafe import VibeError, is_text_bytes, resolve_in

MAX_READ_LINES = 400


def _mgr(ctx):
    m = getattr(ctx, "vibe", None)
    if m is None:
        raise VibeError("Vibe Coding is not available in this context")
    return m


def _run(ctx, run: str):
    r = _mgr(ctx).get_run(run)
    if r is None or not r.active:
        raise VibeError("there is no active coding run for this request")
    return r


def guard(fn):
    def wrapper(ctx, **kw):
        try:
            return fn(ctx, **kw)
        except (VibeError, PatchError, CommandError) as e:
            return fail(str(e))
    wrapper.__name__ = fn.__name__
    return wrapper


# ------------------------------------------------------------------------------------------------ read tools
@guard
def list_files(ctx, run: str, path: str = ".", depth: int = 2):
    mgr = _mgr(ctx)
    r = _run(ctx, run)
    prefix = "" if path.strip() in ("", ".", "/") else path.strip().replace("\\", "/").strip("/")
    if prefix:
        _, prefix = resolve_in(mgr.project_path(r.project), prefix)
    pend = mgr.pending.get(r.project, {})
    entries: dict[str, str] = {}
    for rel in mgr.iter_files(r.project):
        if prefix and not rel.startswith(prefix + "/"):
            continue
        rest = rel[len(prefix) + 1:] if prefix else rel
        parts = rest.split("/")
        for i in range(1, min(len(parts), depth + 1)):
            entries.setdefault("/".join(parts[:i]) + "/", "dir")
        if len(parts) <= depth:
            entries[rest] = "file" + (" [staged]" if rel in pend else "")
    lines = [(k if v == "dir" else f"{k}  ({v})") for k, v in sorted(entries.items())][:300]
    for rel, cid in pend.items():
        ch = mgr.changes.get(cid)
        if ch and ch.op == "delete" and (not prefix or rel.startswith(prefix + "/")):
            lines.append(f"{rel[len(prefix) + 1:] if prefix else rel}  (staged for deletion)")
    text = "\n".join(lines) or "(empty)"
    return ok(f"{len(lines)} entries under {prefix or '.'}:\n{text}", text=text, untrusted=True)


@guard
def read_file(ctx, run: str, path: str, offset: int = 1, limit: int = MAX_READ_LINES):
    mgr = _mgr(ctx)
    r = _run(ctx, run)
    p = mgr.project_path(r.project)
    real, clean = resolve_in(p, path)
    cur = mgr.current_text(r.project, clean)
    if cur is None:
        return fail(f"{clean} does not exist. Use list_files to see what is there.")
    lines = cur.split("\n")
    total = len(lines) - (1 if lines and lines[-1] == "" else 0)
    offset = max(1, int(offset))
    limit = max(1, min(int(limit), MAX_READ_LINES))
    chunk = lines[offset - 1:offset - 1 + limit]
    body = "\n".join(chunk)
    cap = int(mgr.cfg("max_read_chars", 12000))
    note = ""
    if len(body) > cap:
        body = body[:cap]
        note = " (cut at the character limit; use offset to read more)"
    end = offset - 1 + len(chunk)
    head = f"{clean} lines {offset}-{end} of {total}{note}" + (" [staged version]" if clean in mgr.pending.get(r.project, {}) else "")
    return ok(head, text=body, untrusted=True, path=clean)


@guard
def search_code(ctx, run: str, query: str, glob: str = ""):
    mgr = _mgr(ctx)
    r = _run(ctx, run)
    if not query.strip():
        return fail("empty query")
    if query.startswith("re:"):
        try:
            rx = re.compile(query[3:], re.I)
        except re.error as e:
            return fail(f"bad regular expression: {e}")
    else:
        rx = re.compile(re.escape(query), re.I)
    hits: list[str] = []
    for rel in mgr.iter_files(r.project):
        if glob and not (fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(rel.rsplit("/", 1)[-1], glob)):
            continue
        try:
            txt = mgr.current_text(r.project, rel)
        except VibeError:
            continue
        if txt is None or len(txt) > 200_000:
            continue
        for i, ln in enumerate(txt.split("\n"), 1):
            if rx.search(ln):
                hits.append(f"{rel}:{i}: {ln.strip()[:160]}")
                if len(hits) >= 40:
                    break
        if len(hits) >= 40:
            break
    text = "\n".join(hits) or "no matches"
    return ok(f"{len(hits)} match(es)", text=text, untrusted=True)


# ------------------------------------------------------------------------------------------------ write tools (staged)
def _after_stage(ctx, r, ch, verb: str) -> ToolResult:
    mgr = _mgr(ctx)
    if ch is None:
        return ok("No change: the file already has exactly that content.")
    auto = mgr.auto_accept(r.project) and not r.tainted
    if auto:
        try:
            mgr.accept(ch.id, via="auto-accept")
        except VibeError as e:
            return fail(str(e))
        r.add("change", f"{verb} {ch.path}  +{ch.added} −{ch.removed}  (auto-accepted)", ch.path, "accepted", ch.id)
        return ok(f"{verb} {ch.path} (+{ch.added}/−{ch.removed}); written because auto-accept is on for this project.", change=ch.id)
    r.add("change", f"{verb} {ch.path}  +{ch.added} −{ch.removed}  · waiting for review", ch.path, "pending", ch.id)
    return ok(f"{verb} {ch.path} (+{ch.added}/−{ch.removed}). It is STAGED: the user must accept it before it is written to disk. "
              f"Later reads will show your staged version. Do not write it again.", change=ch.id)


@guard
def write_file(ctx, run: str, path: str, content: str):
    r = _run(ctx, run)
    ch = _mgr(ctx).stage(r, path, content)
    verb = "Proposed" if not ch or ch.op != "create" else "Proposed new file"
    return _after_stage(ctx, r, ch, "Created" if ch and ch.op == "create" else "Edited" if ch else verb)


@guard
def apply_patch(ctx, run: str, patch: str):
    r = _run(ctx, run)
    changes = _mgr(ctx).stage_patch(r, patch)
    if not changes:
        return ok("The patch changes nothing.")
    outs = [_after_stage(ctx, r, c, "Patched") for c in changes]
    bad = [o for o in outs if not o.ok]
    if bad:
        return fail(bad[0].text)
    return ok(" ".join(o.text for o in outs))


@guard
def delete_file(ctx, run: str, path: str):
    r = _run(ctx, run)
    ch = _mgr(ctx).stage(r, path, None)
    return _after_stage(ctx, r, ch, "Deleted")


# ------------------------------------------------------------------------------------------------ commands
def _classify_cmd(ctx, args):
    mgr = ctx.vibe
    r = mgr.get_run(args.get("run", "")) if mgr else None
    if r is None:
        return Level.BLOCKED, "no active coding run"
    cmd = args.get("command", "")
    if is_long_running(cmd):
        return Level.BLOCKED, "dev servers are started from the Live preview panel, not from commands"
    return mgr.classify_command(cmd, mgr.project_path(r.project))


def _describe_cmd(ctx, args):
    mgr = ctx.vibe
    r = mgr.get_run(args.get("run", ""))
    lvl, why = mgr.classify_command(args["command"])
    return f"Vibe Coding · project {r.project if r else '?'}: run this exact command in its folder: {args['command']}  ({why})"


@guard
def run_command(ctx, run: str, command: str, timeout: int = 0, call: str = ""):
    mgr = _mgr(ctx)
    r = _run(ctx, run)
    p = mgr.project_path(r.project)
    lvl, why = mgr.classify_command(command, p)
    if lvl == Level.BLOCKED:
        return fail(f"Blocked: {why}")
    argv = tokenize(command)
    low = argv[0].lower().replace("\\", "/").rsplit("/", 1)[-1]
    is_pip = low in ("pip", "pip3") or (low in ("python", "python3", "py", "python.exe") and argv[1:3] == ["-m", "pip"])
    if is_pip and not venv_python(p):
        return fail("There is no virtual environment yet, and pip must not install into the system Python. Run `python -m venv .venv` first.")
    real = resolve_argv(argv, p, str(mgr.cfg("python", "") or ""))
    secs = int(timeout or mgr.cfg("command_timeout_s", 180))
    secs = max(5, min(secs, 900))
    job = start_job(real, str(p), clean_env(mgr.secret_env_names()), secs)
    key = call or uuid.uuid4().hex[:6]
    r.jobs[key] = job
    return ok(f"started: {command}", call=key)


# ------------------------------------------------------------------------------------------------ user-origin tools
@guard
def review_change(ctx, change: str, decision: str):
    mgr = _mgr(ctx)
    ch = mgr.accept(change) if decision == "accept" else mgr.reject(change)
    return ok(f"{'Accepted' if decision == 'accept' else 'Rejected'} {ch.op} of {ch.path}.", change=ch.id, status=ch.status, path=ch.path)


def _describe_review(ctx, args):
    ch = ctx.vibe.changes.get(args["change"]) if ctx.vibe else None
    return f"{args['decision']} the change to {ch.path if ch else args['change']}"


@guard
def preview_ctl(ctx, project: str, action: str):
    mgr = _mgr(ctx)
    if action == "start":
        st = mgr.preview.start(project)
        return ok(st["message"], preview=st)
    mgr.preview.stop(project)
    return ok("Preview stopped.", preview=mgr.preview.status(project))


@guard
def open_vscode(ctx, project: str):
    return ok(_mgr(ctx).open_in_vscode(project))


@guard
def create_project(ctx, name: str, template: str):
    info = _mgr(ctx).create_project(name, template)
    return ok(f"Created project {info['name']} from the {template} template in {info['path']}.", **info)


@guard
def undo_run(ctx, project: str):
    return ok(_mgr(ctx).undo_last(project))


def _describe_undo(ctx, args):
    mgr = ctx.vibe
    h = mgr.history(args["project"])
    last = next((x for x in h if not x.get("undone") and x.get("snapshot")), None)
    if not last:
        return f"Undo the last Vibe Coding run in {args['project']} (nothing to undo)"
    return (f"Undo the last Vibe Coding run in {args['project']} (“{last['prompt'][:60]}”): reset the project's files to the snapshot taken before it. "
            f"Anything changed since then is saved in git first")


@guard
def set_auto_accept(ctx, project: str, enabled: bool):
    _mgr(ctx).set_auto_accept(project, enabled)
    return ok(("Auto-accept is ON: edits in this project are written without asking (commands still follow the whitelist)." if enabled
               else "Auto-accept is OFF: every file change waits for your review."))


def _classify_auto(ctx, args):
    return (Level.CONFIRM, "turning auto-accept on lets Delta write files here without asking") if args.get("enabled") else (Level.SAFE, "turning it off is always allowed")


def _describe_auto(ctx, args):
    return f"Turn ON auto-accept for project {args['project']}: Delta will write file edits there without showing each one first"


def register(reg: ToolRegistry) -> None:
    run = {"run": {**S, "description": "internal run id"}}
    def T(name, desc, params, fn, level=Level.SAFE, **kw):
        reg.register(Tool(name, desc, params, fn, level, category="vibe", expose_to_llm=False, **kw))
    T("vibe_list_files", "Vibe Coding: list files in the project.", obj({**run, "path": S, "depth": {**I, "minimum": 1, "maximum": 4}}, ["run"]),
      list_files, Level.SAFE, side_effects=False, untrusted_output=True)
    T("vibe_read_file", "Vibe Coding: read a project file.", obj({**run, "path": S, "offset": I, "limit": I}, ["run", "path"]),
      read_file, Level.SAFE, side_effects=False, untrusted_output=True)
    T("vibe_search_code", "Vibe Coding: search the project.", obj({**run, "query": S, "glob": S}, ["run", "query"]),
      search_code, Level.SAFE, side_effects=False, untrusted_output=True)
    T("vibe_write_file", "Vibe Coding: stage a whole-file write for review.", obj({**run, "path": S, "content": S}, ["run", "path", "content"]),
      write_file, Level.SAFE, audit_hide_args=("content",))
    T("vibe_apply_patch", "Vibe Coding: stage a unified-diff patch for review.", obj({**run, "patch": S}, ["run", "patch"]),
      apply_patch, Level.SAFE, audit_hide_args=("patch",))
    T("vibe_delete_file", "Vibe Coding: stage a file deletion for review.", obj({**run, "path": S}, ["run", "path"]), delete_file, Level.SAFE)
    T("vibe_run_command", "Vibe Coding: run a whitelisted command in the project folder (others ask first).",
      obj({**run, "command": S, "timeout": {**I, "minimum": 0, "maximum": 900}, "call": S}, ["run", "command"]),
      run_command, Level.CONFIRM, classify=_classify_cmd, describe=_describe_cmd, taint_sensitive=True, untrusted_output=True)
    T("vibe_review_change", "Vibe Coding: accept or reject one staged file change (dashboard buttons only).",
      obj({"change": S, "decision": {**S, "enum": ["accept", "reject"]}}, ["change", "decision"]), review_change, Level.SAFE, describe=_describe_review)
    T("vibe_preview", "Vibe Coding: start or stop the live preview server of a project.",
      obj({"project": S, "action": {**S, "enum": ["start", "stop"]}}, ["project", "action"]), preview_ctl, Level.SAFE)
    T("vibe_open_vscode", "Vibe Coding: open a project folder in VS Code.", obj({"project": S}, ["project"]), open_vscode, Level.SAFE)
    T("vibe_create_project", "Vibe Coding: create a project folder from a template.", obj({"name": S, "template": S}, ["name", "template"]),
      create_project, Level.SAFE)
    T("vibe_undo", "Vibe Coding: undo the last agent run (git reset to the snapshot).", obj({"project": S}, ["project"]), undo_run, Level.CONFIRM,
      always_confirm=True, describe=_describe_undo)
    T("vibe_auto_accept", "Vibe Coding: switch auto-accept for a project.", obj({"project": S, "enabled": B}, ["project", "enabled"]),
      set_auto_accept, Level.SAFE, classify=_classify_auto, describe=_describe_auto)
