"""Real-browser checks (headless Chrome via playwright): the preview port cannot talk to Delta, and the in-house highlighter works.
Skipped automatically when playwright or Chrome is not installed."""
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pw = pytest.importorskip("playwright.sync_api")
CHROME = os.environ.get("CHROME") or next((p for p in ("/usr/bin/google-chrome", shutil.which("google-chrome") or "", shutil.which("chromium") or "") if p and os.path.exists(p)), None)
pytestmark = pytest.mark.skipif(not CHROME, reason="no Chrome found")

import uvicorn  # noqa: E402

from delta.server import create_app  # noqa: E402
from delta.vibe.preview import free_port  # noqa: E402

from vibe_helpers import make_vibe_ctx  # noqa: E402

TOKEN = "b" * 32


class Recorder(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Recorder.seen.append({"path": self.path, "host": self.headers.get("Host"), "cookie": self.headers.get("Cookie"), "site": self.headers.get("Sec-Fetch-Site")})
        body = b"<!doctype html><title>evil preview</title><script>window.__go = (url, opts) => fetch(url, opts).then(r => r.status, e => 'blocked: ' + e.message)</script>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("browser")
    ctx = make_vibe_ctx(tmp)
    ctx.vibe.create_project("p", "static")
    dport, pport = free_port(), free_port()
    app = create_app(ctx, TOKEN, dport)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=dport, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    rec = ThreadingHTTPServer(("127.0.0.1", pport), Recorder)
    threading.Thread(target=rec.serve_forever, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    yield dport, pport, ctx
    rec.shutdown()
    server.should_exit = True
    ctx.vibe.preview.stop_all()


@pytest.fixture
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"], headless=True)
        yield b
        b.close()


def test_code_on_another_loopback_port_cannot_use_the_delta_session(stack, browser):
    dport, pport, ctx = stack
    c = browser.new_context()
    c.add_cookies([{"name": "delta_token", "value": TOKEN, "url": f"http://127.0.0.1:{dport}/"}])
    page = c.new_page()
    Recorder.seen.clear()
    api = f"http://127.0.0.1:{dport}/api/vibe/status"
    # (a) sibling PORT on the same host name: the browser DOES send the cookie to it (cookies ignore ports) ...
    page.goto(f"http://127.0.0.1:{pport}/")
    assert Recorder.seen[-1]["cookie"] and TOKEN in Recorder.seen[-1]["cookie"]
    # ... but a request from that page to Delta carries Sec-Fetch-Site: same-site and is refused, even though the cookie is valid
    statuses = []
    page.on("response", lambda r: statuses.append((r.url, r.status)) if r.url.startswith(f"http://127.0.0.1:{dport}/") else None)
    page.evaluate("([u]) => window.__go(u, {credentials: 'include', mode: 'no-cors'})", [api])
    page.evaluate("([u]) => window.__go(u + 'ects', {method: 'POST', credentials: 'include', mode: 'no-cors', headers: {'Content-Type': 'text/plain'}, body: '{\"name\":\"evil\",\"template\":\"static\"}'})", [f"http://127.0.0.1:{dport}/api/vibe/proj"])
    time.sleep(0.8)
    assert statuses and all(code == 403 for _, code in statuses), statuses
    assert "evil" not in [p["name"] for p in ctx.vibe.list_projects()]
    # (b) the SAME page loaded via the other loopback name (what the Preview panel does): the cookie is never sent to the preview server
    Recorder.seen.clear()
    page.goto(f"http://localhost:{pport}/")
    assert Recorder.seen and Recorder.seen[-1]["cookie"] is None
    statuses.clear()
    page.evaluate("([u]) => window.__go(u, {credentials: 'include', mode: 'no-cors'})", [api])
    time.sleep(0.8)
    assert statuses and all(code in (401, 403) for _, code in statuses), statuses
    c.close()


def test_delta_itself_still_works_same_origin(stack, browser):
    dport, pport, ctx = stack
    c = browser.new_context()
    page = c.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{dport}/?token={TOKEN}")
    page.wait_for_selector("#nav button")
    page.click("#nav button:has-text('Vibe Coding')")
    page.wait_for_selector(".vb-proj")
    assert "p" in page.inner_text(".vb-proj-t b")
    assert page.evaluate("fetch('/api/vibe/status').then(r => r.status)") == 200
    # the CSP only lets Delta frame loopback pages
    csp = page.evaluate("fetch('/').then(r => r.headers.get('content-security-policy'))")
    assert "frame-src http://127.0.0.1:* http://localhost:*" in csp
    assert not errors
    c.close()


def test_highlighter_tokens_in_a_real_browser(stack, browser):
    dport, pport, ctx = stack
    c = browser.new_context()
    page = c.new_page()
    page.goto(f"http://127.0.0.1:{dport}/?token={TOKEN}")
    page.wait_for_selector("#nav button")
    tk = lambda src, lang: page.evaluate("([s, l]) => DeltaVibe.tokenize(s, l).filter(t => t[0]).map(t => t[0] + ':' + t[1])", [src, lang])
    js = tk('const x = foo("a b"); // note\nclass Box {}', "js")
    assert "k:const" in js and 's:"a b"' in js and "c:// note" in js and "f:foo" in js and "t:Box" in js
    py = tk('def run(n):\n    """doc\n    more"""\n    return n + 42  # hi', "python")
    assert "k:def" in py and any(t.startswith("s:") and "doc" in t for t in py) and "n:42" in py and "c:# hi" in py and "k:return" in py
    css = tk("a.btn { color: #fff; margin: 4px; --x: 1; }", "css")
    assert "p:color" in css and "n:#fff" in css and "n:4px" in css and "v:--x" in css
    html = tk('<div class="a" id=b>hi &amp; <!-- c --></div>', "html")
    assert "t:<div" in html and "a:class" in html and 's:"a"' in html and "c:<!-- c -->" in html and "n:&amp;" in html
    js_json = tk('{"a": [1, true, null], "b": "x"}', "json")
    assert 'p:"a"' in js_json and "n:1" in js_json and "k:true" in js_json and 's:"x"' in js_json
    # injected HTML in file contents is shown as text, never parsed
    n_scripts = page.evaluate("""() => { const host = document.createElement('div'); document.body.append(host);
        const lines = DeltaVibe.toLines(DeltaVibe.tokenize('<img src=x onerror=alert(1)><script>alert(2)</script>', 'html'));
        lines[0].forEach(([t, s]) => host.append(Object.assign(document.createElement('span'), {textContent: s})));
        return host.querySelectorAll('img,script').length; }""")
    assert n_scripts == 0
    # an unterminated string / comment must not hang the tokenizer
    assert page.evaluate("DeltaVibe.tokenize('\"unterminated /* never closed ' + 'x'.repeat(50000), 'js').length") > 0
    c.close()
