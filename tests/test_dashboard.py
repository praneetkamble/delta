"""Dashboard API: read endpoints, actions through the gate, and the new helpers (next_after, demo motion, sampler)."""
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from delta.adapters.mock import MockAdapter
from delta.dashboard import ACTIONS, VitalsSampler, _activity_item
from delta.routines import Routine, RoutineBook, Schedule
from delta.server import create_app

TOKEN = "d" * 32
NOW = datetime(2026, 10, 15, 10, 0, 0)   # a Thursday


@pytest.fixture
def client(ctx):
    app = create_app(ctx, TOKEN, 8765)
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    c.cookies.set("delta_token", TOKEN)
    return c


@pytest.fixture
def anon(ctx):
    return TestClient(create_app(ctx, TOKEN, 8765), base_url="http://127.0.0.1:8765")


READ_ENDPOINTS = ["/api/briefing", "/api/status", "/api/vitals", "/api/processes", "/api/controls", "/api/tasks", "/api/notes",
                  "/api/activity", "/api/routines", "/api/modules", "/api/files/recent", "/api/safety"]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_every_dashboard_read_endpoint_needs_the_token(anon, client, path):
    assert anon.get(path).status_code == 401
    assert client.get(path).status_code == 200


def test_dashboard_write_endpoints_need_the_token(anon):
    for method, path, body in [("post", "/api/todos", {"text": "x"}), ("post", "/api/actions/lock", None), ("post", "/api/notes", {"text": "x"}),
                               ("post", "/api/reminders", {"text": "x", "when": "in 5 minutes"}), ("post", "/api/routines/work mode/run", None),
                               ("delete", "/api/todos/1", None), ("post", "/api/files/open", {"text": "x"})]:
        assert getattr(anon, method)(path, **({"json": body} if body else {})).status_code == 401


def test_assets_are_whitelisted_and_need_the_token(anon, client):
    assert anon.get("/assets/dashboard.css").status_code == 401
    assert client.get("/assets/../server.py").status_code in (404, 422)
    assert client.get("/assets/secrets.txt").status_code == 404
    css = client.get("/assets/dashboard.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert client.get("/assets/Geist.woff2").headers["content-type"] == "font/woff2"
    assert client.get("/assets/dashboard.js").headers["content-type"].startswith("text/javascript")


def test_index_is_the_dashboard_with_a_strict_csp(client):
    page = client.get("/")
    assert page.status_code == 200 and "DELTA" in page.text
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "http://" not in page.text.replace("http://www.w3.org", "") and "https://" not in page.text   # no CDN / external links


def test_briefing_has_greeting_date_and_counts(client, ctx):
    ctx.memory.add_todo("write tests")
    ctx.memory.add_reminder("call mom", datetime(2026, 10, 15, 18, 0))
    b = client.get("/api/briefing").json()
    assert b["greeting"] == "Good morning, Praneet" and b["date"] == "Thursday, 15 October 2026" and b["time"] == "10:00 AM"
    assert b["todos_open"] == 1 and b["reminders_today"][0]["text"] == "call mom" and b["reminders_today"][0]["at"] == "6:00 PM"
    assert b["battery"]["percent"] == 78


def test_briefing_reports_the_next_scheduled_routine(client, ctx):
    ctx.routines = RoutineBook([Routine("morning briefing", schedule=Schedule.parse("weekdays 09:00"), schedule_text="weekdays 09:00")])
    nxt = client.get("/api/briefing").json()["next_routine"]
    assert nxt == {"name": "morning briefing", "schedule": "weekdays 09:00", "at": "2026-10-16T09:00"}


def test_status_is_honest_about_demo_llm_and_voice(client):
    s = client.get("/api/status").json()
    assert s["demo"] is True and s["adapter"] == {"name": "mock", "real": False}
    assert s["llm"]["configured"] is False and s["llm"]["available"] is False and s["tools"] >= 60
    assert s["voice"]["available"] is False and s["scheduler"]["running"] is None


def test_status_knows_a_local_llm(ctx):
    from delta.llm import LLMClient
    ctx.llm = LLMClient("http://localhost:11434/v1", "llama3.1:8b")
    ctx.config.set("llm.base_url", "http://localhost:11434/v1")
    c = TestClient(create_app(ctx, TOKEN, 8765), base_url="http://127.0.0.1:8765")
    c.cookies.set("delta_token", TOKEN)
    llm = c.get("/api/status").json()["llm"]
    assert llm["configured"] and llm["local"] is True and llm["host"] == "localhost:11434"


def test_vitals_shape_and_history(client):
    v = client.get("/api/vitals").json()
    assert v["cpu"]["percent"] == 17.5 and v["memory"]["percent"] == 60.0 and v["demo"] is True
    assert v["disk"] == {"percent": 58.8, "used": 301 * 10**9, "total": 512 * 10**9, "mount": "C:\\"}
    assert v["battery"] == {"percent": 78, "plugged": False, "secs_left": 14400}
    assert v["network"]["addresses"][0]["ip"] == "192.168.1.23" and v["network"]["down_bps"] == 0
    assert len(v["cpu"]["history"]) >= 1 and len(v["cpu"]["history"]) <= 60


def test_vitals_without_battery_is_null_not_invented(client, ctx):
    ctx.adapter.battery = lambda: None
    assert client.get("/api/vitals").json()["battery"] is None


def test_sampler_keeps_60_samples_and_computes_network_rates(ctx):
    s = VitalsSampler(ctx)
    ad = ctx.adapter
    n = iter(range(100))
    def net():
        i = next(n)
        return {"addresses": [], "bytes_sent": 1000 * i, "bytes_recv": 5000 * i}
    ad.network = net
    for _ in range(70):
        s.sample()
    assert len(s.cpu) == len(s.mem) == len(s.down) == 60
    assert all(x >= 0 for x in s.down) and s.down[-1] > 0


def test_sampler_never_reports_negative_rates_when_counters_reset(ctx):
    s = VitalsSampler(ctx)
    vals = iter([(1000, 1000), (10, 10), (50, 50)])
    ctx.adapter.network = lambda: dict(zip(("bytes_sent", "bytes_recv"), next(vals)), addresses=[])
    for _ in range(3):
        s.sample()
    assert min(s.down) >= 0 and min(s.up) >= 0


def test_sampler_thread_starts_and_stops(ctx):
    s = VitalsSampler(ctx, interval=0.05)
    s.start()
    time.sleep(0.3)
    assert s.running is True
    s.stop()
    assert len(s.cpu) >= 2


def test_demo_motion_moves_but_default_mock_is_deterministic(tmp_path):
    steady = MockAdapter(trash_dir=tmp_path)
    assert steady.cpu_percent() == 17.5 and steady.memory()["percent"] == 60.0
    demo = MockAdapter(trash_dir=tmp_path, demo_motion=True)
    seen = set()
    for i in range(4):
        demo._t0 -= 2.5 * i
        seen.add(demo.cpu_percent())
    assert len(seen) > 1 and all(3 <= x <= 95 for x in seen)
    prev = None
    for t in [x * 0.25 for x in range(0, 200)]:           # the simulated byte counters only ever go up (rates stay positive)
        demo._t0 = time.time() - t
        cur = demo.network()
        if prev:
            assert cur["bytes_recv"] >= prev["bytes_recv"] and cur["bytes_sent"] >= prev["bytes_sent"]
        prev = cur


def test_get_adapter_enables_demo_motion_only_on_the_mock_path(tmp_path):
    from delta.adapters import get_adapter
    from delta.config import Config
    ad = get_adapter(Config({"adapter": "mock", "data_dir": str(tmp_path)}))
    assert ad.name == "mock" and ad.demo_motion is True


def test_processes_sorted_and_validated(client):
    p = client.get("/api/processes?sort=cpu&limit=2").json()
    assert [x["name"] for x in p["processes"]] == ["chrome.exe", "Code.exe"]
    m = client.get("/api/processes?sort=memory&limit=1").json()
    assert m["processes"][0]["name"] == "chrome.exe"
    assert client.get("/api/processes?sort=evil").status_code == 422


def test_controls_reports_current_values(client, adapter):
    assert client.get("/api/controls").json() == {"volume": 35, "muted": False, "brightness": 70}
    adapter.brightness = None
    assert client.get("/api/controls").json()["brightness"] is None


# ---------------------------------------------------------------- actions go through the gate
def test_volume_action_runs_and_is_audited(client, adapter, ctx):
    r = client.post("/api/actions/volume", json={"value": 42}).json()
    assert r["result"]["status"] == "ok" and adapter.volume == 42
    assert any(e.get("tool") == "set_volume" and e.get("origin") == "user" for e in ctx.audit.tail(10))


def test_volume_action_validates_the_value(client, adapter):
    assert client.post("/api/actions/volume", json={"value": 101}).status_code == 422
    assert client.post("/api/actions/volume", json={}).status_code == 422
    assert client.post("/api/actions/volume").status_code == 422
    assert adapter.volume == 35


def test_unknown_action_is_404(client):
    assert client.post("/api/actions/format_c").status_code == 404


def test_mute_toggle_and_media_and_screenshot(client, adapter):
    assert client.post("/api/actions/mute").json()["result"]["status"] == "ok" and adapter.muted is True
    assert client.post("/api/actions/play_pause").json()["result"]["status"] == "ok" and ("media_key", "play_pause") in adapter.calls
    assert client.post("/api/actions/screenshot").json()["result"]["status"] == "ok"


def test_open_vscode_action_launches_a_known_app(client, adapter):
    r = client.post("/api/actions/open_vscode").json()
    assert r["result"]["status"] == "ok" and any(c[0] == "open_app" for c in adapter.calls)


def test_shutdown_action_asks_first_and_does_nothing_until_approved(client, adapter):
    r = client.post("/api/actions/shutdown").json()
    assert r["result"]["status"] == "pending" and r["result"]["pending_id"]
    assert not any(c[0] == "shutdown" for c in adapter.calls)
    assert r["state"]["pending"][0]["tool"] == "shutdown_pc"
    ok = client.post("/api/confirm", json={"id": r["result"]["pending_id"], "approve": True}).json()
    assert ok["result"]["status"] == "ok" and any(c[0] == "shutdown" for c in adapter.calls)


def test_shutdown_action_deny_path(client, adapter):
    pid = client.post("/api/actions/shutdown").json()["result"]["pending_id"]
    r = client.post("/api/confirm", json={"id": pid, "approve": False}).json()
    assert r["result"]["status"] == "denied" and not any(c[0] == "shutdown" for c in adapter.calls)


def test_actions_respect_the_kill_switch_and_dry_run(client, adapter, ctx):
    ctx.dry_run = True
    r = client.post("/api/actions/volume", json={"value": 10}).json()
    assert r["result"]["status"] == "dry_run" and adapter.volume == 35
    ctx.dry_run = False
    client.post("/api/kill")
    r = client.post("/api/actions/volume", json={"value": 10}).json()
    assert r["result"]["status"] == "killed" and adapter.volume == 35
    client.post("/api/resume")
    assert client.post("/api/actions/volume", json={"value": 10}).json()["result"]["status"] == "ok"


def test_every_action_maps_to_a_registered_tool(ctx):
    for name, (tool, fixed, _) in ACTIONS.items():
        assert ctx.registry.get(tool) is not None, name


def test_blocked_tools_config_also_blocks_dashboard_actions(make_ctx):
    ctx = make_ctx(safety={"blocked_tools": ["lock_screen"]})
    c = TestClient(create_app(ctx, TOKEN, 8765), base_url="http://127.0.0.1:8765")
    c.cookies.set("delta_token", TOKEN)
    r = c.post("/api/actions/lock").json()
    assert r["result"]["status"] == "blocked" and not any(x[0] == "lock" for x in ctx.adapter.calls)


# ---------------------------------------------------------------- tasks, reminders, notes
def test_todo_lifecycle(client, ctx):
    t = client.post("/api/todos", json={"text": "Send the invoice"}).json()
    tid = t["data"]["id"]
    assert t["result"]["status"] == "ok"
    assert [x["text"] for x in client.get("/api/tasks").json()["todos"]] == ["Send the invoice"]
    assert client.post(f"/api/todos/{tid}/done").json()["result"]["status"] == "ok"
    assert client.get("/api/tasks").json()["todos"] == []
    assert client.post(f"/api/todos/{tid}/done").json()["result"]["status"] == "error"   # already done
    tid2 = client.post("/api/todos", json={"text": "b"}).json()["data"]["id"]
    assert client.delete(f"/api/todos/{tid2}").json()["result"]["status"] == "ok"


def test_todo_text_is_validated(client):
    assert client.post("/api/todos", json={"text": ""}).status_code == 422
    assert client.post("/api/todos", json={"text": "x" * 501}).status_code == 422
    assert client.post("/api/todos", json={}).status_code == 422


def test_reminder_and_timer_and_cancel(client):
    r = client.post("/api/reminders", json={"text": "stretch", "when": "in 20 minutes"}).json()
    assert r["result"]["status"] == "ok"
    t = client.post("/api/timers", json={"duration": "10 minutes", "label": "Tea"}).json()
    assert t["result"]["status"] == "ok"
    tasks = client.get("/api/tasks").json()["reminders"]
    assert {x["text"] for x in tasks} == {"stretch", "Tea"} and {x["kind"] for x in tasks} == {"reminder", "timer"}
    assert tasks[0]["due"].startswith("today ")
    assert client.delete(f"/api/reminders/{r['data']['id']}").json()["result"]["status"] == "ok"
    assert [x["text"] for x in client.get("/api/tasks").json()["reminders"]] == ["Tea"]


def test_bad_reminder_time_is_a_friendly_error_not_a_crash(client):
    r = client.post("/api/reminders", json={"text": "x", "when": "whenever"}).json()
    assert r["result"]["status"] == "error" and "couldn't understand" in r["result"]["text"]


def test_notes_and_facts(client, ctx):
    assert client.get("/api/notes").json() == {"notes": [], "facts": []}
    n = client.post("/api/notes", json={"text": "buy cables"}).json()
    assert n["result"]["status"] == "ok"
    ctx.memory.add_fact("my name is Sam")
    out = client.get("/api/notes").json()
    assert out["notes"][0]["text"] == "buy cables" and out["facts"][0]["text"] == "my name is Sam"


# ---------------------------------------------------------------- activity
def test_activity_labels_safe_confirm_and_blocked(client):
    client.post("/api/chat", json={"message": "volume 50"})
    client.post("/api/chat", json={"message": "shut down"})
    client.post("/api/chat", json={"message": "command: format c:"})
    act = client.get("/api/activity?limit=40").json()
    badges = {(i["tool"], i["badge"], i["outcome"]) for i in act["items"]}
    assert ("set_volume", "safe", "done") in badges
    assert ("shutdown_pc", "confirm", "asked") in badges
    assert any(i["badge"] == "blocked" for i in act["items"]) or any(i["badge"] == "confirm" and i["tool"] == "run_command" for i in act["items"])
    assert act["chain_ok"] is True and "safe" in act["counts"]
    assert act["items"][0]["ts"] >= act["items"][-1]["ts"]   # newest first


def test_activity_item_mapping_unit():
    assert _activity_item({"event": "user_message", "text": "hi"}) is None
    assert _activity_item({"event": "blocked", "tool": "kill_process", "reason": "protected"})["badge"] == "blocked"
    assert _activity_item({"event": "tool_call", "tool": "lock_screen", "status": "ok", "level": "safe"})["badge"] == "safe"
    assert _activity_item({"event": "tool_call", "tool": "delete_file", "status": "ok", "level": "confirm", "approved": True})["badge"] == "confirm"
    assert _activity_item({"event": "confirm_denied", "tool": "x"})["outcome"] == "denied"
    assert _activity_item({"event": "kill_switch", "reason": "UI button"})["badge"] == "blocked"


def test_activity_limit_is_clamped(client):
    for i in range(5):
        client.post("/api/actions/volume", json={"value": i})
    assert len(client.get("/api/activity?limit=3").json()["items"]) == 3
    assert len(client.get("/api/activity?limit=0").json()["items"]) == 1


def test_activity_never_leaks_secrets(client, ctx):
    ctx.audit.log("tool_call", tool="x", status="ok", level="safe", result="password=hunter2hunter2 token=abcdef", api_key="sk-live-123")
    raw = str(client.get("/api/activity").json())
    assert "sk-live-123" not in raw


# ---------------------------------------------------------------- routines
def test_next_after_handles_weekdays_weekly_and_daily():
    thu = datetime(2026, 10, 15, 10, 0)
    assert Schedule.parse("daily 08:30").next_after(thu) == datetime(2026, 10, 16, 8, 30)
    assert Schedule.parse("daily 18:00").next_after(thu) == datetime(2026, 10, 15, 18, 0)
    fri_eve = datetime(2026, 10, 16, 20, 0)
    assert Schedule.parse("weekdays 09:00").next_after(fri_eve) == datetime(2026, 10, 19, 9, 0)   # skips the weekend
    assert Schedule.parse("weekly mon 18:00").next_after(thu) == datetime(2026, 10, 19, 18, 0)
    assert Schedule.parse("daily 10:00").next_after(thu) == datetime(2026, 10, 16, 10, 0)           # strictly after


def test_routines_list_and_run(client, ctx, adapter):
    ctx.routines = RoutineBook([Routine("work mode", "Open work apps", [{"do": "open vs code"}, {"tool": "set_volume", "args": {"percent": 30}}],
                                        ["start work"], None, ""),
                                Routine("morning briefing", "", [{"do": "daily briefing"}], [], Schedule.parse("weekdays 09:00"), "weekdays 09:00")])
    rs = {r["name"]: r for r in client.get("/api/routines").json()["routines"]}
    assert rs["work mode"]["steps"] == ["open vs code", "set_volume"] and rs["work mode"]["schedule"] is None and rs["work mode"]["next_run"] is None
    assert rs["morning briefing"]["next_run"] == "2026-10-16T09:00" and rs["morning briefing"]["ran_today"] is False
    out = client.post("/api/routines/work mode/run").json()
    assert [r["status"] for r in out["results"]] == ["ok", "ok"] and adapter.volume == 30
    assert all(r["origin"] == "user" for r in out["results"])


def test_routine_run_still_asks_for_risky_steps(client, ctx, adapter):
    ctx.routines = RoutineBook([Routine("end", steps=[{"do": "shut down"}])])
    out = client.post("/api/routines/end/run").json()
    assert out["results"][0]["status"] == "pending" and out["state"]["pending"]
    assert not any(c[0] == "shutdown" for c in adapter.calls)


def test_routine_run_unknown_is_404(client):
    assert client.post("/api/routines/nope/run").status_code == 404


def test_routines_report_ran_today(client, ctx):
    ctx.routines = RoutineBook([Routine("a", steps=[{"do": "daily briefing"}], schedule=Schedule.parse("daily 08:00"), schedule_text="daily 08:00")])
    ctx.memory.mark_routine_ran("a", "2026-10-15")
    assert client.get("/api/routines").json()["routines"][0]["ran_today"] is True


# ---------------------------------------------------------------- modules, files, safety
def test_modules_are_real_tool_groups_not_invented_agents(client, ctx):
    m = client.get("/api/modules").json()
    ids = [x["id"] for x in m["modules"]]
    assert ids[:4] == ["gate", "scheduler", "llm", "voice"]
    skills = {x["name"].lower(): x for x in m["modules"] if x["kind"] == "skill"}
    assert sum(x["tools"] for x in skills.values()) == m["tools_total"] == len(ctx.registry.all())
    assert skills["system"]["ask_first"] >= 1 and all(x["status"] == "active" for x in skills.values())
    by = {x["id"]: x for x in m["modules"]}
    assert by["llm"]["status"] == "standby" and by["voice"]["status"] == "standby" and by["scheduler"]["status"] == "standby"


def test_modules_scheduler_and_pause_states(client, ctx):
    class FakeSched:
        running = True
    ctx.scheduler = FakeSched()
    client.post("/api/kill")
    by = {x["id"]: x for x in client.get("/api/modules").json()["modules"]}
    assert by["scheduler"]["status"] == "active" and by["gate"]["status"] == "paused"
    FakeSched.running = False
    client.post("/api/resume")
    assert {x["id"]: x for x in client.get("/api/modules").json()["modules"]}["scheduler"]["status"] == "error"


def test_recent_files_only_from_allowed_folders_newest_first(client, home):
    import os, time
    a = home / "Documents" / "old.txt"
    b = home / "Downloads" / "new.pdf"
    a.write_text("a"); b.write_text("bb")
    os.utime(a, (time.time() - 5000, time.time() - 5000))
    outside = home / "secret.txt"
    outside.write_text("nope")
    (home / "Documents" / ".hidden").write_text("x")
    out = client.get("/api/files/recent").json()
    assert [f["name"] for f in out["files"]] == ["new.pdf", "old.txt"]
    assert out["files"][0]["folder"] == "Downloads" and out["files"][0]["ext"] == "pdf" and out["files"][0]["size"] == 2
    assert {f["name"] for f in out["folders"]} == {"Downloads", "Documents", "Desktop", "Pictures"}
    assert "secret.txt" not in str(out)


def test_recent_files_depth_limit_and_empty_state(client, home):
    assert client.get("/api/files/recent").json()["files"] == []
    deep = home / "Documents" / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "too-deep.txt").write_text("x")
    (home / "Documents" / "a" / "ok.txt").write_text("x")
    assert [f["name"] for f in client.get("/api/files/recent").json()["files"]] == ["ok.txt"]


def test_open_file_goes_through_the_sandbox_and_gate(client, home, adapter):
    f = home / "Documents" / "plan.txt"
    f.write_text("x")
    assert client.post("/api/files/open", json={"text": str(f)}).json()["result"]["status"] == "ok"
    assert str(f) in adapter.opened_paths
    r = client.post("/api/files/open", json={"text": str(home.parent / "outside.txt")}).json()
    assert r["result"]["status"] in ("blocked", "error") and str(home.parent / "outside.txt") not in adapter.opened_paths
    setup = home / "Downloads" / "setup.exe"
    setup.write_text("MZ")
    assert client.post("/api/files/open", json={"text": str(setup)}).json()["result"]["status"] == "pending"


def test_safety_panel_reflects_kill_dry_run_and_audit(client, ctx):
    s = client.get("/api/safety").json()
    assert s["killed"] is False and s["dry_run"] is False and s["audit"]["ok"] is True
    assert s["kill_hotkey"] == "ctrl+alt+shift+k" and s["confirm_timeout_s"] == 120 and len(s["allowed_folders"]) == 4
    assert s["tools"]["always_ask"] >= 3
    client.post("/api/dryrun", json={"enabled": True})
    client.post("/api/kill")
    s = client.get("/api/safety").json()
    assert s["killed"] is True and s["dry_run"] is True


def test_safety_panel_detects_a_tampered_audit_log(client, ctx):
    client.post("/api/actions/volume", json={"value": 1})
    client.post("/api/actions/volume", json={"value": 2})
    text = ctx.audit.path.read_text().replace('"percent": 1', '"percent": 9')
    ctx.audit.path.write_text(text)
    s = client.get("/api/safety").json()
    assert s["audit"]["ok"] is False and s["audit"]["first_bad_line"] >= 1
    assert client.get("/api/activity").json()["chain_ok"] is False


def test_safety_lists_pending_approvals(client):
    client.post("/api/actions/shutdown")
    assert client.get("/api/safety").json()["pending"][0]["tool"] == "shutdown_pc"


def test_scheduler_exposes_running_flag(ctx):
    from delta.scheduler import Scheduler
    s = Scheduler(ctx, interval=0.05)
    assert s.running is False
    s.start()
    assert s.running is True
    s.stop()


# ---------------------------------------------------------------- the front-end files themselves
def test_static_files_have_no_external_requests():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "delta" / "ui" / "static"
    for f in ("index.html", "dashboard.css", "dashboard.js"):
        text = (root / f).read_text(encoding="utf-8")
        urls = re.findall(r"https?://[^\s\"'`)<>]+", text)
        assert all(u.startswith("http://www.w3.org/") for u in urls), (f, urls)    # only SVG namespace strings
        assert "@import" not in text and "//cdn" not in text and "fonts.googleapis" not in text
    assert (root / "fonts" / "Geist.woff2").stat().st_size > 10_000 and (root / "fonts" / "GeistMono.woff2").stat().st_size > 10_000
    assert (root / "fonts" / "LICENSE-Geist.txt").exists()


def test_page_uses_textcontent_only_for_data():
    """innerHTML is only allowed with constant strings (icons, tick marks); nothing built from API data."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "delta" / "ui" / "static" / "dashboard.js").read_text(encoding="utf-8")
    uses = [ln.strip() for ln in js.splitlines() if "innerHTML" in ln]
    assert len(uses) == 2 and all(("ICONS[name]" in u) or ("svg.innerHTML = out" in u) for u in uses), uses
    assert "document.write" not in js and "eval(" not in js and "insertAdjacentHTML" not in js


def test_page_has_the_required_accessible_landmarks(client):
    html = client.get("/").text
    for needle in ('lang="en"', 'aria-label="Quick actions"', 'role="combobox"', 'aria-live', 'id="pal"', 'aria-label="Kill switch"', "viewport"):
        assert needle in html, needle
    css = client.get("/assets/dashboard.css").text
    assert "prefers-reduced-motion" in css and ":focus-visible" in css and "@media (max-width:760px)" in css
