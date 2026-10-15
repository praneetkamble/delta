"""Start Delta (mock adapter = demo mode), seed a little demo content through the real API, drive the dashboard with headless Chrome.

    python scripts/shoot_dashboard.py            # screenshots -> docs/
    python scripts/shoot_dashboard.py --video    # also records a ~30 s walkthrough -> /tmp/delta-video/*.webm

Needs `playwright` (pip install playwright) and a Chrome at /usr/bin/google-chrome. DELTA_PY = python that can run Delta.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PORT = 8798
SERVER_PY = os.environ.get("DELTA_PY", sys.executable)
CHROME = "/usr/bin/google-chrome"
VIDEO = "--video" in sys.argv


def start_server(tmp: Path):
    for n in ("Downloads", "Documents", "Desktop", "Pictures"):
        (tmp / n).mkdir(parents=True, exist_ok=True)
    now = time.time()
    for i, (folder, name, size, age) in enumerate([("Documents", "Q4-invoice-draft.pdf", 184_000, 900), ("Downloads", "design-system-notes.md", 6_400, 5400),
                                                    ("Documents", "portfolio-case-study.docx", 92_000, 14000), ("Pictures", "hero-render.png", 1_800_000, 30000),
                                                    ("Desktop", "delta_config.yaml", 1_200, 60000)]):
        f = tmp / folder / name
        f.write_bytes(b"x" * size)
        os.utime(f, (now - age, now - age))
    cfg = tmp / "config.yaml"
    cfg.write_text(f"""adapter: mock
user_name: Praneet
data_dir: {tmp / 'data'}
safety:
  allowed_folders: ['{tmp / "Downloads"}', '{tmp / "Documents"}', '{tmp / "Desktop"}', '{tmp / "Pictures"}']
routines_file: {ROOT / 'routines.example.yaml'}
""")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    srv = subprocess.Popen([SERVER_PY, "-m", "delta", "--config", str(cfg), "serve", "--port", str(PORT), "--no-browser"], cwd=ROOT, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url_file = tmp / "data" / "session_url.txt"
    for _ in range(80):
        if url_file.exists():
            break
        time.sleep(0.25)
    else:
        srv.kill()
        sys.exit("server did not start:\n" + srv.stdout.read())
    return srv, url_file.read_text().strip()


def seed(url: str):
    token = url.split("token=")[1]

    def call(path, body=None, method="POST"):
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"x-delta-token": token, "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req).read() or b"{}")

    for t in ["Review the Delta dashboard design", "Send invoice to Rahul", "Book dentist appointment"]:
        call("/api/todos", {"text": t})
    call("/api/reminders", {"text": "Stand-up call", "when": "in 3 hours"})
    call("/api/reminders", {"text": "Stretch and drink water", "when": "in 40 minutes"})
    call("/api/timers", {"duration": "25 minutes", "label": "Focus block"})
    call("/api/notes", {"text": "Ask the client for logo files before Friday"})
    call("/api/notes", {"text": "Idea: weekly review routine on Sunday evening"})
    for m in ["volume 40", "open vs code", "what's my battery", "run command: format c:"]:
        call("/api/chat", {"message": m})
    return call


def main():
    tmp = Path(tempfile.mkdtemp(prefix="demo-"))
    srv, url = start_server(tmp)
    errors = []
    try:
        call = seed(url)
        time.sleep(float(os.environ.get('WARMUP', '64')))   # let the 60 s vitals history fill
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"], headless=True)

            def page_for(w, h, scale=1):
                ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale)
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append(f"{w}: console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
                pg.on("response", lambda r: errors.append(f"{w}: HTTP {r.status} {r.url.split('?')[0]}") if r.status >= 400 else None)
                pg.on("pageerror", lambda e: errors.append(f"{w}: pageerror: {e}"))
                pg.goto(url)
                pg.wait_for_selector("#g-name:not(:empty)")
                time.sleep(2.5)
                return pg

            d = page_for(1440, 900)
            d.screenshot(path=str(DOCS / "dashboard-desktop.png"))
            # a pending approval from a quick action, shown over the core
            d.evaluate("fetch('/api/actions/shutdown',{method:'POST'})")
            d.wait_for_selector("#tray .card.pending", timeout=8000)
            time.sleep(0.8)
            d.screenshot(path=str(DOCS / "dashboard-approval.png"))
            d.click("#tray .btn.no")
            time.sleep(0.6)
            d.keyboard.press("Control+k")
            time.sleep(0.5)
            d.screenshot(path=str(DOCS / "dashboard-palette.png"))
            d.keyboard.press("Escape")
            for idx, name in ((2, "tasks"), (6, "activity"), (9, "controls")):
                d.click(f"#nav li:nth-child({idx}) button")
                time.sleep(1.2)
                d.screenshot(path=str(DOCS / f"dashboard-{name}.png"))
            d.click("#nav li:nth-child(1) button")
            d.fill("#inp", "restart")
            d.keyboard.press("Enter")
            d.wait_for_selector("#col .card.pending", timeout=8000)
            time.sleep(1.0)
            d.screenshot(path=str(DOCS / "dashboard-chat.png"))
            d.click("#dock .card.pending .btn.no")        # leave nothing pending for the next shots
            time.sleep(0.5)
            d.close()

            w = page_for(1440, 900, 2)          # sharper close-ups of single widgets
            w.locator(".monitor").screenshot(path=str(DOCS / "widget-monitor.png"))
            w.locator("#core").screenshot(path=str(DOCS / "widget-core.png"))
            w.locator(".zone-left").screenshot(path=str(DOCS / "widget-left.png"))
            w.locator(".zone-right .gatecard").screenshot(path=str(DOCS / "widget-safety.png"))
            w.evaluate("fetch('/api/actions/shutdown',{method:'POST'})")
            w.wait_for_selector("#tray .card.pending", timeout=8000)
            time.sleep(0.8)
            w.locator(".stage").screenshot(path=str(DOCS / "widget-approval.png"))
            w.click("#tray .btn.no")
            time.sleep(0.5)
            w.close()

            m = page_for(375, 812, 2)
            m.screenshot(path=str(DOCS / "dashboard-mobile.png"))
            m.screenshot(path=str(DOCS / "dashboard-mobile-full.png"), full_page=True)
            m.close()
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(5)
        except subprocess.TimeoutExpired:
            srv.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    print("console problems:", errors or "none")


if __name__ == "__main__":
    main()
