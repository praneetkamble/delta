"""In-memory adapter used on Linux, in tests and in CI. Records every call so tests can assert on it."""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .base import Adapter, AdapterError, APP_PROCESSES


class MockAdapter(Adapter):
    name = "mock"
    is_real = False

    def __init__(self, trash_dir: Path | None = None, run_real_processes: bool = False, demo_motion: bool = False):
        # demo_motion: slowly varying simulated vitals so a demo dashboard is not a flat line (never used by the tests)
        self.demo_motion = demo_motion
        self._t0 = time.time()
        self.calls: list[tuple] = []
        self.volume = 35
        self.muted = False
        self.brightness: int | None = 70
        self.clipboard = ""
        self.running: dict[str, int] = {"explorer.exe": 1}
        self.windows = [
            {"id": 1, "title": "Delta", "process": "chrome.exe"},
            {"id": 2, "title": "main.py - delta - Visual Studio Code", "process": "Code.exe"},
            {"id": 3, "title": "Downloads", "process": "explorer.exe"},
        ]
        self.opened_paths: list[str] = []
        self.opened_urls: list[str] = []
        self.notifications: list[tuple[str, str]] = []
        self.trash_dir = Path(trash_dir) if trash_dir else Path.home() / ".delta" / "mock_trash"
        self.ocr_text = "Sample OCR text from the mock screen."
        self.run_real_processes = run_real_processes
        self.fake_procs = [
            {"pid": 4120, "name": "chrome.exe", "memory": 6.4, "cpu": 4.1},
            {"pid": 8812, "name": "Code.exe", "memory": 4.2, "cpu": 2.3},
            {"pid": 2210, "name": "Spotify.exe", "memory": 2.1, "cpu": 0.8},
            {"pid": 1337, "name": "python.exe", "memory": 1.4, "cpu": 0.4},
        ]
        self.killed: list[int] = []

    def _rec(self, *a):
        self.calls.append(a)

    # apps / windows
    def open_app(self, target):
        self._rec("open_app", target)
        key = target.lower()
        self.running[Path(target).name or target] = 1000 + len(self.running)
        return f"launched {target}"

    def close_app(self, process_name):
        self._rec("close_app", process_name)
        hits = [k for k in list(self.running) if k.lower() == process_name.lower()]
        for k in hits:
            self.running.pop(k)
        return len(hits)

    def list_windows(self):
        return list(self.windows)

    def focus_window(self, title_part):
        self._rec("focus_window", title_part)
        for w in self.windows:
            if title_part.lower() in w["title"].lower():
                return w["title"]
        return None

    def window_action(self, title_part, action):
        self._rec("window_action", title_part, action)
        if title_part in ("", "active"):
            return self.windows[0]["title"]
        return self.focus_window(title_part)

    # sound / display / power
    def get_volume(self):
        return self.volume

    def set_volume(self, percent):
        self._rec("set_volume", percent)
        self.volume = max(0, min(100, int(percent)))

    def get_muted(self):
        return self.muted

    def set_muted(self, muted):
        self._rec("set_muted", muted)
        self.muted = bool(muted)

    def get_brightness(self):
        return self.brightness

    def set_brightness(self, percent):
        self._rec("set_brightness", percent)
        self.brightness = max(0, min(100, int(percent)))

    def lock(self):
        self._rec("lock")

    def sleep(self):
        self._rec("sleep")

    def shutdown(self, delay_s=30):
        self._rec("shutdown", delay_s)

    def restart(self, delay_s=30):
        self._rec("restart", delay_s)

    def cancel_shutdown(self):
        self._rec("cancel_shutdown")

    # clipboard / screen / media / notify
    def clipboard_get(self):
        return self.clipboard

    def clipboard_set(self, text):
        self._rec("clipboard_set", len(text))
        self.clipboard = text

    def screenshot(self, path):
        self._rec("screenshot", str(path))
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # smallest valid PNG (1x1)
        path.write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6360000002000001e221bc330000000049454e44ae426082"))
        return path

    def ocr_image(self, path):
        self._rec("ocr_image", str(path))
        return self.ocr_text

    def media_key(self, action):
        self._rec("media_key", action)

    def notify(self, title, message):
        self.notifications.append((title, message))

    # files / urls / processes
    def open_path(self, path):
        self._rec("open_path", str(path))
        self.opened_paths.append(str(path))

    def open_url(self, url):
        self._rec("open_url", url)
        self.opened_urls.append(url)

    def trash(self, path):
        self._rec("trash", str(path))
        path = Path(path)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        dest = self.trash_dir / path.name
        i = 1
        while dest.exists():
            dest = self.trash_dir / f"{path.stem}.{i}{path.suffix}"
            i += 1
        shutil.move(str(path), str(dest))

    def run_process(self, argv, timeout=30, cwd=None):
        self._rec("run_process", list(argv))
        if not self.run_real_processes:
            return 0, f"[mock] would run: {' '.join(argv)}\n", ""
        return self._run(argv, timeout, cwd)

    # info (deterministic)
    def _wave(self, period: float, phase: float = 0.0) -> float:
        return math.sin((time.time() - self._t0) / period + phase)

    def cpu_percent(self):
        if not self.demo_motion:
            return 17.5
        return round(min(95.0, max(3.0, 24 + 13 * self._wave(6.0) + 6 * self._wave(1.7, 1.0) + 3 * self._wave(0.6, 2.0))), 1)

    def memory(self):
        if not self.demo_motion:
            return {"total": 16 * 2**30, "used": int(9.6 * 2**30), "percent": 60.0}
        pct = round(60 + 6 * self._wave(19.0) + 1.8 * self._wave(2.9, 1.0), 1)
        return {"total": 16 * 2**30, "used": int(16 * 2**30 * pct / 100), "percent": pct}

    def disks(self):
        return [{"mount": "C:\\", "total": 512 * 10**9, "used": 301 * 10**9, "percent": 58.8}]

    def battery(self):
        return {"percent": 78, "plugged": False, "secs_left": 14400}

    def network(self):
        if not self.demo_motion:
            return {"addresses": [{"interface": "Wi-Fi", "ip": "192.168.1.23"}], "bytes_sent": 48_000_000, "bytes_recv": 912_000_000}
        t = time.time() - self._t0   # cumulative counters; their slope (bytes/s) stays positive: ~0.4-2.4 MB/s down, ~80-280 kB/s up
        recv = 912_000_000 + int(1_400_000 * t - 3_000_000 * math.cos(t / 3.0) + 500_000 * math.cos(t / 1.3))
        sent = 48_000_000 + int(180_000 * t - 300_000 * math.cos(t / 3.0))
        return {"addresses": [{"interface": "Wi-Fi", "ip": "192.168.1.23"}], "bytes_sent": sent, "bytes_recv": recv}

    def processes(self, limit=8, sort="memory"):
        procs = self.fake_procs
        if self.demo_motion:
            procs = [dict(p, cpu=round(max(0.1, p["cpu"] * (1 + 0.4 * self._wave(3.0, p["pid"]))), 1)) for p in procs]
        rows = sorted(procs, key=lambda r: r["cpu" if sort == "cpu" else "memory"], reverse=True)
        return rows[:limit]

    def find_pids(self, name):
        n = name.lower()
        return [{"pid": p["pid"], "name": p["name"]} for p in self.fake_procs if p["name"].lower() in (n, n + ".exe")]

    def process_name(self, pid):
        return next((p["name"] for p in self.fake_procs if p["pid"] == pid), None)

    def kill_pid(self, pid):
        self._rec("kill_pid", pid)
        for p in self.fake_procs:
            if p["pid"] == pid:
                self.killed.append(pid)
                return p["name"]
        raise AdapterError(f"no process with id {pid}")

    def describe(self):
        return {"name": "mock", "real": False}
