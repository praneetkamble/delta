"""Global hotkeys (Windows, via RegisterHotKey: no extra dependency). On other systems start() returns False."""
from __future__ import annotations

import logging
import sys
import threading
from typing import Callable

log = logging.getLogger("delta")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN, "windows": MOD_WIN}
_SPECIAL = {"space": 0x20, "esc": 0x1B, "escape": 0x1B, "enter": 0x0D, "tab": 0x09, "pause": 0x13, "backspace": 0x08,
            "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+shift+k' -> (modifier flags, virtual-key code). Raises ValueError on nonsense."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError(f"hotkey {spec!r} needs at least one modifier and a key, e.g. ctrl+alt+k")
    *mods, key = parts
    flags = 0
    for m in mods:
        if m not in _MODS:
            raise ValueError(f"unknown modifier {m!r} in {spec!r}")
        flags |= _MODS[m]
    if not flags:
        raise ValueError("a modifier is required")
    if key in _SPECIAL:
        vk = _SPECIAL[key]
    elif len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"unknown key {key!r} in {spec!r}")
    return flags, vk


class HotkeyManager:
    def __init__(self) -> None:
        self._bindings: dict[int, tuple[int, int, Callable[[], None], str]] = {}
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()
        self.registered: list[str] = []
        self.failed: list[str] = []

    def add(self, spec: str, callback: Callable[[], None]) -> None:
        flags, vk = parse_hotkey(spec)
        self._bindings[len(self._bindings) + 1] = (flags, vk, callback, spec)

    def start(self) -> bool:
        if sys.platform != "win32" or not self._bindings:
            return False
        self._thread = threading.Thread(target=self._loop, name="delta-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(3)
        return bool(self.registered)

    def _loop(self) -> None:  # pragma: no cover - Windows only
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._tid = kernel32.GetCurrentThreadId()
        for hid, (flags, vk, _cb, spec) in self._bindings.items():
            if user32.RegisterHotKey(None, hid, flags | MOD_NOREPEAT, vk):
                self.registered.append(spec)
            else:
                self.failed.append(spec)
                log.warning("could not register hotkey %s (already used by another program?)", spec)
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312 and msg.wParam in self._bindings:  # WM_HOTKEY
                cb = self._bindings[msg.wParam][2]
                threading.Thread(target=self._safe, args=(cb,), daemon=True).start()
        for hid in self._bindings:
            user32.UnregisterHotKey(None, hid)

    @staticmethod
    def _safe(cb: Callable[[], None]) -> None:
        try:
            cb()
        except Exception:
            log.exception("hotkey handler failed")

    def stop(self) -> None:
        if sys.platform == "win32" and self._tid:  # pragma: no cover
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT
