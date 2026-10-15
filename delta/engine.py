"""The engine: the ONE place where every action (from rules, the LLM, voice, routines or the scheduler) passes the gate.

    request -> kill switch -> tool lookup -> argument validation -> permission decision
            -> blocked | pending confirmation | run (dry-run aware) -> audit log
"""
from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .brain import Brain
from .intents import parse_commands
from .registry import ArgError, Level, validate_args
from .safety import SandboxError, detect_injection

log = logging.getLogger("delta")

YES = {"yes", "y", "yep", "yeah", "yup", "confirm", "confirmed", "do it", "go ahead", "approve", "approved", "sure", "ok do it", "yes do it", "yes please"}
NO = {"no", "n", "nope", "nah", "cancel", "deny", "denied", "don't", "dont", "never mind", "nevermind", "stop", "no thanks", "abort"}
TAINT_TURNS = 3


@dataclass
class ExecResult:
    status: str                    # ok | error | pending | blocked | denied | killed | dry_run | expired
    tool: str
    args: dict
    text: str
    level: str = "safe"
    data: dict = field(default_factory=dict)
    pending_id: str | None = None
    tainted: bool = False
    untrusted: bool = False
    origin: str = "user"

    def to_dict(self) -> dict:
        return {"status": self.status, "tool": self.tool, "args": self.args, "text": self.text, "level": self.level,
                "pending_id": self.pending_id, "tainted": self.tainted, "untrusted": self.untrusted, "origin": self.origin}


@dataclass
class Pending:
    id: str
    tool: str
    args: dict
    description: str
    origin: str
    tainted: bool
    created: float
    expires: float
    reason: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "tool": self.tool, "args": self.args, "description": self.description, "origin": self.origin,
                "tainted": self.tainted, "expires_in": max(0, int(self.expires - time.time())), "reason": self.reason}


@dataclass
class Reply:
    text: str
    results: list[ExecResult] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    source: str = "system"

    def to_dict(self) -> dict:
        return {"text": self.text, "results": [r.to_dict() for r in self.results], "pending": self.pending, "source": self.source}


class SessionState:
    def __init__(self) -> None:
        self.taint_ttl = 0

    @property
    def tainted(self) -> bool:
        return self.taint_ttl > 0


class Engine:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.pending: dict[str, Pending] = {}
        self.lock = threading.RLock()
        self.sessions: dict[str, SessionState] = {}
        self.brain = Brain(self)

    # ------------------------------------------------------------------ helpers
    def session(self, sid: str) -> SessionState:
        return self.sessions.setdefault(sid, SessionState())

    def _expire(self) -> None:
        now = time.time()
        for pid in [p for p, v in self.pending.items() if v.expires < now]:
            v = self.pending.pop(pid)
            self.ctx.audit.log("confirm_expired", id=pid, tool=v.tool)

    # ------------------------------------------------------------------ the gate
    def execute(self, tool_name: str, args: dict | None = None, origin: str = "user", tainted: bool = False) -> ExecResult:
        ctx = self.ctx
        with self.lock:
            self._expire()
            args = args or {}
            if ctx.killed.is_set():
                ctx.audit.log("blocked", tool=tool_name, args=args, origin=origin, reason="kill switch is on")
                return ExecResult("killed", tool_name, args, "Delta is paused (kill switch). Press Resume in the UI or type “resume”.", origin=origin)
            tool = ctx.registry.get(tool_name)
            if tool is None:
                ctx.audit.log("error", tool=tool_name, args=args, origin=origin, reason="unknown tool")
                return ExecResult("error", tool_name, args, f"I don't have a tool called “{tool_name}”.", origin=origin)
            try:
                clean = validate_args(tool.parameters, args)
            except ArgError as e:
                ctx.audit.log("error", tool=tool_name, args=args, origin=origin, reason=f"bad arguments: {e}")
                return ExecResult("error", tool_name, args, f"Bad arguments for {tool_name}: {e}.", origin=origin)
            try:
                decision = ctx.policy.decide(tool, ctx, clean, tainted)
            except SandboxError as e:  # classify() resolving a path outside the sandbox
                ctx.audit.log("sandbox_violation", tool=tool_name, args=clean, origin=origin, reason=str(e), hide=tool.audit_hide_args)
                return ExecResult("blocked", tool_name, clean, f"Blocked: {e}.", level="blocked", origin=origin)
            if decision.level == Level.BLOCKED:
                ctx.audit.log("blocked", tool=tool_name, args=clean, origin=origin, reason=decision.reason, hide=tool.audit_hide_args)
                return ExecResult("blocked", tool_name, clean, f"Blocked by the safety policy: {decision.reason}.", level="blocked", origin=origin)
            if decision.level == Level.CONFIRM:
                try:
                    desc = tool.describe_call(ctx, clean)
                except SandboxError as e:
                    ctx.audit.log("sandbox_violation", tool=tool_name, args=clean, origin=origin, reason=str(e))
                    return ExecResult("blocked", tool_name, clean, f"Blocked: {e}.", level="blocked", origin=origin)
                pid = secrets.token_hex(3)
                ttl = float(ctx.config.get("safety.confirm_timeout_s", 120))
                p = Pending(pid, tool_name, clean, desc, origin, tainted, time.time(), time.time() + ttl, decision.reason)
                self.pending[pid] = p
                ctx.audit.log("confirm_requested", id=pid, tool=tool_name, args=clean, origin=origin, tainted=tainted,
                              description=desc, reason=decision.reason, hide=tool.audit_hide_args)
                ctx.emit("confirm", ref=pid, description=desc)
                warn = " (This came after I read untrusted web/file text, so please check it is really what you want.)" if tainted else ""
                return ExecResult("pending", tool_name, clean, f"Needs your approval: {desc}.{warn}", level="confirm",
                                  pending_id=pid, tainted=tainted, origin=origin)
            return self._run(tool, clean, origin, tainted, decision.level.value, approved=False)

    def _run(self, tool: Any, args: dict, origin: str, tainted: bool, level: str, approved: bool) -> ExecResult:
        ctx = self.ctx
        base = dict(tool=tool.name, args=args, origin=origin, level=level, approved=approved, tainted=tainted, hide=tool.audit_hide_args)
        if ctx.dry_run and tool.side_effects:
            desc = tool.describe_call(ctx, args)
            ctx.audit.log("tool_call", status="dry_run", dry_run=True, result=f"would run: {desc}", **base)
            return ExecResult("dry_run", tool.name, args, f"[dry-run] would run: {desc}", level=level, origin=origin, tainted=tainted)
        try:
            res = tool.handler(ctx, **args)
        except SandboxError as e:
            ctx.audit.log("sandbox_violation", tool=tool.name, args=args, origin=origin, reason=str(e), hide=tool.audit_hide_args)
            return ExecResult("blocked", tool.name, args, f"Blocked: {e}.", level="blocked", origin=origin)
        except Exception as e:
            log.exception("tool %s failed", tool.name)
            ctx.audit.log("tool_call", status="error", result=f"{type(e).__name__}: {e}", **base)
            return ExecResult("error", tool.name, args, f"{tool.name} failed: {e}", level=level, origin=origin, tainted=tainted)
        status = "ok" if res.ok else "error"
        text = res.text
        untrusted = tool.untrusted_output or bool(res.data.get("untrusted"))
        if untrusted and detect_injection(res.data.get("text") or res.text) and "⚠" not in text:
            text += "\n⚠ This text contains phrases that look like instructions to an AI. I treat it only as data."
        ctx.audit.log("tool_call", status=status, result=text, **base)
        return ExecResult(status, tool.name, args, text, level=level, data=res.data, tainted=tainted, untrusted=untrusted, origin=origin)

    # ------------------------------------------------------------------ confirmations
    def resolve(self, pid: str, approve: bool, via: str = "ui") -> ExecResult:
        ctx = self.ctx
        with self.lock:
            self._expire()
            p = self.pending.pop(pid, None)
            if p is None:
                return ExecResult("expired", "?", {}, "That request has expired or was already handled.")
            if ctx.killed.is_set():
                ctx.audit.log("confirm_denied", id=pid, tool=p.tool, via=via, reason="kill switch")
                return ExecResult("killed", p.tool, p.args, "Delta is paused (kill switch); nothing was run.")
            if not approve:
                ctx.audit.log("confirm_denied", id=pid, tool=p.tool, args=p.args, via=via)
                return ExecResult("denied", p.tool, p.args, f"Okay, cancelled: {p.description}.", level="confirm")
            tool = ctx.registry.get(p.tool)
            ctx.audit.log("confirm_approved", id=pid, tool=p.tool, args=p.args, via=via, tainted=p.tainted, hide=tool.audit_hide_args if tool else ())
            if tool is None:
                return ExecResult("error", p.tool, p.args, "That tool no longer exists.")
            try:
                decision = ctx.policy.decide(tool, ctx, p.args, p.tainted)
            except SandboxError as e:
                return ExecResult("blocked", p.tool, p.args, f"Blocked: {e}.", level="blocked")
            if decision.level == Level.BLOCKED:
                ctx.audit.log("blocked", tool=p.tool, args=p.args, reason=decision.reason)
                return ExecResult("blocked", p.tool, p.args, f"Blocked by the safety policy: {decision.reason}.", level="blocked")
            return self._run(tool, p.args, p.origin, p.tainted, "confirm", approved=True)

    def pending_list(self) -> list[dict]:
        with self.lock:
            self._expire()
            return [p.to_dict() for p in self.pending.values()]

    # ------------------------------------------------------------------ kill switch
    def kill(self, reason: str = "kill switch") -> None:
        with self.lock:
            self.ctx.killed.set()
            n = len(self.pending)
            self.pending.clear()
            self.ctx.audit.log("kill_switch", reason=reason, cancelled_pending=n)
            self.ctx.emit("kill", text="Kill switch pressed: Delta is paused.")
            if getattr(self.ctx, "vibe", None) is not None:
                self.ctx.vibe.on_kill()
            if self.ctx.speak:
                try:
                    self.ctx.speak("Delta paused.")
                except Exception:
                    pass

    def resume(self) -> None:
        self.ctx.killed.clear()
        self.ctx.audit.log("resume")
        self.ctx.emit("resume", text="Delta resumed.")

    # ------------------------------------------------------------------ routines
    def run_routine(self, name: str, origin: str = "routine") -> list[ExecResult]:
        r = self.ctx.routines.find(name)
        if r is None:
            return [ExecResult("error", "run_routine", {"name": name}, f"No routine called “{name}”.")]
        self.ctx.audit.log("routine_start", routine=r.name, origin=origin)
        out: list[ExecResult] = []
        for st in r.steps:
            if self.ctx.killed.is_set():
                out.append(ExecResult("killed", "routine", {}, "Routine stopped by the kill switch."))
                break
            if "wait" in st:
                self.ctx.sleep(min(float(st["wait"]), 30))
            elif "tool" in st:
                out.append(self.execute(st["tool"], st.get("args") or {}, origin=origin))
            elif "do" in st:
                intents = parse_commands(str(st["do"]), None, self.ctx.now())  # routines are not nested
                if not intents:
                    out.append(ExecResult("error", "do", {"do": st["do"]}, f"Routine step not understood: “{st['do']}”.", origin=origin))
                for it in intents:
                    out.append(self.execute(it.tool, it.args, origin=origin))
        self.ctx.audit.log("routine_end", routine=r.name, steps=len(out), ok=sum(1 for x in out if x.status in ("ok", "dry_run")))
        return out

    # ------------------------------------------------------------------ chat entry point
    def handle_message(self, text: str, origin: str = "user", session: str = "default") -> Reply:
        ctx = self.ctx
        text = (text or "").strip()
        if not text:
            return Reply("Say something and I'll do my best.")
        with self.lock:
            ctx.audit.log("user_message", text=text[:80] + ("…" if len(text) > 80 else ""), chars=len(text), origin=origin)
            ctx.memory.add_message(session, "user", text)
            reply = self._dispatch(text, origin, session)
            ctx.memory.add_message(session, "assistant", reply.text)
            return reply

    def _dispatch(self, text: str, origin: str, session: str) -> Reply:
        ctx = self.ctx
        tl = re.sub(r"[\s.!]+$", "", text.lower()).strip()
        if ctx.killed.is_set():
            if tl in ("resume", "resume delta", "unpause", "wake up"):
                self.resume()
                return Reply("Resumed. I'm listening.", source="system")
            return Reply("Delta is paused by the kill switch. Press Resume in the UI or type “resume”.", source="system")
        if tl in ("kill", "kill switch", "emergency stop", "panic"):
            self.kill("typed command")
            return Reply("Paused everything and cancelled pending approvals. Type “resume” to continue.", source="system")
        self._expire()
        # ---- confirmations ("yes"/"no" are only ever accepted from the user's own input, never from LLM output)
        m = re.fullmatch(r"(yes|confirm|approve|y|no|deny|cancel)\s+#?([0-9a-f]{6})", tl)
        if m and m.group(2) in self.pending:
            res = self.resolve(m.group(2), m.group(1) in ("yes", "confirm", "approve", "y"), via="chat-id")
            return Reply(res.text, [res], self.pending_list(), "system")
        if self.pending and tl in YES | NO:
            if tl in NO:
                results = [self.resolve(pid, False, via="chat") for pid in list(self.pending)]
                return Reply("Cancelled. " + " ".join(r.text for r in results), results, [], "system")
            plist = list(self.pending.values())
            if len(plist) > 1:
                return Reply("There are several requests waiting. Use the buttons, or say “yes <id>”: " + ", ".join(f"{p.id} ({p.description})" for p in plist), pending=self.pending_list(), source="system")
            p = plist[0]
            if p.tainted:
                return Reply(f"That request came after I read untrusted web/file text, so a plain “yes” isn't enough. Press Approve, or say “yes {p.id}” if you really want it: {p.description}.",
                             pending=self.pending_list(), source="system")
            res = self.resolve(p.id, True, via="chat")
            return Reply(res.text, [res], self.pending_list(), "system")
        # ---- 1) deterministic rules (offline, predictable)
        intents = parse_commands(text, ctx.routines, ctx.now())
        if intents:
            results = [self.execute(i.tool, i.args, origin=("rules" if origin == "user" else origin)) for i in intents]
            return self._compose(results, "rules")
        # ---- 2) LLM with tool calling
        mode = str(ctx.config.get("brain.mode", "auto"))
        if mode != "rules" and ctx.llm is not None and ctx.llm.available:
            try:
                out_text, results = self.brain.run_turn(session, text)
                rep = self._compose(results, "llm", lead=out_text)
                return rep
            except Exception as e:
                log.warning("LLM failed: %s", e)
                ctx.audit.log("llm_error", error=str(e))
                return Reply(f"I couldn't reach the language model ({e}). Rule-based commands still work: type “help”.", source="system")
        return Reply("I didn't catch that. I understand commands like “open chrome”, “volume 40”, “remind me to call mom in 10 minutes”, “find file invoice” "
                     "(type “help” for everything). To chat or handle free-form requests, connect an LLM (see README → LLM).", source="system")

    def _compose(self, results: list[ExecResult], source: str, lead: str = "") -> Reply:
        lines = [r.text for r in results if r.text]
        if source == "llm":
            extra = [r.text for r in results if r.status in ("pending", "blocked", "killed") and r.text not in lead]
            text = (lead.strip() + ("\n" + "\n".join(extra) if extra else "")).strip() or "\n".join(lines)
        else:
            text = "\n".join(lines)
        return Reply(text, results, self.pending_list(), source)
