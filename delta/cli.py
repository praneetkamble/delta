"""Command line: serve (web UI + scheduler + hotkeys), chat, say, doctor, selftest, tools, audit."""
from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

from . import __version__
from .config import load_config
from .context import build_context

log = logging.getLogger("delta")


def _interactive_reply(engine, text: str, session: str = "cli") -> None:
    reply = engine.handle_message(text, session=session)
    print(reply.text)
    while engine.pending:
        p = list(engine.pending.values())[0]
        try:
            ans = input(f"  Approve? [{p.id}] {p.description}  (y/N) ").strip().lower()
        except EOFError:
            ans = "n"
        res = engine.resolve(p.id, ans in ("y", "yes"), via="cli")
        print(res.text)


def cmd_serve(args) -> int:
    import uvicorn
    from .hotkeys import HotkeyManager
    from .scheduler import Scheduler
    from .server import assert_loopback, create_app, new_token

    cfg = load_config(args.config, {"safety.dry_run": True} if args.dry_run else None)
    if sys.stdout is None or sys.stderr is None:  # started with pythonw.exe (start-on-login): there is no console
        logf = open(cfg.data_dir / "delta.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or logf
        sys.stderr = sys.stderr or logf
    host = "127.0.0.1"
    port = int(args.port or cfg.get("server.port", 8765))
    assert_loopback(host)
    ctx = build_context(cfg)
    engine = ctx.engine
    sched = Scheduler(ctx)
    ctx.scheduler = sched
    sched.start()

    hk = HotkeyManager()
    voice_trigger = None
    try:
        hk.add(str(cfg.get("safety.kill_switch_hotkey", "ctrl+alt+shift+k")), lambda: engine.kill("global hotkey"))
        if cfg.get("voice.enabled") or args.voice:
            from .voice import Listener, Speaker, VoiceController
            speaker = Speaker() if cfg.get("voice.speak_replies", True) else None
            vc = VoiceController(engine, Listener(cfg.get("voice.stt_backend", "auto"), cfg.get("voice.whisper_model", "base.en"),
                                                  int(cfg.get("voice.max_record_s", 15))), speaker)
            if speaker:
                ctx.speak = speaker.say
            voice_trigger = vc.trigger
            hk.add(str(cfg.get("voice.hotkey", "ctrl+alt+space")), vc.trigger)
    except ValueError as e:
        print(f"Hotkey configuration problem: {e}")
    if hk.start():
        print("Global hotkeys active: " + ", ".join(hk.registered))
    else:
        print("Global hotkeys are inactive (Windows only).")
    for w in ctx.routines.warnings:
        print("routines.yaml:", w)

    token = new_token()
    url = f"http://{host}:{port}/?token={token}"
    app = create_app(ctx, token, port, voice_trigger)
    print(f"\nDelta {__version__} ({ctx.adapter.name} adapter, dry-run {'ON' if ctx.dry_run else 'off'})")
    print(f"Open this link (it contains this session's secret token):\n  {url}\n")
    url_file = cfg.data_dir / "session_url.txt"
    try:
        url_file.write_text(url, encoding="utf-8")
    except OSError:
        pass
    if cfg.get("server.open_browser", True) and not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        sched.stop()
        hk.stop()
        try:
            url_file.unlink()
        except OSError:
            pass
    return 0


def cmd_open(args) -> int:
    cfg = load_config(args.config)
    f = cfg.data_dir / "session_url.txt"
    if not f.exists():
        print("Delta isn't running (no session link found). Start it with run.bat.")
        return 1
    webbrowser.open(f.read_text(encoding="utf-8").strip())
    return 0


def cmd_chat(args) -> int:
    cfg = load_config(args.config, {"safety.dry_run": True} if args.dry_run else None)
    ctx = build_context(cfg)
    from .scheduler import Scheduler
    Scheduler(ctx).start()
    print(f"Delta {__version__} · {ctx.adapter.name} adapter · type 'help', or 'exit' to quit")
    while True:
        try:
            line = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.lower() in ("exit", "quit", "q"):
            return 0
        if line:
            print("delta ›", end=" ")
            _interactive_reply(ctx.engine, line)


def cmd_say(args) -> int:
    cfg = load_config(args.config, {"safety.dry_run": True} if args.dry_run else None)
    ctx = build_context(cfg)
    _interactive_reply(ctx.engine, " ".join(args.text))
    return 0


def cmd_tools(args) -> int:
    ctx = build_context(load_config(args.config))
    for t in ctx.registry.all():
        flag = "ALWAYS-CONFIRM" if t.always_confirm else t.level.value
        extra = " [classified per call]" if t.classify else ""
        print(f"{t.category:10} {t.name:20} {flag:15}{extra}")
    return 0


def cmd_audit(args) -> int:
    ctx = build_context(load_config(args.config))
    ok, bad = ctx.audit.verify()
    print("Audit chain:", "intact" if ok else f"BROKEN at line {bad}")
    for r in ctx.audit.tail(args.tail):
        print(r.get("ts", "")[:19], r.get("event"), r.get("tool", ""), r.get("status", ""), str(r.get("result") or r.get("description") or r.get("text") or "")[:80])
    return 0 if ok else 2


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def cmd_doctor(args) -> int:
    cfg = load_config(args.config)
    print(f"Delta {__version__} doctor")
    print(f"  Python      {sys.version.split()[0]} ({'OK' if sys.version_info >= (3, 10) else 'NEEDS 3.10+'})")
    print(f"  Platform    {sys.platform}")
    ctx = build_context(cfg)
    print(f"  Adapter     {ctx.adapter.name}" + ("" if ctx.adapter.is_real else "  (mock: nothing real is controlled; expected on Linux/macOS)"))
    print(f"  Config      {cfg.path or 'built-in defaults (no config.yaml found)'}")
    print(f"  Data dir    {cfg.data_dir}")
    core = ["fastapi", "uvicorn", "httpx", "yaml", "psutil", "send2trash", "pydantic"]
    win = ["win32gui", "pycaw", "comtypes", "PIL", "pyperclip"] if sys.platform == "win32" else []
    opt = ["pytesseract", "faster_whisper", "sounddevice", "speech_recognition", "pyttsx3", "screen_brightness_control"]
    print("  Required    " + ", ".join(f"{m}:{'ok' if _have(m) else 'MISSING'}" for m in core + win))
    print("  Optional    " + ", ".join(f"{m}:{'ok' if _have(m) else '-'}" for m in opt))
    for p in ctx.config.allowed_folders:
        print(f"  Folder      {p}  {'(exists)' if p.exists() else '(does not exist; ignored)'}")
    llm = ctx.llm
    if llm and llm.available:
        try:
            llm.chat([{"role": "user", "content": "Reply with the single word: ok"}])
            print(f"  LLM         reachable ({llm.base_url}, model {llm.model})")
        except Exception as e:
            print(f"  LLM         NOT reachable: {e}")
    else:
        print("  LLM         not configured (rule-based commands only; see README)")
    for w in ctx.routines.warnings + ctx.routines.validate(ctx.registry):
        print("  Routines    ", w)
    return 0


def cmd_selftest(args) -> int:
    """Harmless read-mostly checks of each adapter capability. Run this once on the real PC and send me the output."""
    ctx = build_context(load_config(args.config))
    a = ctx.adapter
    print(f"Self-test on the '{a.name}' adapter" + ("" if a.is_real else " (mock)"))
    results: list[tuple[str, bool, str]] = []

    def check(name, fn):
        try:
            out = fn()
            results.append((name, True, str(out)[:70]))
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"[:90]))

    check("volume read", a.get_volume)
    check("mute read", a.get_muted)
    check("brightness read", a.get_brightness)
    check("windows list", lambda: f"{len(a.list_windows())} windows")
    check("battery", a.battery)
    check("cpu", a.cpu_percent)
    check("memory", lambda: a.memory()["percent"])
    check("disks", lambda: f"{len(a.disks())} drives")
    check("processes", lambda: f"{len(a.processes(3))} rows")

    def clip():
        old = a.clipboard_get()
        a.clipboard_set("delta-selftest")
        got = a.clipboard_get()
        a.clipboard_set(old)
        assert got == "delta-selftest", f"read back {got!r}"
        return "round-trip ok (original restored)"

    check("clipboard", clip)
    tmp = Path(tempfile.gettempdir()) / "delta-selftest.png"
    check("screenshot", lambda: f"{a.screenshot(tmp).stat().st_size} bytes")
    check("notification (watch for a toast)", lambda: a.notify("Delta self-test", "If you can see this, notifications work."))
    for n, ok_, msg in results:
        print(f"  [{'PASS' if ok_ else 'FAIL'}] {n:34} {msg}")
    print("Not tested here on purpose (they change state): set volume/brightness, lock, sleep, shutdown, close app, focus/snap windows, media keys, trash.")
    print("Try those by hand with dry-run OFF, e.g. 'volume 30', 'snap left', 'play'.")
    return 0 if all(ok_ for _, ok_, _ in results) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="delta", description="Delta: local personal assistant")
    ap.add_argument("--config", help="path to config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="describe actions without executing them")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the web UI (default)")
    s.add_argument("--port", type=int)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--voice", action="store_true", help="enable push-to-talk voice")
    sub.add_parser("open", help="open the running UI in the browser")
    sub.add_parser("chat", help="interactive terminal chat")
    sy = sub.add_parser("say", help="run one command")
    sy.add_argument("text", nargs="+")
    sub.add_parser("doctor", help="check the installation")
    sub.add_parser("selftest", help="check each platform capability")
    sub.add_parser("tools", help="list tools and permission levels")
    au = sub.add_parser("audit", help="show the audit log and verify its hash chain")
    au.add_argument("--tail", type=int, default=20)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    if args.cmd is None:
        args.cmd, args.port, args.no_browser, args.voice = "serve", None, False, False
    return {"serve": cmd_serve, "open": cmd_open, "chat": cmd_chat, "say": cmd_say, "doctor": cmd_doctor,
            "selftest": cmd_selftest, "tools": cmd_tools, "audit": cmd_audit}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
