from datetime import datetime, timedelta

from delta.adapters.mock import MockAdapter
from delta.config import Config
from delta.context import build_context
from delta.llm import LLMClient
from delta.scheduler import Scheduler

from conftest import FIXED_NOW, make_cfg


def test_set_list_cancel(eng):
    r = eng.handle_message("remind me to call mom in 10 minutes")
    assert r.results[0].status == "ok"
    rid = r.results[0].data["id"]
    assert "call mom" in eng.handle_message("list reminders").text
    assert eng.handle_message(f"cancel reminder {rid}").results[0].status == "ok"
    assert "no pending" in eng.handle_message("list reminders").text.lower()


def test_reminder_fires_once_on_time(ctx, eng, adapter):
    eng.handle_message("remind me to stretch in 10 minutes")
    s = Scheduler(ctx)
    assert s.tick(FIXED_NOW + timedelta(minutes=5)) == []
    fired = s.tick(FIXED_NOW + timedelta(minutes=10, seconds=1))
    assert len(fired) == 1
    assert adapter.notifications[-1] == ("Delta: Reminder", "stretch")
    assert s.tick(FIXED_NOW + timedelta(minutes=11)) == []           # never twice
    assert any(e["type"] == "reminder" for e in ctx.events)
    assert any(e["event"] == "reminder_fired" for e in ctx.audit.tail(10))


def test_timer_and_alarm(ctx, eng, adapter):
    t = eng.handle_message("set a 5 minute timer").results[0]
    a = eng.handle_message("set an alarm for 7:30 am").results[0]
    assert t.status == a.status == "ok"
    s = Scheduler(ctx)
    s.tick(FIXED_NOW + timedelta(minutes=6))
    assert adapter.notifications[-1][0] == "Delta: Timer finished"
    s.tick(datetime(2026, 10, 16, 7, 31))
    assert adapter.notifications[-1][0] == "Delta: Alarm"


def test_reminders_persist_across_restart_and_missed_are_flagged(tmp_path, home):
    cfg = make_cfg(tmp_path, home)
    c1 = build_context(cfg, adapter=MockAdapter(trash_dir=tmp_path / "t"), llm=LLMClient("", ""))
    c1.clock = lambda: FIXED_NOW
    c1.engine.handle_message("remind me to pay rent in 30 minutes")
    c1.memory.close()
    # Delta was off; it starts again 3 hours later
    ad2 = MockAdapter(trash_dir=tmp_path / "t")
    c2 = build_context(make_cfg(tmp_path, home), adapter=ad2, llm=LLMClient("", ""))
    assert len(c2.memory.reminders("pending")) == 1
    Scheduler(c2).tick(FIXED_NOW + timedelta(hours=3))
    assert "missed" in ad2.notifications[-1][1]
    assert c2.memory.reminders("fired")[0]["missed"] == 1


def test_bad_times_are_rejected_politely(eng):
    r = eng.execute("set_reminder", {"text": "x", "when": "whenever"})
    assert r.status == "error" and "couldn't understand" in r.text
    assert eng.execute("set_timer", {"duration": "soon"}).status == "error"
    assert eng.execute("set_reminder", {"text": "x", "when": "2020-01-01T10:00"}).status == "error"  # in the past


def test_iso_time_from_llm_is_accepted(eng):
    assert eng.execute("set_reminder", {"text": "x", "when": "2026-10-16T09:00"}).status == "ok"


def test_scheduler_does_nothing_while_killed(ctx, eng):
    eng.handle_message("remind me to x in 1 minute")
    eng.kill()
    assert Scheduler(ctx).tick(FIXED_NOW + timedelta(minutes=5)) == []
    assert len(ctx.memory.reminders("pending")) == 1


def test_notification_failure_does_not_lose_the_reminder(ctx, eng, adapter):
    def boom(*a):
        raise RuntimeError("toast broke")
    adapter.notify = boom
    eng.handle_message("remind me to x in 1 minute")
    assert len(Scheduler(ctx).tick(FIXED_NOW + timedelta(minutes=2))) == 1
    assert ctx.memory.reminders("fired")
