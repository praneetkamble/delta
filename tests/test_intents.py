from datetime import datetime

import pytest

from delta.intents import clean, parse_commands
from delta.routines import Routine, RoutineBook

NOW = datetime(2026, 10, 15, 10, 0, 0)


def one(text, routines=None):
    out = parse_commands(text, routines, NOW)
    assert len(out) == 1, f"{text!r} -> {out}"
    return out[0].tool, out[0].args


@pytest.mark.parametrize("text,tool,args", [
    ("open chrome", "open_app", {"name": "chrome"}),
    ("Please open VS Code", "open_app", {"name": "VS Code"}),
    ("hey delta, could you launch spotify?", "open_app", {"name": "spotify"}),
    ("close spotify", "close_app", {"name": "spotify"}),
    ("switch to chrome", "focus_window", {"title": "chrome"}),
    ("volume 40", "set_volume", {"percent": 40}),
    ("set the volume to 75%", "set_volume", {"percent": 75}),
    ("volume up", "change_volume", {"delta": 10}),
    ("turn the volume down by 25", "change_volume", {"delta": -25}),
    ("louder", "change_volume", {"delta": 10}),
    ("max volume", "set_volume", {"percent": 100}),
    ("mute", "set_mute", {"state": "on"}),
    ("unmute", "set_mute", {"state": "off"}),
    ("brightness 30", "set_brightness", {"percent": 30}),
    ("brightness down", "change_brightness", {"delta": -10}),
    ("lock my pc", "lock_screen", {}),
    ("sleep", "sleep_pc", {}),
    ("shut down the computer", "shutdown_pc", {}),
    ("restart", "restart_pc", {}),
    ("cancel shutdown", "cancel_shutdown", {}),
    ("take a screenshot", "screenshot", {}),
    ("read my screen", "screen_ocr", {}),
    ("what's on my clipboard", "clipboard_read", {}),
    ("copy hello world to clipboard", "clipboard_write", {"text": "hello world"}),
    ("system status", "system_info", {"section": "all"}),
    ("what's my battery", "system_info", {"section": "battery"}),
    ("how much disk space is left", "system_info", {"section": "disk"}),
    ("top processes", "top_processes", {"sort_by": "memory"}),
    ("what's using my cpu", "top_processes", {"sort_by": "cpu"}),
    ("kill chrome", "kill_process", {"target": "chrome"}),
    ("minimize", "window_action", {"action": "minimize", "title": "active"}),
    ("maximise chrome", "window_action", {"action": "maximize", "title": "chrome"}),
    ("snap left", "window_action", {"action": "snap_left", "title": "active"}),
    ("organize downloads", "organize_downloads", {}),
    ("find duplicates in downloads", "find_duplicates", {"folder": "downloads"}),
    ("find file invoice in downloads", "search_files", {"query": "invoice", "folder": "downloads"}),
    ("create folder Taxes 2026", "create_folder", {"name": "Taxes 2026"}),
    ("move report.pdf to Documents", "move_path", {"source": "report.pdf", "destination": "Documents"}),
    ("delete old.pdf", "delete_path", {"path": "old.pdf"}),
    ("open downloads", "open_path", {"path": "downloads"}),
    ("open notes.txt", "open_path", {"path": "notes.txt"}),
    ("open youtube.com", "open_url", {"url": "youtube.com"}),
    ("search for best laptops under 50000", "web_search", {"query": "best laptops under 50000"}),
    ("search python tutorials on youtube", "web_search", {"query": "python tutorials", "engine": "youtube"}),
    ("summarise https://example.com/post", "summarize_url", {"url": "https://example.com/post"}),
    ("run command: ipconfig /all", "run_command", {"command": "ipconfig /all"}),
    ("run script backup", "run_script", {"name": "backup"}),
    ("play", "media_control", {"action": "play_pause"}),
    ("next song", "media_control", {"action": "next"}),
    ("note: buy filters for the desk lamp", "add_note", {"text": "buy filters for the desk lamp"}),
    ("add todo send invoice to Rahul", "add_todo", {"text": "send invoice to Rahul"}),
    ("todo list", "list_todos", {}),
    ("done 3", "complete_todo", {"id": 3}),
    ("remember that my gym day is Tuesday", "remember_fact", {"text": "my gym day is Tuesday"}),
    ("what do you know about me", "list_facts", {}),
    ("good morning", "daily_briefing", {}),
    ("what time is it", "current_time", {}),
    ("help", "list_capabilities", {}),
    ("list reminders", "list_reminders", {}),
    ("cancel reminder 4", "cancel_reminder", {"id": 4}),
])
def test_intent_mapping(text, tool, args):
    assert one(text) == (tool, args)


def test_open_multiple_apps():
    out = parse_commands("open chrome, vs code and spotify", None, NOW)
    assert [i.args["name"] for i in out] == ["chrome", "vs code", "spotify"]


def test_reminder_what_when_split():
    assert one("remind me to call mom in 10 minutes") == ("set_reminder", {"text": "call mom", "when": "in 10 minutes"})
    # a time word inside the text must not confuse the split
    assert one("remind me to meet at work in 10 min") == ("set_reminder", {"text": "meet at work", "when": "in 10 min"})
    assert one("remind me in 2 hours to drink water") == ("set_reminder", {"text": "drink water", "when": "in 2 hours"})
    assert one("remind me to submit the form tomorrow at 9am") == ("set_reminder", {"text": "submit the form", "when": "tomorrow at 9am"})


def test_reminder_without_time_is_not_guessed():
    assert parse_commands("remind me to call mom", None, NOW) == []


def test_timer_and_alarm():
    assert one("set a 5 minute timer") == ("set_timer", {"duration": "5 minute"})
    assert one("timer for 1 hour 30 minutes") == ("set_timer", {"duration": "1 hour 30 minutes"})
    assert one("set an alarm for 7:30 am") == ("set_alarm", {"time": "7:30 am"})
    assert one("wake me up at 6") == ("set_alarm", {"time": "6"})


def test_search_files_vs_web_search():
    assert one("find file budget")[0] == "search_files"
    assert one("search for budget templates")[0] == "web_search"


def test_unknown_text_is_not_guessed():
    for t in ["hello there", "tell me a joke", "asdf", "", "   "]:
        assert parse_commands(t, None, NOW) == []


def test_routine_triggers_beat_generic_verbs():
    book = RoutineBook([Routine("work mode", triggers=["start work"]), Routine("focus mode")])
    assert one("work mode", book) == ("run_routine", {"name": "work mode"})
    assert one("start work", book) == ("run_routine", {"name": "work mode"})
    assert one("run focus mode", book) == ("run_routine", {"name": "focus mode"})
    assert one("focus mode", book) == ("run_routine", {"name": "focus mode"})
    # without the routine, "focus X" is a window command
    assert one("focus chrome")[0] == "focus_window"


def test_clean_strips_politeness():
    assert clean("Hey Delta, could you please open notepad?") == "open notepad"
