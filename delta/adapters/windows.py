"""Real Windows implementation.

IMPORTANT: this file could NOT be executed in the environment where Delta was written (Linux). It follows
documented APIs (pywin32, pycaw, psutil, Pillow, ctypes, PowerShell) and every Windows-only import is lazy, so the module
imports anywhere. Treat it as "written carefully, needs a first run on a real PC": run `python -m delta doctor`
and then `python -m delta selftest` (see README) to check each capability on your machine.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from .base import Adapter, AdapterError, DEFAULT_APPS

# Anything that could be interpreted by cmd.exe as an operator is refused before we ever call `start`.
_SAFE_TARGET = re.compile(r"^[\w .\-:\\/()+@]+$")
_VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2, "mute": 0xAD, "volume_up": 0xAF, "volume_down": 0xAE}
_TOAST_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $tpl.GetElementsByTagName('text')
$nodes.Item(0).AppendChild($tpl.CreateTextNode($env:DELTA_TITLE)) | Out-Null
$nodes.Item(1).AppendChild($tpl.CreateTextNode($env:DELTA_MSG)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($tpl)
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""


def safe_launch_target(target: str) -> bool:
    """Pure helper (unit-tested on Linux): is this string safe to hand to `cmd /c start`?"""
    return bool(target) and bool(_SAFE_TARGET.fullmatch(target))


class WindowsAdapter(Adapter):
    name = "windows"
    is_real = True

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise AdapterError("WindowsAdapter can only be used on Windows (use adapter: mock elsewhere).")

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _win32():
        try:
            import win32con, win32gui, win32process  # type: ignore
            return win32con, win32gui, win32process
        except ImportError as e:
            raise AdapterError("pywin32 is not installed. Run: pip install pywin32") from e

    @staticmethod
    def _com_init() -> None:
        try:
            import comtypes  # type: ignore
            comtypes.CoInitialize()
        except Exception:
            pass

    def _ps(self, script: str, timeout: int = 20, env: dict | None = None) -> str:
        full_env = dict(os.environ)
        full_env.update(env or {})
        rc, out, err = self._run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                  "-Command", script], timeout, env=full_env)
        if rc != 0:
            raise AdapterError((err or out).strip()[:300] or "PowerShell command failed")
        return out.strip()

    # ---------------------------------------------------------------- apps & windows
    def open_app(self, target: str) -> str:
        t = target.strip()
        if not safe_launch_target(t):
            raise AdapterError("That app name contains characters I won't pass to the shell.")
        try:
            if t.endswith(":") or "://" in t or (os.path.isabs(t) and os.path.exists(t)):
                os.startfile(t)  # type: ignore[attr-defined]  # URI scheme (spotify:, ms-settings:) or a full path
            else:
                subprocess.Popen(["cmd", "/c", "start", "", t], shell=False,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise AdapterError(f"could not start {t}: {e}") from e
        return f"started {t}"

    def close_app(self, process_name: str) -> int:
        pids = self.find_pids(process_name)
        if not pids:
            return 0
        exe = pids[0]["name"]
        self._run(["taskkill", "/IM", exe], timeout=10)  # polite close request (no /F): apps can ask to save work
        time.sleep(1.5)
        return len(pids)

    def list_windows(self) -> list[dict]:
        con, gui, proc = self._win32()
        import psutil
        out: list[dict] = []

        def cb(hwnd, _):
            if not gui.IsWindowVisible(hwnd):
                return
            title = gui.GetWindowText(hwnd)
            if not title:
                return
            ex = gui.GetWindowLong(hwnd, con.GWL_EXSTYLE)
            if ex & con.WS_EX_TOOLWINDOW:
                return
            try:
                pid = proc.GetWindowThreadProcessId(hwnd)[1]
                pname = psutil.Process(pid).name()
            except Exception:
                pname = "?"
            out.append({"id": hwnd, "title": title, "process": pname})

        gui.EnumWindows(cb, None)
        return out

    def _find_hwnd(self, title_part: str):
        _, gui, _ = self._win32()
        if title_part.strip().lower() in ("", "active", "this", "current"):
            return gui.GetForegroundWindow()
        tp = title_part.lower()
        for w in self.list_windows():
            if tp in w["title"].lower() or tp in w["process"].lower():
                return w["id"]
        return None

    def _bring_front(self, hwnd) -> None:
        con, gui, _ = self._win32()
        if gui.IsIconic(hwnd):
            gui.ShowWindow(hwnd, con.SW_RESTORE)
        try:  # Windows blocks SetForegroundWindow unless the process "recently received input": tap ALT first.
            import ctypes
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
            gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def focus_window(self, title_part: str) -> str | None:
        _, gui, _ = self._win32()
        hwnd = self._find_hwnd(title_part)
        if not hwnd:
            return None
        self._bring_front(hwnd)
        return gui.GetWindowText(hwnd)

    def window_action(self, title_part: str, action: str) -> str | None:
        con, gui, _ = self._win32()
        hwnd = self._find_hwnd(title_part)
        if not hwnd:
            return None
        title = gui.GetWindowText(hwnd)
        if action == "minimize":
            gui.ShowWindow(hwnd, con.SW_MINIMIZE)
        elif action == "maximize":
            gui.ShowWindow(hwnd, con.SW_MAXIMIZE)
        elif action == "restore":
            gui.ShowWindow(hwnd, con.SW_RESTORE)
        elif action == "close":
            gui.PostMessage(hwnd, con.WM_CLOSE, 0, 0)  # asks the app to close; it may prompt to save
        elif action in ("snap_left", "snap_right"):
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
            w, h = rect.right - rect.left, rect.bottom - rect.top
            x = rect.left if action == "snap_left" else rect.left + w // 2
            gui.ShowWindow(hwnd, con.SW_RESTORE)
            gui.MoveWindow(hwnd, x, rect.top, w // 2, h, True)
        else:
            raise AdapterError(f"unknown window action {action}")
        return title

    # ---------------------------------------------------------------- sound
    def _endpoint(self):
        self._com_init()
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
            from comtypes import CLSCTX_ALL  # type: ignore
            from ctypes import POINTER, cast
        except ImportError as e:
            raise AdapterError("pycaw is not installed. Run: pip install pycaw comtypes") from e
        dev = AudioUtilities.GetSpeakers()
        ev = getattr(dev, "EndpointVolume", None)  # newer pycaw versions expose it directly
        if ev is not None:
            return ev
        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))

    def get_volume(self) -> int:
        return round(self._endpoint().GetMasterVolumeLevelScalar() * 100)

    def set_volume(self, percent: int) -> None:
        self._endpoint().SetMasterVolumeLevelScalar(max(0, min(100, int(percent))) / 100.0, None)

    def get_muted(self) -> bool:
        return bool(self._endpoint().GetMute())

    def set_muted(self, muted: bool) -> None:
        self._endpoint().SetMute(1 if muted else 0, None)

    # ---------------------------------------------------------------- display / power
    def get_brightness(self) -> int | None:
        try:
            import screen_brightness_control as sbc  # type: ignore
            v = sbc.get_brightness()
            return int(v[0] if isinstance(v, list) else v)
        except Exception:
            pass
        try:
            out = self._ps("(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness")
            return int(out.splitlines()[0])
        except Exception:
            return None

    def set_brightness(self, percent: int) -> None:
        p = max(0, min(100, int(percent)))
        try:
            import screen_brightness_control as sbc  # type: ignore
            sbc.set_brightness(p)
            return
        except ImportError:
            pass
        except Exception as e:
            raise AdapterError(f"brightness not supported on this display: {e}") from e
        try:
            self._ps(f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{p})")
        except AdapterError as e:
            raise AdapterError("This display does not support software brightness (desktop monitors usually don't). "
                               "Optional: pip install screen-brightness-control") from e

    def lock(self) -> None:
        import ctypes
        if not ctypes.windll.user32.LockWorkStation():
            raise AdapterError("LockWorkStation failed")

    def sleep(self) -> None:
        # Note: if hibernation is enabled Windows may hibernate instead; `powercfg /hibernate off` makes it a true sleep.
        self._run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], timeout=10)

    def shutdown(self, delay_s: int = 30) -> None:
        self._run(["shutdown", "/s", "/t", str(int(delay_s)), "/c", "Delta: shutting down. Say 'cancel shutdown' to abort."])

    def restart(self, delay_s: int = 30) -> None:
        self._run(["shutdown", "/r", "/t", str(int(delay_s)), "/c", "Delta: restarting. Say 'cancel shutdown' to abort."])

    def cancel_shutdown(self) -> None:
        self._run(["shutdown", "/a"])

    # ---------------------------------------------------------------- clipboard / screen / media / notify
    def clipboard_get(self) -> str:
        try:
            import pyperclip  # type: ignore
            return pyperclip.paste()
        except ImportError:
            return self._ps("Get-Clipboard -Raw")

    def clipboard_set(self, text: str) -> None:
        try:
            import pyperclip  # type: ignore
            pyperclip.copy(text)
        except ImportError:
            self._ps("Set-Clipboard -Value $env:DELTA_CLIP", env={"DELTA_CLIP": text})

    def screenshot(self, path: Path) -> Path:
        try:
            from PIL import ImageGrab  # type: ignore
        except ImportError as e:
            raise AdapterError("Pillow is not installed. Run: pip install Pillow") from e
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(all_screens=True).save(path)
        return path

    def ocr_image(self, path: Path) -> str:
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError as e:
            raise AdapterError("OCR needs `pip install pytesseract Pillow` and the Tesseract program "
                               "(https://github.com/UB-Mannheim/tesseract/wiki).") from e
        for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.exists(cand):
                pytesseract.pytesseract.tesseract_cmd = cand
                break
        try:
            return pytesseract.image_to_string(Image.open(path)).strip()
        except pytesseract.TesseractNotFoundError as e:
            raise AdapterError("Tesseract is not installed (https://github.com/UB-Mannheim/tesseract/wiki).") from e

    def media_key(self, action: str) -> None:
        import ctypes
        vk = _VK.get(action)
        if vk is None:
            raise AdapterError(f"unknown media action {action}")
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)

    def notify(self, title: str, message: str) -> None:
        self._ps(_TOAST_PS, timeout=15, env={"DELTA_TITLE": title[:100], "DELTA_MSG": message[:250]})

    # ---------------------------------------------------------------- files / urls / processes
    def open_path(self, path: Path) -> None:
        os.startfile(str(path))  # type: ignore[attr-defined]

    def open_url(self, url: str) -> None:
        if not webbrowser.open(url):
            raise AdapterError("could not open the default browser")

    def trash(self, path: Path) -> None:
        try:
            from send2trash import send2trash  # type: ignore
        except ImportError as e:
            raise AdapterError("send2trash is not installed. Run: pip install send2trash") from e
        send2trash(str(path))

    def run_process(self, argv: list[str], timeout: int = 30, cwd: str | None = None) -> tuple[int, str, str]:
        return self._run(argv, timeout, cwd)
