import time

import pytest


def test_safe_command_runs_immediately(eng, adapter):
    r = eng.handle_message("volume 40")
    assert r.results[0].status == "ok" and adapter.volume == 40 and r.source == "rules"


def test_volume_is_clamped_and_unmutes(eng, adapter):
    adapter.muted = True
    eng.handle_message("volume up by 90")
    assert adapter.volume == 100 and adapter.muted is False
    eng.execute("change_volume", {"delta": -100})
    assert adapter.volume == 0


def test_confirm_flow_by_typing_yes(eng, adapter):
    r = eng.handle_message("shut down")
    assert r.results[0].status == "pending" and r.pending
    assert not [c for c in adapter.calls if c[0] == "shutdown"]
    r2 = eng.handle_message("yes")
    assert r2.results[0].status == "ok" and ("shutdown", 30) in adapter.calls


def test_confirm_flow_deny(eng, adapter):
    eng.handle_message("restart")
    r = eng.handle_message("no")
    assert not eng.pending and not [c for c in adapter.calls if c[0] == "restart"]
    assert "cancel" in r.text.lower()


def test_yes_without_pending_does_nothing(eng, adapter):
    r = eng.handle_message("yes")
    assert not r.results and not adapter.calls


def test_pending_expires(make_ctx):
    c = make_ctx(safety={"confirm_timeout_s": 0})
    r = c.engine.handle_message("restart")
    time.sleep(0.02)
    res = c.engine.resolve(r.results[0].pending_id, True)
    assert res.status == "expired" and not [x for x in c.adapter.calls if x[0] == "restart"]
    assert any(e["event"] == "confirm_expired" for e in c.audit.tail(10))


def test_multiple_pending_need_explicit_id(eng, adapter):
    a = eng.execute("restart_pc").pending_id
    b = eng.execute("shutdown_pc").pending_id
    r = eng.handle_message("yes")
    assert "several" in r.text and not [c for c in adapter.calls if c[0] in ("restart", "shutdown")]
    eng.handle_message(f"no {a}")
    eng.handle_message(f"yes {b}")
    assert [c[0] for c in adapter.calls if c[0] in ("restart", "shutdown")] == ["shutdown"]


def test_confirmation_cannot_be_replayed(eng, adapter):
    pid = eng.execute("shutdown_pc").pending_id
    assert eng.resolve(pid, True).status == "ok"
    assert eng.resolve(pid, True).status == "expired"
    assert len([c for c in adapter.calls if c[0] == "shutdown"]) == 1


def test_kill_switch_blocks_everything_and_clears_pending(eng, adapter):
    eng.execute("shutdown_pc")
    eng.kill("test")
    assert not eng.pending
    for text in ("volume 10", "open chrome", "yes"):
        r = eng.handle_message(text)
        assert "paused" in r.text.lower()
    assert eng.execute("set_volume", {"percent": 5}).status == "killed"
    assert adapter.volume == 35
    eng.handle_message("resume")
    assert eng.handle_message("volume 10").results[0].status == "ok" and adapter.volume == 10


def test_kill_by_typing(eng, ctx):
    eng.handle_message("kill switch")
    assert ctx.killed.is_set()


def test_approval_after_kill_does_not_run(eng, adapter):
    pid = eng.execute("shutdown_pc").pending_id
    eng.ctx.killed.set()                      # kill switch flips while the card is still on screen
    assert eng.resolve(pid, True).status == "killed"
    assert not [c for c in adapter.calls if c[0] == "shutdown"]


def test_dry_run_changes_nothing_but_reads_still_work(make_ctx):
    c = make_ctx(safety={"dry_run": True})
    r = c.engine.handle_message("volume 90")
    assert r.results[0].status == "dry_run" and c.adapter.volume == 35
    assert c.engine.handle_message("what's my battery").results[0].status == "ok"   # read-only
    pid = c.engine.execute("shutdown_pc").pending_id
    assert c.engine.resolve(pid, True).status == "dry_run"                           # even an approved action is only simulated
    assert not [x for x in c.adapter.calls if x[0] in ("set_volume", "shutdown")]
    assert any(e.get("dry_run") for e in c.audit.tail(10))


def test_dry_run_can_be_toggled_at_runtime(ctx, adapter):
    ctx.dry_run = True
    assert ctx.engine.handle_message("mute").results[0].status == "dry_run"
    ctx.dry_run = False
    assert ctx.engine.handle_message("mute").results[0].status == "ok" and adapter.muted


def test_bad_arguments_and_unknown_tools(eng):
    assert eng.execute("set_volume", {"percent": "loud"}).status == "error"
    assert eng.execute("set_volume", {}).status == "error"
    assert eng.execute("set_volume", {"percent": 5, "evil": 1}).status == "error"
    assert eng.execute("set_volume", {"percent": 500}).status == "error"
    assert eng.execute("format_c_drive", {}).status == "error"


def test_numeric_strings_are_coerced(eng, adapter):
    assert eng.execute("set_volume", {"percent": "55"}).status == "ok" and adapter.volume == 55


def test_handler_exception_becomes_error_not_crash(eng, adapter):
    def boom(*a, **k):
        raise RuntimeError("driver exploded")
    adapter.set_volume = boom
    r = eng.handle_message("volume 20")
    assert r.results[0].status == "error" and "driver exploded" in r.text


def test_multiple_intents_in_one_message(eng, adapter):
    r = eng.handle_message("open chrome and spotify")
    assert [x.status for x in r.results] == ["ok", "ok"]
    assert [c[1] for c in adapter.calls if c[0] == "open_app"] == ["chrome", "spotify:"]


def test_unknown_program_needs_approval(eng, adapter):
    r = eng.handle_message("open totally-unknown-tool")
    assert r.results[0].status == "pending" and not adapter.calls
    eng.handle_message("yes")
    assert adapter.calls[0][0] == "open_app"


def test_unrecognised_text_without_llm_gives_help(eng):
    r = eng.handle_message("tell me a story about dragons")
    assert not r.results and "help" in r.text.lower() and r.source == "system"


def test_history_is_persisted(eng, ctx):
    eng.handle_message("volume 20", session="web")
    msgs = ctx.memory.all_messages("web")
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_tools_cli_listing_covers_levels(ctx):
    names = {t.name for t in ctx.registry.all()}
    assert {"shutdown_pc", "restart_pc", "delete_path", "kill_process", "run_command"} <= names
    assert len(names) >= 50
