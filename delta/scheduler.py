"""Background scheduler: fires due reminders/timers/alarms and scheduled routines. `tick()` is also called directly by tests."""
from __future__ import annotations

import logging
import threading
from datetime import datetime

log = logging.getLogger("delta")


class Scheduler:
    def __init__(self, ctx, interval: float = 5.0):
        self.ctx = ctx
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: datetime | None = None) -> list[dict]:
        ctx = self.ctx
        now = now or ctx.now()
        fired = []
        if ctx.killed.is_set():
            return fired
        for r in ctx.memory.due_reminders(now.timestamp()):
            late = now.timestamp() - r["due_ts"]
            missed = late > 120  # delta was off/asleep when it was due
            ctx.memory.mark_fired(r["id"], missed)
            title = {"timer": "Timer finished", "alarm": "Alarm"}.get(r["kind"], "Reminder")
            body = r["text"] + (" (missed while Delta was not running)" if missed else "")
            try:
                ctx.adapter.notify(f"Delta: {title}", body)
            except Exception as e:  # toast failures must never stop the scheduler
                log.warning("notification failed: %s", e)
            ctx.audit.log("reminder_fired", id=r["id"], kind=r["kind"], text=r["text"], missed=missed)
            ctx.emit("reminder", title=title, text=body, ref=r["id"], kind=r["kind"])
            if ctx.speak and not missed:
                try:
                    ctx.speak(f"{title}. {r['text']}")
                except Exception:
                    pass
            fired.append(r)
        for rt in ctx.routines.all():
            if rt.schedule and rt.schedule.is_due(now):
                key = now.strftime("%Y-%m-%d")
                if not ctx.memory.routine_ran(rt.name, key):
                    ctx.memory.mark_routine_ran(rt.name, key)
                    ctx.audit.log("routine_scheduled_start", routine=rt.name)
                    ctx.emit("routine", text=f"Running scheduled routine “{rt.name}”")
                    ctx.engine.run_routine(rt.name, origin="scheduler")
                    fired.append({"routine": rt.name})
        return fired

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(self.interval):
                try:
                    self.tick()
                except Exception:
                    log.exception("scheduler tick failed")

        self._thread = threading.Thread(target=loop, name="delta-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
