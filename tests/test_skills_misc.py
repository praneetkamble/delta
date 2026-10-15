import pytest

from delta.skills import plugins


def test_mute_toggle_and_explicit(eng, adapter):
    eng.handle_message("mute")
    assert adapter.muted
    eng.execute("set_mute", {"state": "toggle"})
    assert not adapter.muted
    eng.handle_message("unmute")
    assert not adapter.muted


def test_brightness_set_and_unreadable_display(eng, adapter):
    eng.handle_message("brightness 20")
    assert adapter.brightness == 20
    adapter.brightness = None
    r = eng.execute("change_brightness", {"delta": 10})
    assert r.status == "error" and "desktop" in r.text.lower()


def test_lock_and_sleep_are_safe_but_power_off_is_not(eng, adapter):
    assert eng.handle_message("lock my pc").results[0].status == "ok"
    assert eng.handle_message("sleep").results[0].status == "ok"
    assert eng.handle_message("cancel shutdown").results[0].status == "ok"
    assert {c[0] for c in adapter.calls} >= {"lock", "sleep", "cancel_shutdown"}


def test_media_keys(eng, adapter):
    for phrase in ("play", "next song", "previous track"):
        eng.handle_message(phrase)
    assert [c[1] for c in adapter.calls if c[0] == "media_key"] == ["play_pause", "next", "previous"]


@pytest.mark.parametrize("phrase,needle", [("cpu", "CPU"), ("memory", "Memory"), ("disk", "Disk C:"), ("battery", "Battery"), ("network", "192.168.1.23"), ("system status", "Battery")])
def test_system_info_sections(eng, phrase, needle):
    r = eng.handle_message(phrase)
    assert r.results[0].status == "ok" and needle in r.text


def test_top_processes(eng):
    r = eng.handle_message("top processes")
    assert "chrome.exe" in r.text.splitlines()[1]
    assert "Code.exe" not in eng.execute("top_processes", {"limit": 1}).text


def test_kill_process_asks_then_kills(eng, adapter):
    r = eng.handle_message("kill chrome")
    assert r.results[0].status == "pending" and "chrome" in r.text and not adapter.killed
    eng.handle_message("yes")
    assert adapter.killed == [4120]
    assert eng.execute("kill_process", {"target": "no-such-app"}).status == "pending"
    assert eng.handle_message("yes").results[0].status == "error"


def test_close_app_asks_first(eng, adapter):
    adapter.running["Spotify.exe"] = 1
    assert eng.handle_message("close spotify").results[0].status == "pending"
    eng.handle_message("yes")
    assert ("close_app", "Spotify.exe") in adapter.calls and "Spotify.exe" not in adapter.running


def test_focus_and_window_actions(eng, adapter):
    assert eng.handle_message("switch to visual studio").results[0].status == "ok"
    assert eng.handle_message("switch to nothing here").results[0].status == "error"
    assert eng.handle_message("snap left").results[0].status == "ok"
    assert ("window_action", "active", "snap_left") in adapter.calls
    r = eng.execute("window_action", {"action": "close", "title": "chrome"})
    assert r.status == "pending"


def test_clipboard_roundtrip(eng, adapter):
    eng.handle_message("copy hello world to clipboard")
    assert adapter.clipboard == "hello world"
    assert "hello world" in eng.handle_message("what's on my clipboard").text


def test_clipboard_text_is_not_written_to_the_audit_log(eng, ctx):
    eng.execute("clipboard_write", {"text": "my secret meeting notes"}, origin="llm")
    raw = (ctx.config.data_dir / "audit.jsonl").read_text()
    assert "secret meeting notes" not in raw and "chars>" in raw


def test_screenshot_saved_inside_pictures(eng, home, adapter):
    r = eng.handle_message("take a screenshot")
    path = r.results[0].data["path"]
    assert path.startswith(str((home / "Pictures").resolve())) and adapter.calls[0][0] == "screenshot"


def test_ocr_reads_text(eng):
    r = eng.handle_message("read my screen")
    assert "Sample OCR text" in r.text and r.results[0].untrusted


def test_notes_and_todos_flow(eng):
    eng.handle_message("note: call the electrician")
    assert "electrician" in eng.handle_message("show notes").text
    eng.handle_message("add todo book flights")
    eng.handle_message("add todo renew passport")
    assert "book flights" in eng.handle_message("todo list").text
    eng.handle_message("done 1")
    assert "book flights" not in eng.handle_message("todo list").text
    assert eng.handle_message("done 99").results[0].status == "error"


def test_facts_flow(eng, ctx):
    eng.handle_message("remember that I prefer dark mode")
    assert "dark mode" in eng.handle_message("what do you know about me").text
    eng.handle_message("forget 1")
    assert ctx.memory.facts() == []


def test_briefing_contents(eng):
    eng.handle_message("add todo ship the portfolio")
    eng.handle_message("remind me to hydrate in 30 minutes")
    text = eng.handle_message("good morning").text
    assert "Thursday, 15 October 2026" in text and "ship the portfolio" in text and "hydrate" in text and "Battery 78%" in text
    assert "not connected" in text  # honest about missing plugins


def test_current_time(eng):
    assert "10:00 AM" in eng.handle_message("what time is it").text


def test_web_search_builds_encoded_url(eng, adapter):
    eng.handle_message("search for best café near me & open now")
    url = adapter.opened_urls[-1]
    assert url.startswith("https://www.google.com/search?q=") and "&open" not in url.split("q=")[1]
    eng.handle_message("search lo-fi beats on youtube")
    assert adapter.opened_urls[-1].startswith("https://www.youtube.com/results?search_query=")


def test_run_command_whitelist_confirm_and_args(eng, adapter):
    r = eng.handle_message("run command: ipconfig /all")
    assert r.results[0].status == "ok" and adapter.calls[-1] == ("run_process", ["ipconfig", "/all"])
    r = eng.handle_message("run command: notepad C:\\x.txt")
    assert r.results[0].status == "pending" and "exact command" in r.text
    n = len(adapter.calls)
    eng.handle_message("yes")
    assert len(adapter.calls) == n + 1
    assert eng.handle_message("run command: del /s /q C:\\").results[0].status == "blocked"


def test_run_script_only_registered_names(make_ctx, tmp_path):
    script = tmp_path / "backup.bat"
    script.write_text("@echo off")
    c = make_ctx(scripts={"backup": str(script)})
    assert c.engine.handle_message("run script backup").results[0].status == "ok"
    assert c.adapter.calls[-1][0] == "run_process" and c.adapter.calls[-1][1][0] == "cmd"
    assert c.engine.handle_message("run script nuke").results[0].status == "error"


def test_custom_apps_from_config(make_ctx):
    c = make_ctx(apps={"obsidian": "C:/Apps/Obsidian.exe"})
    assert c.engine.handle_message("open obsidian").results[0].status == "ok"
    assert c.adapter.calls[-1] == ("open_app", "C:/Apps/Obsidian.exe")


def test_capabilities_listing(eng):
    t = eng.handle_message("help").text
    assert "shutdown_pc (asks first)" in t and "gmail" not in t


def test_plugin_stubs_are_honest_and_not_exposed(ctx):
    assert ctx.engine.execute("gmail_unread").status == "error"
    assert "not set up" in ctx.engine.execute("calendar_today").text
    assert not ctx.registry.get("gmail_unread").expose_to_llm
