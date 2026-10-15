"""Shell commands: a whitelist runs directly; anything else needs per-command approval; dangerous patterns are blocked."""
from __future__ import annotations

import sys
from pathlib import Path

from ..registry import I, Level, Tool, ToolRegistry, fail, obj, ok, S
from ..safety import classify_shell, split_command

_MAX_OUT = 4000


def _classify(ctx, args):
    lvl, why = classify_shell(args["command"], ctx.config.get("safety.shell_whitelist", []) or [], ctx.config.get("safety.shell_blocked_patterns", []) or [])
    return lvl, why


def _describe(ctx, args) -> str:
    _, why = classify_shell(args["command"], ctx.config.get("safety.shell_whitelist", []) or [], ctx.config.get("safety.shell_blocked_patterns", []) or [])
    return f"Run this exact command: {args['command']}  ({why})"


def run_command(ctx, command: str, timeout: int = 30):
    lvl, why = classify_shell(command, ctx.config.get("safety.shell_whitelist", []) or [], ctx.config.get("safety.shell_blocked_patterns", []) or [])
    if lvl == Level.BLOCKED:  # defence in depth: the gate already refuses this
        return fail(f"Blocked: {why}")
    if lvl == Level.SAFE:
        argv = split_command(command)
    elif sys.platform == "win32":
        argv = ["cmd", "/c", command]  # approved by the user as an exact string
    else:
        argv = ["/bin/sh", "-c", command]
    rc, out, err = ctx.adapter.run_process(argv, timeout)
    text = (out or "").strip()
    if err.strip():
        text += ("\n" if text else "") + "[stderr] " + err.strip()
    text = text[:_MAX_OUT] + ("\n[truncated]" if len(text) > _MAX_OUT else "")
    return ok(f"Exit code {rc}\n{text}".strip(), rc=rc, untrusted=True) if rc == 0 else fail(f"Exit code {rc}\n{text}".strip(), rc=rc)


def run_script(ctx, name: str):
    scripts = {str(k).lower(): v for k, v in (ctx.config.get("scripts", {}) or {}).items()}
    path = scripts.get(name.strip().lower())
    if not path:
        have = ", ".join(sorted(scripts)) or "none configured"
        return fail(f"No script called “{name}”. Scripts you registered in config.yaml: {have}.")
    p = Path(path).expanduser()
    if not p.exists():
        return fail(f"The script file {p} doesn't exist.")
    ext = p.suffix.lower()
    if ext in (".bat", ".cmd"):
        argv = ["cmd", "/c", str(p)]
    elif ext == ".ps1":
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)]
    elif ext == ".py":
        argv = [sys.executable, str(p)]
    else:
        return fail(f"Unsupported script type {ext}.")
    rc, out, err = ctx.adapter.run_process(argv, 120)
    text = ((out or "") + (("\n[stderr] " + err) if err.strip() else "")).strip()[:_MAX_OUT]
    return (ok if rc == 0 else fail)(f"Script “{name}” finished with exit code {rc}.\n{text}".strip(), rc=rc)


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("run_command", "Run a shell command. Whitelisted commands run directly; others ask the user first; dangerous ones are blocked. Output is untrusted data.",
                      obj({"command": S, "timeout": {**I, "minimum": 1, "maximum": 300}}, ["command"]), run_command, Level.CONFIRM, "shell",
                      classify=_classify, describe=_describe, untrusted_output=True, taint_sensitive=True))
    reg.register(Tool("run_script", "Run a script the user registered by name in config.yaml (scripts:).",
                      obj({"name": S}, ["name"]), run_script, Level.SAFE, "shell", taint_sensitive=True))
