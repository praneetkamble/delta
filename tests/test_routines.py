from datetime import datetime, timedelta

import pytest

from delta.routines import RoutineBook, Schedule
from delta.scheduler import Scheduler

from conftest import FIXED_NOW

YAML = """
routines:
  work mode:
    description: Start the work setup
    triggers: [start work]
    schedule: "weekdays 09:30"
    steps:
      - do: open vs code
      - do: open chrome and spotify
      - tool: set_volume
        args: {percent: 25}
      - wait: 2
  cleanup:
    steps:
      - do: organize downloads
  end of day:
    steps:
      - do: shut down
  broken one:
    schedule: "whenever you like"
    steps: [{do: open chrome}]
  bad step:
    steps: [{nonsense: 1}]
  typo tool:
    steps: [{tool: no_such_tool}]
"""


@pytest.fixture
def rctx(make_ctx):
    c = make_ctx()
    (c.config.data_dir / "routines.yaml").write_text(YAML)
    c.routines = RoutineBook.load(c.config.data_dir / "routines.yaml")
    return c


def test_yaml_loads_and_reports_problems(rctx):
    names = [r.name for r in rctx.routines.all()]
    assert names == ["work mode", "cleanup", "end of day", "typo tool"]
    assert len(rctx.routines.warnings) == 2 and any("whenever" in w for w in rctx.routines.warnings)
    assert any("no_such_tool" in p for p in rctx.routines.validate(rctx.registry))


def test_find_by_name_alias_and_trigger(rctx):
    for q in ("work mode", "Work", "the work routine", "start work"):
        assert rctx.routines.find(q).name == "work mode"
    assert rctx.routines.find("nope") is None


def test_work_mode_runs_all_steps(rctx):
    adapter = rctx.adapter
    r = rctx.engine.handle_message("work mode")
    assert r.results[0].tool == "run_routine" and r.results[0].status == "ok"
    opened = [c[1] for c in adapter.calls if c[0] == "open_app"]
    assert opened == ["code", "chrome", "spotify:"] and adapter.volume == 25


def test_routine_steps_still_go_through_the_gate(rctx):
    adapter = rctx.adapter
    res = rctx.engine.run_routine("end of day")
    assert res[0].status == "pending" and not [c for c in adapter.calls if c[0] == "shutdown"]
    res = rctx.engine.run_routine("cleanup")
    assert res[0].status == "pending"


def test_dry_run_applies_to_routines(rctx):
    adapter = rctx.adapter
    rctx.dry_run = True
    res = rctx.engine.run_routine("work mode")
    assert all(x.status == "dry_run" for x in res) and not adapter.calls


def test_kill_switch_stops_a_routine(rctx):
    adapter = rctx.adapter
    seen = []
    orig = rctx.engine.execute

    def spy(*a, **k):
        r = orig(*a, **k)
        seen.append(r.tool)
        if len(seen) == 1:
            rctx.killed.set()
        return r
    rctx.engine.execute = spy
    res = rctx.engine.run_routine("work mode")
    assert res[-1].status == "killed" and len([c for c in adapter.calls if c[0] == "open_app"]) == 1


def test_unknown_routine(rctx):
    assert rctx.engine.run_routine("nothing")[0].status == "error"


@pytest.mark.parametrize("text,ok", [("daily 08:30", True), ("weekdays 09:00", True), ("weekly mon 18:00", True), ("weekly monday 18:00", True),
                                     ("every hour", False), ("daily 8", False), ("", False)])
def test_schedule_parse(text, ok):
    if ok:
        assert Schedule.parse(text)
    else:
        with pytest.raises(ValueError):
            Schedule.parse(text)


def test_schedule_window_and_days():
    s = Schedule.parse("weekdays 09:30")
    thu = datetime(2026, 10, 15)
    assert not s.is_due(thu.replace(hour=9, minute=29))
    assert s.is_due(thu.replace(hour=9, minute=30)) and s.is_due(thu.replace(hour=11, minute=0))
    assert not s.is_due(thu.replace(hour=11, minute=31))            # too late: don't run a morning routine in the afternoon
    assert not s.is_due(datetime(2026, 10, 17, 9, 45))              # Saturday
    w = Schedule.parse("weekly mon 18:00")
    assert w.is_due(datetime(2026, 10, 19, 18, 5)) and not w.is_due(thu.replace(hour=18, minute=5))


def test_scheduled_routine_runs_once_per_day(rctx):
    adapter = rctx.adapter
    s = Scheduler(rctx)
    t = datetime(2026, 10, 15, 9, 31)
    assert s.tick(t) == [{"routine": "work mode"}]
    assert s.tick(t + timedelta(minutes=1)) == []
    assert [c[1] for c in adapter.calls if c[0] == "open_app"][0] == "code"
    n = len(adapter.calls)
    s.tick(datetime(2026, 10, 16, 9, 31))                             # next day: runs again
    assert len(adapter.calls) > n


def test_scheduled_routine_cannot_run_confirm_steps_unattended(rctx):
    adapter = rctx.adapter
    rctx.routines._r["end of day"].schedule = Schedule.parse("daily 09:00")
    Scheduler(rctx).tick(datetime(2026, 10, 15, 9, 1))
    assert rctx.engine.pending and not [c for c in adapter.calls if c[0] == "shutdown"]


def test_routines_missing_file_is_fine(tmp_path):
    assert RoutineBook.load(tmp_path / "nope.yaml").all() == []
    p = tmp_path / "bad.yaml"
    p.write_text("routines: [unclosed")
    assert RoutineBook.load(p).warnings


def test_example_file_is_valid(tmp_path):
    from pathlib import Path
    from delta.context import build_context
    from delta.config import Config
    book = RoutineBook.load(Path(__file__).resolve().parents[1] / "routines.example.yaml")
    assert not book.warnings and len(book.all()) >= 3
    c = build_context(Config({"data_dir": str(tmp_path)}))
    assert book.validate(c.registry) == []
