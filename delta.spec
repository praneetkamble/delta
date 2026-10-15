# -*- mode: python ; coding: utf-8 -*-
# Build a Windows folder app:  .venv\Scripts\pip install pyinstaller  &&  .venv\Scripts\pyinstaller delta.spec
# Result: dist\Delta\Delta.exe  (copy config.example.yaml -> config.yaml next to it).
# NOTE: this spec was written on Linux and has NOT been built or run on Windows. Expect to adjust hidden imports.
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("delta") + [
    "win32timezone", "win32gui", "win32con", "win32process", "pythoncom", "pywintypes",
    "pycaw.pycaw", "comtypes", "comtypes.client",
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "pyttsx3.drivers", "pyttsx3.drivers.sapi5",
]

a = Analysis(
    ["delta_launcher.py"],
    pathex=["."],
    datas=[("delta/ui/static", "delta/ui/static"), ("config.example.yaml", "."), ("routines.example.yaml", ".")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest", "playwright"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Delta", console=True)   # console=True so you can see the secret link
coll = COLLECT(exe, a.binaries, a.datas, name="Delta")
