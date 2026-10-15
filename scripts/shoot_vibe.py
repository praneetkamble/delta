"""End-to-end Vibe Coding demo with a MOCK language model (no network, no API key, no cost).

Starts Delta in demo mode (mock adapter) against a scripted fake OpenAI-compatible LLM server, then drives the real dashboard in headless
Chrome: create a project, ask for a one-page site, review the diffs, accept, preview it, critique it twice and iterate, approve a command,
look at the code and history, then repeat a short flow at phone width. Everything shown is produced by the real Vibe Coding code.

    python scripts/shoot_vibe.py            # screenshots -> docs/vibe-*.png

Needs `playwright` and a Chrome at /usr/bin/google-chrome (override with CHROME=...). DELTA_PY = python that can run Delta.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from delta.vibe.difftools import make_diff  # noqa: E402

DOCS = ROOT / "docs"
PORT, LLM_PORT = 8797, 8796
SERVER_PY = os.environ.get("DELTA_PY", sys.executable)
CHROME = os.environ.get("CHROME", "/usr/bin/google-chrome")

# ---------------------------------------------------------------------------------------------- what the "model" writes
HTML_1 = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Café Aroma</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="top"><strong>Café Aroma</strong><nav><a href="#menu">Menu</a><a href="#hours">Hours</a><a href="#contact">Contact</a></nav></header>
  <main>
    <section class="hero">
      <h1>Café Aroma</h1>
      <p class="lead">Small-batch coffee and fresh pastries, baked every morning on Elm Street.</p>
    </section>
    <section id="menu">
      <h2>Menu</h2>
      <ul class="menu">
        <li>Espresso - 3.00</li>
        <li>Flat white - 4.20</li>
        <li>Cold brew - 4.50</li>
        <li>Almond croissant - 3.80</li>
      </ul>
    </section>
    <section id="hours">
      <h2>Opening hours</h2>
      <p>Mon-Fri 7:00-18:00, Sat-Sun 8:00-16:00</p>
    </section>
    <section id="contact">
      <h2>Contact</h2>
      <p>12 Elm Street · hello@cafearoma.example · 020 7946 0123</p>
    </section>
  </main>
  <script src="script.js"></script>
</body>
</html>
"""
CSS_1 = """:root { --bg: #1b130e; --ink: #f1e6d8; --accent: #d98e4a; --muted: #7a6a5b; }
* { box-sizing: border-box; margin: 0; }
body { font: 16px/1.6 Georgia, "Times New Roman", serif; background: var(--bg); color: var(--ink); }
.top { display: flex; justify-content: space-between; align-items: center; padding: 18px 40px; border-bottom: 1px solid #ffffff1a; letter-spacing: .06em; }
nav a { color: var(--muted); margin-left: 22px; text-decoration: none; }
main { max-width: 820px; margin: 0 auto; padding: 56px 24px; }
.hero { padding: 70px 0 50px; }
h1 { font-size: 64px; line-height: 1.05; }
h2 { color: var(--accent); margin: 40px 0 12px; font-size: 26px; }
.lead { color: var(--muted); margin-top: 14px; max-width: 34em; }
.menu { list-style: none; padding: 0; }
.menu li { padding: 6px 0; color: var(--muted); }
p { color: var(--muted); }
"""
# critique 1: prices hard to scan, text too faint, no call to action
HTML_2 = HTML_1.replace('<p class="lead">Small-batch coffee and fresh pastries, baked every morning on Elm Street.</p>',
                        '<p class="lead">Small-batch coffee and fresh pastries, baked every morning on Elm Street.</p>\n      <a class="btn" href="#menu">See the menu</a>')
for name, price in (("Espresso", "3.00"), ("Flat white", "4.20"), ("Cold brew", "4.50"), ("Almond croissant", "3.80")):
    HTML_2 = HTML_2.replace(f"<li>{name} - {price}</li>", f'<li><span>{name}</span><b>£{price}</b></li>')
CSS_2 = (CSS_1.replace("--muted: #7a6a5b", "--muted: #c9b8a6")
         .replace(".menu li { padding: 6px 0; color: var(--muted); }",
                  ".menu li { display: flex; justify-content: space-between; gap: 16px; padding: 9px 0; border-bottom: 1px dotted #ffffff30; color: var(--ink); }\n"
                  ".menu b { color: var(--accent); font-variant-numeric: tabular-nums; }\n"
                  ".btn { display: inline-block; margin-top: 26px; padding: 12px 26px; border-radius: 99px; background: var(--accent); color: #1b130e; text-decoration: none; font-weight: 700; }\n"
                  ".btn:hover { filter: brightness(1.1); }"))
# critique 2: not usable on a phone, add a footer
HTML_3 = HTML_2.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">').replace(
    "  <script src=\"script.js\"></script>", '  <footer class="foot">© 2026 Café Aroma · Baked fresh daily</footer>\n  <script src="script.js"></script>')
CSS_3 = CSS_2 + """.foot { text-align: center; padding: 34px 20px; color: var(--muted); border-top: 1px solid #ffffff1a; font-size: 14px; }
@media (max-width: 640px) {
  .top { flex-direction: column; gap: 10px; padding: 14px 18px; }
  nav a { margin: 0 11px; }
  main { padding: 28px 18px; }
  .hero { padding: 36px 0 26px; }
  h1 { font-size: 40px; }
  .btn { display: block; text-align: center; }
}
"""
# phone run: add an About blurb
HTML_4 = HTML_3.replace('    <section id="hours">', '    <section id="about">\n      <h2>Our story</h2>\n      <p>Mara and Tom opened Café Aroma in 2019 with one grinder and a very loud oven. We still roast in small batches and bake before sunrise.</p>\n    </section>\n    <section id="hours">')

P0 = "Build a one-page website for Café Aroma, a small coffee shop: a hero, a menu with prices, opening hours and a contact section. Warm dark theme."
P1 = "Critique: the menu prices are hard to scan, the grey text is too faint to read, and the hero has no call to action. Please fix those three things."
P2 = "Critique 2: on a phone the header links overflow and the heading is huge. Make it responsive and add a small footer."
P3 = "Add a short “Our story” section before the opening hours."


def tc(name, args, i):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def text(t):
    return {"role": "assistant", "content": t}


def script():
    n = iter(range(1, 999))
    q = []
    # run 0: build the first version
    q += [tc("list_files", {}, next(n)), tc("read_file", {"path": "index.html"}, next(n)), tc("read_file", {"path": "style.css"}, next(n)),
          tc("write_file", {"path": "index.html", "content": HTML_1}, next(n)), tc("write_file", {"path": "style.css", "content": CSS_1}, next(n)),
          text("I built a one-page site for Café Aroma: a hero, a menu with four items, opening hours and a contact section, in a warm dark theme.\n"
               "Files: index.html and style.css (waiting for your review). Preview it after you accept them.")]
    # run 1: critique 1
    q += [tc("read_file", {"path": "index.html"}, next(n)), tc("apply_patch", {"patch": make_diff("index.html", HTML_1, HTML_2)}, next(n)),
          tc("apply_patch", {"patch": make_diff("style.css", CSS_1, CSS_2)}, next(n)),
          text("Fixed all three: prices are now right-aligned with dotted leaders, the muted text is much lighter, and the hero has a “See the menu” button.")]
    # run 2: critique 2 + a command that needs approval (git tag is not on the whitelist)
    q += [tc("apply_patch", {"patch": make_diff("index.html", HTML_2, HTML_3)}, next(n)), tc("apply_patch", {"patch": make_diff("style.css", CSS_2, CSS_3)}, next(n)),
          tc("run_command", {"command": "git tag v1-responsive"}, next(n)),
          text("The page is now responsive: the header stacks on small screens, the heading scales down, the button is full width, and there is a footer. I tagged this version in git as v1-responsive.")]
    # run 3: phone flow
    q += [tc("apply_patch", {"patch": make_diff("index.html", HTML_3, HTML_4)}, next(n)), text("Added an “Our story” section before the opening hours.")]
    return q


QUEUE = script()
LLM_LOG = []


class FakeLLM(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        LLM_LOG.append(body)
        time.sleep(0.9)                                       # so the UI visibly "thinks"
        msg = QUEUE.pop(0) if QUEUE else text("Done.")
        data = json.dumps({"choices": [{"message": msg}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_llm():
    srv = ThreadingHTTPServer(("127.0.0.1", LLM_PORT), FakeLLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def start_delta(tmp: Path):
    home = tmp / "home"
    for n in ("Downloads", "Documents", "Desktop", "Pictures", "Projects"):
        (home / n).mkdir(parents=True, exist_ok=True)
    cfg = tmp / "config.yaml"
    cfg.write_text(f"""adapter: mock
user_name: Praneet
data_dir: {tmp / 'data'}
safety:
  allowed_folders: ['{home / "Downloads"}', '{home / "Documents"}', '{home / "Desktop"}', '{home / "Pictures"}', '{home / "Projects"}']
llm:
  base_url: http://127.0.0.1:{LLM_PORT}/v1
  model: demo-model
vibe:
  projects_root: '{home / "Projects"}'
routines_file: {ROOT / 'routines.example.yaml'}
""")
    env = dict(os.environ, PYTHONPATH=str(ROOT), DELTA_LLM_API_KEY="demo-not-a-real-key")
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
    return srv, url_file.read_text().strip(), home / "Projects"


def api(token, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET",
                                 headers={"x-delta-token": token, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read() or b"{}")


def main():
    from playwright.sync_api import sync_playwright
    tmp = Path(tempfile.mkdtemp(prefix="vibe-demo-"))
    llm = start_llm()
    srv, url, projects = start_delta(tmp)
    token = url.split("token=")[1]
    errors = []
    try:
        for name, tpl in (("todo-api", "fastapi"), ("notes-app", "react-vite"), ("scratch", "python-script")):
            api(token, "/api/vibe/projects", {"name": name, "template": tpl})
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"], headless=True)

            def new_page(w, h, mobile=False, scale=1):
                c = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale, is_mobile=mobile, has_touch=mobile)
                pg = c.new_page()
                pg.on("console", lambda m: errors.append(f"{w}: console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
                pg.on("response", lambda r: errors.append(f"{w}: HTTP {r.status} {r.url.split('?')[0]}") if r.status >= 400 else None)
                pg.on("pageerror", lambda e: errors.append(f"{w}: pageerror: {e}"))
                pg.goto(url)
                pg.wait_for_selector("#g-name:not(:empty)")
                time.sleep(1.5)
                return pg

            def idle(pg, timeout=60000):
                pg.wait_for_function("() => { const b = document.querySelector('.vb-compose .btn.go'); return b && !b.disabled; }", timeout=timeout)
                time.sleep(0.5)

            def ask(pg, prompt):
                pg.fill(".vb-compose textarea", prompt)
                pg.keyboard.press("Enter")
                pg.wait_for_function("() => { const b = document.querySelector('.vb-compose .btn.go'); return b && b.disabled; }", timeout=10000)

            def shot(pg, name):
                time.sleep(0.5)
                pg.screenshot(path=str(DOCS / f"vibe-{name}.png"))
                print("saved", f"docs/vibe-{name}.png")

            d = new_page(1440, 900)
            d.click("#nav li:nth-child(5) button")
            d.wait_for_selector(".vb-proj")
            shot(d, "projects")

            # --- create the project from the template picker
            d.fill("#vb-name", "cafe-aroma")
            d.click(".vb-tpl[data-key=static]")
            d.click(".vb-new .btn.go")
            d.wait_for_selector(".vb-compose textarea")
            time.sleep(1.0)
            shot(d, "new-project")

            # --- round 0: build
            ask(d, P0)
            time.sleep(2.2)
            shot(d, "agent-working")
            idle(d)
            d.wait_for_selector(".vb-ch")
            shot(d, "review-diffs")
            d.click(".vb-ch-all .btn.go")                   # Accept all
            time.sleep(1.2)

            # --- code viewer with the in-house highlighter
            d.click(".vb-tabs .vb-tab:nth-child(2)")
            d.wait_for_selector(".vb-code .cl")
            d.click(".vb-ti.file:has-text('style.css')")
            time.sleep(0.6)
            shot(d, "code")

            # --- live preview v1
            d.click(".vb-tabs .vb-tab:nth-child(3)")
            d.click(".vb-pvbar .btn.go")
            fr = d.frame_locator("iframe.vb-frame")
            fr.locator("h1").wait_for(timeout=15000)
            time.sleep(0.8)
            shot(d, "preview-v1")

            # --- critique 1 -> iterate
            ask(d, P1)
            idle(d)
            d.wait_for_selector(".vb-ch")
            shot(d, "critique-1-diff")
            d.click(".vb-ch-all .btn.go")
            time.sleep(1.0)
            d.click(".vb-tabs .vb-tab:nth-child(3)")
            d.click(".vb-pvbar .btn:has-text('Refresh')")
            fr.locator(".btn").wait_for(timeout=15000)
            time.sleep(0.8)
            shot(d, "preview-v2")

            # --- critique 2 -> iterate; the agent then wants to run a command that is not whitelisted
            ask(d, P2)
            d.wait_for_selector(".vb-phase.wait", timeout=60000)
            time.sleep(0.8)
            shot(d, "waiting-review")
            d.click(".vb-tabs .vb-tab:nth-child(1)")
            d.wait_for_selector(".vb-ch")
            d.click(".vb-ch-all .btn.go")
            d.wait_for_selector(".vb-ap", timeout=30000)
            time.sleep(0.8)
            shot(d, "approval")
            d.click(".vb-ap .btn.go")                       # approve `git tag v1-responsive`
            idle(d)
            d.click(".vb-tabs .vb-tab:nth-child(3)")
            d.click(".vb-pvbar .btn:has-text('Refresh')")
            fr.locator(".foot").wait_for(timeout=15000)
            time.sleep(0.8)
            shot(d, "preview-final")
            d.click(".vb-tabs .vb-tab:nth-child(4)")
            time.sleep(0.8)
            shot(d, "history")
            d.close()

            # --- phone width
            m = new_page(375, 812, mobile=True, scale=2)
            m.click(".nav button:has-text('Vibe')") if m.query_selector(".nav button:has-text('Vibe')") else m.evaluate("document.querySelectorAll('#nav button')[4].click()")
            m.wait_for_selector(".vb-proj")
            shot(m, "mobile-projects")
            m.click(".vb-proj:has-text('cafe-aroma')")
            m.wait_for_selector(".vb-compose textarea")
            ask(m, P3)
            time.sleep(2.0)
            shot(m, "mobile-chat")
            idle(m)
            m.click(".vb-mtabs .vb-tab:has-text('Changes')")
            m.wait_for_selector(".vb-ch")
            shot(m, "mobile-review")
            m.click(".vb-ch-all .btn.go")
            time.sleep(1.0)
            m.click(".vb-mtabs .vb-tab:has-text('Code')")
            time.sleep(0.8)
            shot(m, "mobile-code")
            m.click(".vb-mtabs .vb-tab:has-text('Preview')")
            if m.query_selector(".vb-pvbar .btn.go"):
                m.click(".vb-pvbar .btn.go")
            else:
                m.click(".vb-pvbar .btn:has-text('Refresh')")
            m.frame_locator("iframe.vb-frame").locator("#about").wait_for(timeout=15000)
            time.sleep(0.8)
            shot(m, "mobile-preview")
            m.close()
            b.close()
        # the model really was driven through the gate: show proof
        audit = [json.loads(l) for l in (tmp / "data" / "audit.jsonl").read_text().splitlines() if l.strip()] if (tmp / "data" / "audit.jsonl").exists() else []
        kinds = {}
        for a in audit:
            kinds[a.get("event")] = kinds.get(a.get("event"), 0) + 1
        print("audit events:", kinds)
        print("LLM requests:", len(LLM_LOG), "| queue left:", len(QUEUE))
        print("cafe-aroma git log:", subprocess.run(["git", "-C", str(projects / "cafe-aroma"), "log", "--oneline"], capture_output=True, text=True).stdout.strip().replace("\n", " | "))
        print("browser console/network problems:", errors or "none")
    finally:
        srv.terminate()
        llm.shutdown()


if __name__ == "__main__":
    main()
