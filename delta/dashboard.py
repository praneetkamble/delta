"""Dashboard API: read-only widgets for the "Delta OS" home screen plus a handful of actions.

Rules this module follows:
* Read endpoints (vitals, processes, files, ...) read straight from the adapter / SQLite / audit log. They never change anything.
* Every action (lock, volume, add a to-do, run a routine, ...) goes through `Engine.execute`, i.e. through the same gate as
  chat, voice and routines: validation, permission level, confirm cards, dry-run, kill switch and the audit log.
* Nothing is invented: if a value is not available on this PC (no battery, no brightness control) the field is null.
"""
from __future__ import annotations

import os
import threading
import time
from collections import Counter, deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import __version__
from .registry import Level

HISTORY = 60  # samples (one per second) = 60 s of history


# ---------------------------------------------------------------------------------- vitals sampler
class VitalsSampler:
    """Keeps the last 60 one-second samples of CPU / RAM / network throughput. Thread-based; `sample_if_due` also works without the thread."""

    def __init__(self, ctx: Any, interval: float = 1.0):
        self.ctx = ctx
        self.interval = interval
        self.cpu: deque[float] = deque(maxlen=HISTORY)
        self.mem: deque[float] = deque(maxlen=HISTORY)
        self.down: deque[float] = deque(maxlen=HISTORY)
        self.up: deque[float] = deque(maxlen=HISTORY)
        self.last: dict = {}
        self._prev_net: tuple[float, int, int] | None = None
        self._last_t = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample(self) -> dict:
        a = self.ctx.adapter
        now = time.time()
        with self._lock:
            cpu = float(a.cpu_percent())
            mem = a.memory()
            net = a.network()
            down = up = 0.0
            if self._prev_net:
                dt = max(now - self._prev_net[0], 1e-3)
                down = max(0.0, (net["bytes_recv"] - self._prev_net[2]) / dt)
                up = max(0.0, (net["bytes_sent"] - self._prev_net[1]) / dt)
            self._prev_net = (now, net["bytes_sent"], net["bytes_recv"])
            self.cpu.append(round(cpu, 1))
            self.mem.append(round(float(mem["percent"]), 1))
            self.down.append(round(down))
            self.up.append(round(up))
            self.last = {"memory": mem, "network": net}
            self._last_t = now
            return self.last

    def sample_if_due(self, min_age: float = 0.9) -> None:
        if time.time() - self._last_t >= min_age:
            self.sample()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(self.interval):
                try:
                    self.sample()
                except Exception:
                    pass

        self._thread = threading.Thread(target=loop, name="delta-vitals", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


# ---------------------------------------------------------------------------------- request models
class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    when: str = Field(min_length=1, max_length=80)


class TimerIn(BaseModel):
    duration: str = Field(min_length=1, max_length=40)
    label: str = Field(default="Timer", max_length=100)


class ActionIn(BaseModel):
    value: int | None = Field(default=None, ge=0, le=100)


# action name -> (tool, fixed args, takes a 0-100 value as `percent`)
ACTIONS: dict[str, tuple[str, dict, bool]] = {
    "lock": ("lock_screen", {}, False),
    "mute": ("set_mute", {"state": "toggle"}, False),
    "volume": ("set_volume", {}, True),
    "brightness": ("set_brightness", {}, True),
    "screenshot": ("screenshot", {}, False),
    "play_pause": ("media_control", {"action": "play_pause"}, False),
    "open_vscode": ("open_app", {"name": "vs code"}, False),
    "open_terminal": ("open_app", {"name": "terminal"}, False),
    "shutdown": ("shutdown_pc", {}, False),
}


# ---------------------------------------------------------------------------------- helpers
def _greeting(now: datetime, name: str) -> str:
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    return f"Good {part}" + (f", {name}" if name else "")


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _activity_item(r: dict) -> dict | None:
    """Turn one audit record into {ts, title, detail, badge (safe|confirm|blocked), outcome}. None = not interesting."""
    ev = r.get("event", "")
    tool = r.get("tool") or ""
    nice = tool.replace("_", " ")
    ts = r.get("ts") or ""
    base = {"ts": ts, "event": ev, "tool": tool, "origin": r.get("origin") or ""}
    if ev == "tool_call":
        status = r.get("status")
        level = r.get("level") or "safe"
        badge = "confirm" if (level == "confirm" or r.get("approved")) else "safe"
        outcome = {"ok": "done", "error": "failed", "dry_run": "dry-run"}.get(status, status or "")
        return {**base, "title": nice, "detail": str(r.get("result") or "")[:140], "badge": badge, "outcome": outcome}
    if ev == "confirm_requested":
        return {**base, "title": nice, "detail": str(r.get("description") or "")[:140], "badge": "confirm", "outcome": "asked"}
    if ev == "confirm_approved":
        return {**base, "title": nice, "detail": "You approved it", "badge": "confirm", "outcome": "approved"}
    if ev in ("confirm_denied", "confirm_expired"):
        return {**base, "title": nice, "detail": "You denied it" if ev == "confirm_denied" else "No answer: it expired", "badge": "confirm",
                "outcome": "denied" if ev == "confirm_denied" else "expired"}
    if ev in ("blocked", "sandbox_violation"):
        return {**base, "title": nice, "detail": str(r.get("reason") or "")[:140], "badge": "blocked", "outcome": "blocked"}
    if ev == "kill_switch":
        return {**base, "title": "kill switch", "detail": str(r.get("reason") or ""), "badge": "blocked", "outcome": "paused"}
    if ev == "resume":
        return {**base, "title": "resume", "detail": "Delta resumed", "badge": "safe", "outcome": "resumed"}
    if ev == "dry_run_changed":
        return {**base, "title": "dry-run", "detail": "turned on" if r.get("enabled") else "turned off", "badge": "safe", "outcome": "changed"}
    if ev in ("routine_start", "routine_scheduled_start"):
        return {**base, "title": "routine · " + str(r.get("routine") or ""), "detail": "on schedule" if ev == "routine_scheduled_start" else "started by you",
                "badge": "safe", "outcome": "started"}
    if ev.startswith("vibe_"):
        proj = str(r.get("project") or "")
        what = {"vibe_run_start": ("Vibe Coding · run started", str(r.get("prompt") or ""), "started"),
                "vibe_run_end": ("Vibe Coding · run finished", f"{proj}: {r.get('changes', 0)} file change(s), {r.get('pending', 0)} waiting for review", str(r.get("status") or "done")),
                "vibe_change": ("Vibe Coding · file " + str(r.get("status") or ""), f"{proj}/{r.get('path')}", str(r.get("status") or "")),
                "vibe_command_result": ("Vibe Coding · command", f"{proj}: exit code {r.get('rc')}", "done" if r.get("rc") == 0 else "failed"),
                "vibe_undo": ("Vibe Coding · undo", f"{proj}: restored the snapshot before run {r.get('run')}", "undone"),
                "vibe_taint": ("Vibe Coding · suspicious text", f"{proj}: instruction-like text in {r.get('where')}; auto-accept paused", "flagged"),
                "vibe_auto_accept": ("Vibe Coding · auto-accept", f"{proj}: {'on' if r.get('enabled') else 'off'}", "changed"),
                "vibe_preview": ("Vibe Coding · preview", f"{proj}: {r.get('action')}", str(r.get("action") or "")),
                "vibe_error": ("Vibe Coding · error", f"{proj}: {r.get('error')}", "failed")}.get(ev)
        if what:
            badge = "blocked" if ev in ("vibe_taint", "vibe_error") else "confirm" if ev == "vibe_undo" else "safe"
            return {**base, "title": what[0], "detail": what[1][:140], "badge": badge, "outcome": what[2]}
        return None
    if ev == "reminder_fired":
        return {**base, "title": r.get("kind") or "reminder", "detail": str(r.get("text") or ""), "badge": "safe", "outcome": "fired"}
    return None


def _tool_groups(ctx: Any) -> list[dict]:
    groups: dict[str, dict] = {}
    for t in ctx.registry.all():
        g = groups.setdefault(t.category, {"name": t.category, "tools": 0, "ask_first": 0, "names": []})
        g["tools"] += 1
        g["names"].append(t.name)
        if t.always_confirm or t.level == Level.CONFIRM or t.classify:
            g["ask_first"] += 1
    return sorted(groups.values(), key=lambda g: (-g["tools"], g["name"]))


def _recent_files(ctx: Any, limit: int = 8, max_depth: int = 2, scan_cap: int = 3000) -> list[dict]:
    rows: list[dict] = []
    seen = 0
    for base in ctx.config.allowed_folders:
        if not base.is_dir():
            continue
        base_depth = len(base.parts)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if len(Path(root).parts) - base_depth >= max_depth:
                dirs[:] = []
            for f in files:
                if f.startswith("."):
                    continue
                seen += 1
                if seen > scan_cap:
                    break
                p = Path(root) / f
                try:
                    st = p.stat()
                except OSError:
                    continue
                rows.append({"name": f, "folder": base.name, "path": str(p), "size": st.st_size, "mtime": st.st_mtime,
                             "ext": p.suffix.lower().lstrip(".")})
            if seen > scan_cap:
                break
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[:limit]


def _result(res: Any, ctx: Any, state_fn) -> dict:
    return {"result": res.to_dict(), "data": res.data, "state": state_fn()}


# ---------------------------------------------------------------------------------- registration
def make_lifespan(sampler: VitalsSampler):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        sampler.start()
        try:
            yield
        finally:
            sampler.stop()
    return lifespan


def register_dashboard(app: FastAPI, ctx: Any, authed, state_dict, sampler: VitalsSampler, voice_available: bool) -> None:
    engine = ctx.engine
    dep = [Depends(authed)]

    def run(tool: str, args: dict | None = None):
        return _result(engine.execute(tool, args or {}, origin="user"), ctx, state_dict)

    # ---- briefing / status -------------------------------------------------------------------------
    @app.get("/api/briefing", dependencies=dep)
    def briefing():
        now = ctx.now()
        name = ctx.config.get("user_name", "")
        today = [r for r in ctx.memory.reminders("pending") if datetime.fromtimestamp(r["due_ts"]).date() <= now.date()]
        todos = ctx.memory.todos()
        batt = None
        try:
            batt = ctx.adapter.battery()
        except Exception:
            pass
        nxt = None
        for r in ctx.routines.all():
            if r.schedule:
                at = r.schedule.next_after(now)
                if nxt is None or at < nxt[1]:
                    nxt = (r, at)
        return {
            "greeting": _greeting(now, name), "name": name, "now": now.isoformat(timespec="seconds"),
            "date": now.strftime("%A, %d %B %Y"), "time": _clock(now),
            "reminders_today": [{"id": r["id"], "text": r["text"], "kind": r["kind"], "at": _clock(datetime.fromtimestamp(r["due_ts"]))} for r in today[:6]],
            "reminders_pending": len(ctx.memory.reminders("pending")), "todos_open": len(todos),
            "battery": batt, "next_routine": ({"name": nxt[0].name, "schedule": nxt[0].schedule_text, "at": nxt[1].isoformat(timespec="minutes")} if nxt else None),
        }

    @app.get("/api/status", dependencies=dep)
    def status():
        llm = ctx.llm
        base = (ctx.config.get("llm.base_url", "") or "") if llm else ""
        host = base.split("://")[-1].split("/")[0] if base else ""
        sched = ctx.scheduler
        return {
            "version": __version__, "adapter": ctx.adapter.describe(), "demo": not ctx.adapter.is_real,
            "uptime_s": int(time.time() - ctx.started), "tools": len(ctx.registry.all()),
            "llm": {"configured": bool(base), "available": bool(llm and llm.available), "model": (llm.model if llm and llm.available else ""),
                    "host": host, "local": host.split(":")[0] in ("localhost", "127.0.0.1", "::1", "[::1]") if host else False,
                    "mode": ctx.config.get("brain.mode")},
            "voice": {"available": voice_available, "speaks": bool(ctx.speak), "hotkey": ctx.config.get("voice.hotkey")},
            "scheduler": {"running": bool(sched and sched.running) if sched is not None else None},
            "sampler": sampler.running,
        }

    # ---- live vitals -------------------------------------------------------------------------------
    @app.get("/api/vitals", dependencies=dep)
    def vitals():
        if not sampler.cpu:
            sampler.sample()
        else:
            sampler.sample_if_due()
        a = ctx.adapter
        mem = sampler.last.get("memory") or a.memory()
        net = sampler.last.get("network") or a.network()
        disks = a.disks()
        main = disks[0] if disks else None
        try:
            batt = a.battery()
        except Exception:
            batt = None
        return {
            "ts": time.time(), "interval_s": sampler.interval, "demo": not a.is_real,
            "cpu": {"percent": sampler.cpu[-1] if sampler.cpu else 0.0, "history": list(sampler.cpu)},
            "memory": {"percent": mem["percent"], "used": mem["used"], "total": mem["total"], "history": list(sampler.mem)},
            "disk": ({"percent": main["percent"], "used": main["used"], "total": main["total"], "mount": main["mount"]} if main else None),
            "disks": disks[:4],
            "battery": batt,
            "network": {"down_bps": sampler.down[-1] if sampler.down else 0, "up_bps": sampler.up[-1] if sampler.up else 0,
                        "down_history": list(sampler.down), "up_history": list(sampler.up), "addresses": net["addresses"][:3]},
        }

    @app.get("/api/processes", dependencies=dep)
    def processes(sort: str = "cpu", limit: int = 6):
        if sort not in ("cpu", "memory"):
            raise HTTPException(status_code=422, detail="sort must be cpu or memory")
        return {"sort": sort, "processes": ctx.adapter.processes(max(1, min(limit, 25)), sort)}

    # ---- quick actions (through the gate) ----------------------------------------------------------
    @app.get("/api/controls", dependencies=dep)
    def controls():
        a = ctx.adapter
        out: dict = {"volume": None, "muted": None, "brightness": None}
        for key, fn in (("volume", a.get_volume), ("muted", a.get_muted), ("brightness", a.get_brightness)):
            try:
                out[key] = fn()
            except Exception:
                pass
        return out

    @app.post("/api/actions/{name}", dependencies=dep)
    def action(name: str, body: ActionIn | None = None):
        spec = ACTIONS.get(name)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"unknown action {name!r}")
        tool, fixed, needs_value = spec
        args = dict(fixed)
        if needs_value:
            if body is None or body.value is None:
                raise HTTPException(status_code=422, detail="this action needs a value 0-100")
            args["percent"] = body.value
        return run(tool, args)

    # ---- tasks: to-dos, reminders, timers ----------------------------------------------------------
    @app.get("/api/tasks", dependencies=dep)
    def tasks():
        now = ctx.now()
        rem = [{"id": r["id"], "text": r["text"], "kind": r["kind"], "due_ts": r["due_ts"],
                "due": _due_label(datetime.fromtimestamp(r["due_ts"]), now)} for r in ctx.memory.reminders("pending")[:20]]
        return {"todos": ctx.memory.todos()[:30], "reminders": rem}

    @app.post("/api/todos", dependencies=dep)
    def add_todo(body: TextIn):
        return run("add_todo", {"text": body.text})

    @app.post("/api/todos/{tid}/done", dependencies=dep)
    def done_todo(tid: int):
        return run("complete_todo", {"id": tid})

    @app.delete("/api/todos/{tid}", dependencies=dep)
    def del_todo(tid: int):
        return run("delete_todo", {"id": tid})

    @app.post("/api/reminders", dependencies=dep)
    def add_reminder(body: ReminderIn):
        return run("set_reminder", {"text": body.text, "when": body.when})

    @app.post("/api/timers", dependencies=dep)
    def add_timer(body: TimerIn):
        return run("set_timer", {"duration": body.duration, "label": body.label or "Timer"})

    @app.delete("/api/reminders/{rid}", dependencies=dep)
    def cancel_reminder(rid: int):
        return run("cancel_reminder", {"id": rid})

    # ---- memory: notes + remembered facts ----------------------------------------------------------
    @app.get("/api/notes", dependencies=dep)
    def notes(limit: int = 20):
        rows = ctx.memory.notes(max(1, min(limit, 100)))
        return {"notes": [{"id": n["id"], "text": n["text"], "ts": n["ts"]} for n in rows], "facts": ctx.memory.facts()[:30]}

    @app.post("/api/notes", dependencies=dep)
    def add_note(body: TextIn):
        return run("add_note", {"text": body.text})

    # ---- activity (audit log, humanised) -----------------------------------------------------------
    @app.get("/api/activity", dependencies=dep)
    def activity(limit: int = 30):
        limit = max(1, min(limit, 100))
        items = []
        for r in reversed(ctx.audit.tail(400)):
            it = _activity_item(r)
            if it:
                items.append(it)
            if len(items) >= limit:
                break
        counts = Counter(i["badge"] for i in items)
        return {"items": items, "counts": dict(counts), "chain_ok": ctx.audit.verify()[0]}

    # ---- routines ----------------------------------------------------------------------------------
    @app.get("/api/routines", dependencies=dep)
    def routines():
        now = ctx.now()
        key = now.strftime("%Y-%m-%d")
        out = []
        for r in ctx.routines.all():
            steps = [str(s.get("do") or s.get("tool") or f"wait {s.get('wait')}s") for s in r.steps]
            out.append({"name": r.name, "description": r.description, "schedule": r.schedule_text or None, "triggers": r.triggers[:4],
                        "steps": steps, "next_run": (r.schedule.next_after(now).isoformat(timespec="minutes") if r.schedule else None),
                        "ran_today": bool(ctx.memory.routine_ran(r.name, key))})
        return {"routines": out}

    @app.post("/api/routines/{name}/run", dependencies=dep)
    def run_routine(name: str):
        if ctx.routines.find(name) is None:
            raise HTTPException(status_code=404, detail=f"no routine called {name!r}")
        res = engine.run_routine(name, origin="user")
        return {"results": [r.to_dict() for r in res], "state": state_dict()}

    # ---- modules (honest "agents": the real parts of Delta) ----------------------------------------
    @app.get("/api/modules", dependencies=dep)
    def modules():
        killed = ctx.killed.is_set()
        sched = ctx.scheduler
        llm = ctx.llm
        st = (lambda ok_: "paused" if killed else ("active" if ok_ else "standby"))
        core = [
            {"id": "gate", "name": "Safety gate", "detail": "validates, asks, audits every action", "status": "paused" if killed else "active", "kind": "core"},
            {"id": "scheduler", "name": "Scheduler", "detail": "reminders, timers, scheduled routines",
             "status": ("standby" if sched is None else "active" if sched.running else "error"), "kind": "core"},
            {"id": "llm", "name": "Language model", "detail": (llm.model if llm and llm.available else "rules only (offline)"), "status": st(bool(llm and llm.available)), "kind": "core"},
            {"id": "voice", "name": "Voice", "detail": "push-to-talk" if voice_available else "not enabled", "status": st(voice_available), "kind": "core"},
        ]
        groups = [{"id": "skill:" + g["name"], "name": g["name"].replace("_", " ").title(), "detail": f"{g['tools']} tools" + (f", {g['ask_first']} ask first" if g["ask_first"] else ""),
                   "status": "paused" if killed else "active", "kind": "skill", "tools": g["tools"], "ask_first": g["ask_first"]} for g in _tool_groups(ctx)]
        return {"modules": core + groups, "tools_total": len(ctx.registry.all()), "killed": killed}

    # ---- files -------------------------------------------------------------------------------------
    @app.get("/api/files/recent", dependencies=dep)
    def recent_files(limit: int = 8):
        return {"files": _recent_files(ctx, max(1, min(limit, 30))),
                "folders": [{"name": p.name or str(p), "path": str(p), "exists": p.is_dir()} for p in ctx.config.allowed_folders]}

    @app.post("/api/files/open", dependencies=dep)
    def open_file(body: TextIn):
        return run("open_path", {"path": body.text})

    # ---- safety panel ------------------------------------------------------------------------------
    @app.get("/api/safety", dependencies=dep)
    def safety():
        ok_, bad = ctx.audit.verify()
        tools = ctx.registry.all()
        return {
            "killed": ctx.killed.is_set(), "dry_run": ctx.dry_run, "kill_hotkey": ctx.config.get("safety.kill_switch_hotkey"),
            "confirm_timeout_s": ctx.config.get("safety.confirm_timeout_s", 120), "redact_secrets": bool(ctx.config.get("safety.redact_secrets", True)),
            "allowed_folders": [{"path": str(p), "exists": p.is_dir()} for p in ctx.config.allowed_folders],
            "blocked_tools": list(ctx.config.get("safety.blocked_tools", []) or []),
            "audit": {"ok": ok_, "first_bad_line": bad}, "pending": engine.pending_list(),
            "tools": {"total": len(tools), "always_ask": sum(1 for t in tools if t.always_confirm or t.level == Level.CONFIRM)},
        }


def _due_label(due: datetime, now: datetime) -> str:
    if due.date() == now.date():
        return "today " + _clock(due)
    if (due.date() - now.date()).days == 1:
        return "tomorrow " + _clock(due)
    return due.strftime("%a %d %b ") + _clock(due)
