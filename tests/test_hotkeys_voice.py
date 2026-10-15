import sys

import pytest

from delta.hotkeys import HotkeyManager, MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey
from delta.voice import VoiceController, shorten_for_speech


@pytest.mark.parametrize("spec,expected", [
    ("ctrl+alt+shift+k", (MOD_CONTROL | MOD_ALT | MOD_SHIFT, ord("K"))),
    ("Ctrl+Alt+Space", (MOD_CONTROL | MOD_ALT, 0x20)),
    ("alt+f9", (MOD_ALT, 0x78)),
    ("control+1", (MOD_CONTROL, ord("1"))),
])
def test_parse_hotkey(spec, expected):
    assert parse_hotkey(spec) == expected


@pytest.mark.parametrize("bad", ["k", "ctrl", "ctrl+", "hyper+k", "ctrl+ñ", "ctrl+f99", "", "+k"])
def test_parse_hotkey_rejects(bad):
    with pytest.raises(ValueError):
        parse_hotkey(bad)


def test_hotkey_manager_is_inert_off_windows():
    hk = HotkeyManager()
    hk.add("ctrl+alt+k", lambda: None)
    if sys.platform != "win32":
        assert hk.start() is False


class FakeListener:
    def __init__(self, *heard):
        self.heard = list(heard)
        self.calls = 0

    def listen(self):
        self.calls += 1
        return self.heard.pop(0) if self.heard else ""


class FakeSpeaker:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


def test_voice_command_is_executed_and_spoken(eng, adapter):
    sp = FakeSpeaker()
    v = VoiceController(eng, FakeListener("volume 45"), sp)
    assert v.trigger() == "volume 45"
    assert adapter.volume == 45 and "45" in sp.said[0]
    assert any(e["type"] == "voice" for e in eng.ctx.events)


def test_voice_confirmation_round_trip(eng, adapter, home):
    f = home / "Documents" / "old.txt"
    f.write_text("x")
    sp = FakeSpeaker()
    v = VoiceController(eng, FakeListener("delete old.txt", "yes"), sp)
    v.trigger()
    assert not f.exists()
    assert any("confirm" in s.lower() for s in sp.said)


def test_voice_no_cancels(eng, home):
    f = home / "Documents" / "old.txt"
    f.write_text("x")
    VoiceController(eng, FakeListener("delete old.txt", "no"), FakeSpeaker()).trigger()
    assert f.exists() and not eng.pending


def test_voice_does_not_listen_when_killed(eng):
    eng.kill()
    lis = FakeListener("volume 10")
    assert VoiceController(eng, lis, FakeSpeaker()).trigger() is None and lis.calls == 0


def test_voice_silence_is_handled(eng):
    sp = FakeSpeaker()
    assert VoiceController(eng, FakeListener(""), sp).trigger() is None
    assert "didn't hear" in sp.said[0]


def test_voice_cannot_bare_yes_a_tainted_request(eng, adapter):
    r = eng.execute("shutdown_pc", {}, origin="llm", tainted=True)
    sp = FakeSpeaker()
    VoiceController(eng, FakeListener("yes"), sp).trigger()
    assert eng.pending and not [c for c in adapter.calls if c[0] == "shutdown"]


def test_shorten_for_speech():
    t = shorten_for_speech("Found 3 files ☐ see https://example.com/very/long/link • " + "word " * 100)
    assert "https" not in t and len(t) <= 285 and "☐" not in t
