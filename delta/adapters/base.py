"""The OS abstraction layer. Skills never import pywin32/pycaw/pyautogui; they call an Adapter."""
from __future__ import annotations

import abc
import subprocess
from pathlib import Path
from typing import Any


class AdapterError(RuntimeError):
    """A platform call failed or is unavailable (message is shown to the user)."""


class Adapter(abc.ABC):
    name = "base"
    is_real = False   # True only for an adapter that really drives an OS

    # ----- apps & windows
    @abc.abstractmethod
    def open_app(self, target: str) -> str: ...
    @abc.abstractmethod
    def close_app(self, process_name: str) -> int: ...
    @abc.abstractmethod
    def list_windows(self) -> list[dict]: ...
    @abc.abstractmethod
    def focus_window(self, title_part: str) -> str | None: ...
    @abc.abstractmethod
    def window_action(self, title_part: str, action: str) -> str | None: ...

    # ----- sound / display / power
    @abc.abstractmethod
    def get_volume(self) -> int: ...
    @abc.abstractmethod
    def set_volume(self, percent: int) -> None: ...
    @abc.abstractmethod
    def get_muted(self) -> bool: ...
    @abc.abstractmethod
    def set_muted(self, muted: bool) -> None: ...
    @abc.abstractmethod
    def get_brightness(self) -> int | None: ...
    @abc.abstractmethod
    def set_brightness(self, percent: int) -> None: ...
    @abc.abstractmethod
    def lock(self) -> None: ...
    @abc.abstractmethod
    def sleep(self) -> None: ...
    @abc.abstractmethod
    def shutdown(self, delay_s: int = 30) -> None: ...
    @abc.abstractmethod
    def restart(self, delay_s: int = 30) -> None: ...
    @abc.abstractmethod
    def cancel_shutdown(self) -> None: ...

    # ----- clipboard / screen / media / notifications
    @abc.abstractmethod
    def clipboard_get(self) -> str: ...
    @abc.abstractmethod
    def clipboard_set(self, text: str) -> None: ...
    @abc.abstractmethod
    def screenshot(self, path: Path) -> Path: ...
    @abc.abstractmethod
    def ocr_image(self, path: Path) -> str: ...
    @abc.abstractmethod
    def media_key(self, action: str) -> None: ...
    @abc.abstractmethod
    def notify(self, title: str, message: str) -> None: ...

    # ----- files / urls / processes
    @abc.abstractmethod
    def open_path(self, path: Path) -> None: ...
    @abc.abstractmethod
    def open_url(self, url: str) -> None: ...
    @abc.abstractmethod
    def trash(self, path: Path) -> None: ...
    @abc.abstractmethod
    def run_process(self, argv: list[str], timeout: int = 30, cwd: str | None = None) -> tuple[int, str, str]: ...

    # ----- system info (psutil-backed by default; the mock overrides)
    def cpu_percent(self) -> float:
        import psutil
        return psutil.cpu_percent(interval=0.3)

    def memory(self) -> dict:
        import psutil
        m = psutil.virtual_memory()
        return {"total": m.total, "used": m.used, "percent": m.percent}

    def disks(self) -> list[dict]:
        import psutil
        out = []
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
            except OSError:
                continue
            out.append({"mount": p.mountpoint, "total": u.total, "used": u.used, "percent": u.percent})
        return out

    def battery(self) -> dict | None:
        import psutil
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if not b:
            return None
        return {"percent": round(b.percent), "plugged": bool(b.power_plugged), "secs_left": b.secsleft}

    def network(self) -> dict:
        import psutil
        ips = []
        for ifname, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family.name == "AF_INET" and not a.address.startswith("127."):
                    ips.append({"interface": ifname, "ip": a.address})
        io = psutil.net_io_counters()
        return {"addresses": ips, "bytes_sent": io.bytes_sent, "bytes_recv": io.bytes_recv}

    def processes(self, limit: int = 8, sort: str = "memory") -> list[dict]:
        import psutil
        rows = []
        for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
            i = p.info
            rows.append({"pid": i["pid"], "name": i["name"] or "?", "memory": round(i["memory_percent"] or 0, 1),
                         "cpu": round(i["cpu_percent"] or 0, 1)})
        rows.sort(key=lambda r: r["cpu" if sort == "cpu" else "memory"], reverse=True)
        return rows[:limit]

    def find_pids(self, name: str) -> list[dict]:
        import psutil
        n = name.lower()
        n2 = n if n.endswith(".exe") else n + ".exe"
        out = []
        for p in psutil.process_iter(["pid", "name"]):
            pn = (p.info["name"] or "").lower()
            if pn in (n, n2):
                out.append({"pid": p.info["pid"], "name": p.info["name"]})
        return out

    def process_name(self, pid: int) -> str | None:
        import psutil
        try:
            return psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def kill_pid(self, pid: int) -> str:
        import psutil
        try:
            p = psutil.Process(pid)
            nm = p.name()
            p.terminate()
            try:
                p.wait(3)
            except psutil.TimeoutExpired:
                p.kill()
            return nm
        except psutil.NoSuchProcess:
            raise AdapterError(f"no process with id {pid}")
        except psutil.AccessDenied:
            raise AdapterError(f"access denied for process {pid}")

    # ----- shared helpers
    @staticmethod
    def _run(argv: list[str], timeout: int = 30, cwd: str | None = None, input_text: str | None = None,
             env: dict | None = None) -> tuple[int, str, str]:
        try:
            cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, input=input_text,
                                env=env, shell=False, errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError:
            raise AdapterError(f"command not found: {argv[0]}")
        except subprocess.TimeoutExpired:
            raise AdapterError(f"command timed out after {timeout}s")
        return cp.returncode, cp.stdout, cp.stderr

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "real": self.is_real}


# Friendly names -> what to launch. Values: executable, App Paths name, or URI scheme. Users extend via config `apps:`.
DEFAULT_APPS: dict[str, str] = {
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "microsoft edge": "msedge", "firefox": "firefox",
    "vs code": "code", "vscode": "code", "visual studio code": "code", "code": "code",
    "spotify": "spotify:", "notepad": "notepad", "calculator": "calc", "calc": "calc", "paint": "mspaint",
    "explorer": "explorer", "file explorer": "explorer", "files": "explorer", "terminal": "wt",
    "windows terminal": "wt", "cmd": "cmd", "command prompt": "cmd", "powershell": "powershell",
    "task manager": "taskmgr", "settings": "ms-settings:", "word": "winword", "excel": "excel",
    "powerpoint": "powerpnt", "outlook": "outlook", "teams": "msteams:", "discord": "discord", "slack": "slack",
    "whatsapp": "whatsapp:", "vlc": "vlc", "snipping tool": "snippingtool", "camera": "microsoft.windows.camera:",
}
# process names used to close an app politely
APP_PROCESSES: dict[str, str] = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe", "edge": "msedge.exe", "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe", "vs code": "Code.exe", "vscode": "Code.exe", "visual studio code": "Code.exe",
    "code": "Code.exe", "spotify": "Spotify.exe", "notepad": "notepad.exe", "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe", "paint": "mspaint.exe", "word": "WINWORD.EXE", "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE", "outlook": "OUTLOOK.EXE", "teams": "ms-teams.exe", "discord": "Discord.exe",
    "slack": "slack.exe", "vlc": "vlc.exe", "task manager": "Taskmgr.exe", "whatsapp": "WhatsApp.exe",
}
