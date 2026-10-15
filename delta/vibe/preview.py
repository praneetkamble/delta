"""Live preview: a built-in static server (static sites) or the project's own dev server (Vite, Express, FastAPI/Flask),
always bound to 127.0.0.1 on a free port. Collects logs, detects errors and exposes them for 'Fix this error'."""
from __future__ import annotations

import atexit
import functools
import http.client
import http.server
import json
import os
import re
import socket
import threading
import time
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Any

from .commands import Job, clean_env, find_node_tool, find_python, kill_tree, resolve_argv, start_job, venv_python
from .pathsafe import VibeError

ERROR_PATTERNS = [
    r"Traceback \(most recent call last\)", r"\b(Syntax|Type|Reference|Name|Import|ModuleNotFound|Attribute|Key|Value|Runtime)Error\b",
    r"Cannot find module", r"\bUncaught\b", r"\[vite\].*(error|failed)", r"Failed to resolve import", r"Internal server error",
    r"\bEADDRINUSE\b", r"\bnpm ERR!", r"\bERR_[A-Z_]+\b", r"error TS\d+", r"\bERROR\b", r"Unexpected token", r"is not defined",
    r"\[browser\]", r"command not found", r"No module named", r"\bENOENT\b", r"Error: ",
]
_ERR_RX = re.compile("|".join(ERROR_PATTERNS))
_NOISE = re.compile(r"(?i)\b(0 errors|no errors|error-free|errors? fixed)\b")

REPORTER = ("<script>(function(){function s(m){try{fetch('/__delta_err',{method:'POST',headers:{'Content-Type':'text/plain'},body:String(m).slice(0,600)})}catch(e){}}"
            "addEventListener('error',function(e){s('Uncaught '+(e.message||'error')+' at '+(e.filename||'').split('/').pop()+':'+(e.lineno||0))});"
            "addEventListener('unhandledrejection',function(e){s('Unhandled promise rejection: '+((e.reason&&e.reason.message)||e.reason))});})();</script>")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


class _Handler(http.server.SimpleHTTPRequestHandler):
    log_sink = None   # set per server

    def log_message(self, fmt, *args):
        if self.log_sink:
            self.log_sink(f"{self.command} {self.path.split('?')[0]} → {args[1] if len(args) > 1 else ''}")

    def _blocked(self) -> bool:
        parts = [p for p in urllib.parse.unquote(self.path.split("?")[0]).replace("\\", "/").split("/") if p]
        return any(p.startswith(".") for p in parts) or ".." in parts

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, "No index.html in this folder")
        return None

    def do_POST(self):
        if self.path.split("?")[0] == "/__delta_err":
            n = min(int(self.headers.get("Content-Length") or 0), 2000)
            msg = self.rfile.read(n).decode("utf-8", "replace")
            if self.log_sink:
                self.log_sink("[browser] " + msg)
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(405)

    def do_GET(self):
        if self._blocked():
            self.send_error(404)
            return
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            idx = os.path.join(path, "index.html")
            if os.path.exists(idx):
                path = idx
        if path.lower().endswith((".html", ".htm")) and os.path.isfile(path):
            try:
                body = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self.send_error(404)
                return
            m = re.search(r"<head[^>]*>", body, re.I)
            body = (body[:m.end()] + REPORTER + body[m.end():]) if m else REPORTER + body
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_HEAD(self):
        if self._blocked():
            self.send_error(404)
            return
        super().do_HEAD()


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Preview:
    def __init__(self, project: str, root: Path, kind: str):
        self.project = project
        self.root = root
        self.kind = kind
        self.status = "starting"        # starting | running | crashed | stopped | done
        self.message = "Starting…"
        self.port = 0
        self.url = ""
        self.job: Job | None = None
        self.server: _Server | None = None
        self.lines: deque[tuple[int, str]] = deque(maxlen=800)
        self.seq = 0
        self.errors: deque[tuple[int, str]] = deque(maxlen=8)
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.started = time.time()
        self.http_errors = 0

    def log(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, line[:400]))
            if _ERR_RX.search(line) and not _NOISE.search(line):
                self.errors.append((self.seq, line[:300]))


class PreviewManager:
    def __init__(self, mgr: Any):
        self.mgr = mgr
        self.items: dict[str, Preview] = {}
        self.lock = threading.RLock()
        atexit.register(self.stop_all)

    # ------------------------------------------------------------------ control
    def start(self, project: str) -> dict:
        p = self.mgr.project_path(project)
        with self.lock:
            cur = self.items.get(project)
            if cur and cur.status in ("starting", "running"):
                return {**self.status(project), "message": "The preview is already running."}
        kind = self.mgr.detect_kind(p)
        pv = Preview(project, p, kind)
        with self.lock:
            self.items[project] = pv
        t = threading.Thread(target=self._boot, args=(pv,), daemon=True, name=f"vibe-preview-{project}")
        t.start()
        return {**self.status(project), "message": "Starting the preview…"}

    def stop(self, project: str) -> None:
        with self.lock:
            pv = self.items.get(project)
        if pv is None:
            return
        pv.stop_flag.set()
        if pv.server is not None:
            try:
                pv.server.shutdown()
                pv.server.server_close()
            except Exception:
                pass
            pv.server = None
        if pv.job is not None:
            pv.job.cancel()
        if pv.status in ("starting", "running"):
            pv.status = "stopped"
            pv.message = "Stopped."
        pv.log("— stopped —")
        self.mgr.ctx.audit.log("vibe_preview", project=project, action="stop")

    def stop_all(self) -> None:
        for name in list(self.items):
            try:
                self.stop(name)
            except Exception:
                pass

    # ------------------------------------------------------------------ status
    def status(self, project: str, since: int = 0) -> dict:
        with self.lock:
            pv = self.items.get(project)
        if pv is None:
            return {"status": "stopped", "kind": "", "url": "", "port": 0, "message": "Not running.", "lines": [], "next": 0, "errors": [], "can_fix": False}
        if pv.job is not None and pv.job.done and pv.status == "running":
            pv.status = "crashed" if pv.job.rc not in (0, None) else "stopped"
            pv.message = f"The server exited with code {pv.job.rc}."
        with pv.lock:
            lines = [{"i": i, "t": t} for i, t in pv.lines if i > since]
            errs = [{"i": i, "t": t} for i, t in pv.errors]
            nxt = pv.seq
        return {"status": pv.status, "kind": pv.kind, "url": pv.url if pv.status == "running" else "", "port": pv.port, "message": pv.message,
                "lines": lines, "next": nxt, "errors": errs, "can_fix": bool(errs) and pv.status in ("running", "crashed", "done"), "started": pv.started}

    def error_text(self, project: str, max_chars: int = 3500) -> str:
        with self.lock:
            pv = self.items.get(project)
        if pv is None:
            return ""
        with pv.lock:
            tail = [t for _, t in list(pv.lines)[-60:]]
        text = "\n".join(tail)
        return text[-max_chars:]

    # ------------------------------------------------------------------ booting (runs on a thread)
    def _boot(self, pv: Preview) -> None:
        try:
            self.mgr.ctx.audit.log("vibe_preview", project=pv.project, action="start", kind=pv.kind)
            k = pv.kind
            if k in ("static", "blank") and (pv.root / "index.html").exists():
                self._boot_static(pv)
            elif k in ("react-vite", "vite", "express", "node"):
                self._boot_node(pv)
            elif k in ("fastapi", "flask"):
                self._boot_python_web(pv)
            elif k == "python-script":
                self._boot_script(pv)
            else:
                pv.status = "stopped"
                pv.message = "Nothing to preview yet: there is no index.html, package.json or main.py. Ask Delta to build something first."
                pv.log(pv.message)
        except VibeError as e:
            pv.status = "crashed"
            pv.message = str(e)
            pv.log("ERROR: " + str(e))
        except Exception as e:
            pv.status = "crashed"
            pv.message = f"Could not start: {e}"
            pv.log(f"ERROR: could not start: {type(e).__name__}: {e}")

    def _boot_static(self, pv: Preview) -> None:
        pv.port = free_port()
        cls = type("H", (_Handler,), {"log_sink": staticmethod(pv.log)})   # per-server subclass: logs of two projects never mix
        srv = _Server(("127.0.0.1", pv.port), functools.partial(cls, directory=str(pv.root)))
        pv.server = srv
        threading.Thread(target=srv.serve_forever, daemon=True, name="vibe-static").start()
        pv.url = f"http://127.0.0.1:{pv.port}/"
        pv.status = "running"
        pv.message = f"Serving the folder at {pv.url}"
        pv.log(f"Static server on {pv.url} (edits show after Refresh)")

    # ---- helpers for external processes
    def _blocking(self, pv: Preview, argv: list[str], cwd: Path, timeout: float, label: str) -> bool:
        pv.log(f"$ {label}")
        pv.message = label
        job = start_job(argv, str(cwd), clean_env(self.mgr.secret_env_names()), timeout, on_line=pv.log)
        pv.job = job
        while not job.done:
            if pv.stop_flag.is_set():
                job.cancel()
                return False
            time.sleep(0.25)
        if job.rc != 0:
            pv.log(f"ERROR: `{label}` exited with code {job.rc}" + (f" ({job.error})" if job.error else ""))
        return job.rc == 0

    def _serve(self, pv: Preview, argv: list[str], extra_env: dict, ready_timeout: float = 90.0) -> None:
        pv.message = "Starting the server…"
        job = start_job(argv, str(pv.root), clean_env(self.mgr.secret_env_names(), extra_env), 6e5, on_line=pv.log)
        pv.job = job
        pv.log("$ " + " ".join(os.path.basename(a) if i == 0 else a for i, a in enumerate(argv)))
        t0 = time.time()
        while time.time() - t0 < ready_timeout and not pv.stop_flag.is_set():
            if job.done:
                pv.status = "crashed"
                pv.message = f"The server stopped right away (exit code {job.rc})."
                pv.log(f"ERROR: server exited with code {job.rc}")
                return
            if port_open(pv.port):
                pv.url = f"http://127.0.0.1:{pv.port}/"
                pv.status = "running"
                pv.message = f"Running at {pv.url}"
                threading.Thread(target=self._health, args=(pv,), daemon=True).start()
                return
            time.sleep(0.4)
        if not pv.stop_flag.is_set():
            pv.status = "crashed"
            pv.message = "The server did not open its port in time. See the log."
            pv.log("ERROR: timed out waiting for the server to listen on port " + str(pv.port))
            job.cancel()

    def _health(self, pv: Preview) -> None:
        """Every few seconds ask for / and note a 5xx once (the dev server stays up but the page is broken)."""
        while pv.status == "running" and not pv.stop_flag.is_set():
            time.sleep(4)
            try:
                c = http.client.HTTPConnection("127.0.0.1", pv.port, timeout=3)
                c.request("GET", "/")
                code = c.getresponse().status
                c.close()
                if code >= 500 and pv.http_errors < 3:
                    pv.http_errors += 1
                    pv.log(f"ERROR: GET / returned HTTP {code}")
            except OSError:
                pass

    def _boot_node(self, pv: Preview) -> None:
        npm = find_node_tool("npm")
        if not npm:
            raise VibeError("Node.js was not found on this PC. Install the LTS version from https://nodejs.org and restart Delta.")
        pj = json.loads((pv.root / "package.json").read_text(encoding="utf-8", errors="replace"))
        scripts = pj.get("scripts", {}) or {}
        if not (pv.root / "node_modules").exists():
            if not self._blocking(pv, resolve_argv(["npm", "install"], pv.root), pv.root, 900, "npm install"):
                pv.status = "crashed" if not pv.stop_flag.is_set() else "stopped"
                pv.message = "npm install failed. See the log."
                return
        pv.port = free_port()
        env = {"PORT": str(pv.port), "HOST": "127.0.0.1"}
        deps = {**pj.get("dependencies", {}), **pj.get("devDependencies", {})}
        if "vite" in deps and "dev" in scripts:
            argv = resolve_argv(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(pv.port), "--strictPort"], pv.root)
        elif "dev" in scripts:
            argv = resolve_argv(["npm", "run", "dev"], pv.root)
        elif "start" in scripts:
            argv = resolve_argv(["npm", "start"], pv.root)
        elif pj.get("main"):
            argv = resolve_argv(["node", str(pj["main"])], pv.root)
        else:
            raise VibeError("package.json has no dev or start script to run.")
        self._serve(pv, argv, env)

    def _boot_python_web(self, pv: Preview) -> None:
        if venv_python(pv.root) is None:
            base = find_python(str(self.mgr.cfg("python", "") or ""))
            if not base:
                raise VibeError("Python 3 was not found on this PC (install it from python.org and tick “Add to PATH”).")
            if not self._blocking(pv, [*base, "-m", "venv", ".venv"], pv.root, 300, "python -m venv .venv"):
                pv.status = "crashed"
                pv.message = "Could not create the virtual environment."
                return
        vpy = venv_python(pv.root)
        req = pv.root / "requirements.txt"
        if req.exists() and not (pv.root / ".venv" / ".delta-installed").exists():
            if not self._blocking(pv, [vpy, "-m", "pip", "install", "-r", "requirements.txt"], pv.root, 900, "pip install -r requirements.txt"):
                pv.status = "crashed" if not pv.stop_flag.is_set() else "stopped"
                pv.message = "pip install failed. See the log."
                return
            try:
                (pv.root / ".venv" / ".delta-installed").write_text(str(time.time()), encoding="utf-8")
            except OSError:
                pass
        pv.port = free_port()
        if pv.kind == "flask":
            argv = [vpy, "-m", "flask", "--app", "app" if (pv.root / "app.py").exists() else "main", "run", "--host", "127.0.0.1", "--port", str(pv.port)]
        else:
            mod = "main" if (pv.root / "main.py").exists() else "app"
            argv = [vpy, "-m", "uvicorn", f"{mod}:app", "--host", "127.0.0.1", "--port", str(pv.port)]
        self._serve(pv, argv, {})

    def _boot_script(self, pv: Preview) -> None:
        py = venv_python(pv.root)
        base = [py] if py else find_python(str(self.mgr.cfg("python", "") or ""))
        if not base:
            raise VibeError("Python 3 was not found on this PC.")
        ok = self._blocking(pv, [*base, "main.py"], pv.root, 120, "python main.py")
        pv.status = "done" if ok else "crashed"
        pv.message = "Finished." if ok else "The script failed. See the log."
