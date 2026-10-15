"""Vibe Coding commands: parse, classify (safe / confirm / blocked), resolve executables (npm.cmd, code.cmd, python), run as a job.

No shell is ever involved: a command string is tokenised here and started as an argv list. Pipes, `&&`, redirects and
%VAR% / $(...) expansion are therefore not supported (they are refused with an explanation), which also removes the
PowerShell / cmd quoting problems.  On Windows `.cmd` shims (npm, npx, code) are started directly after their arguments were
checked for cmd metacharacters.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..registry import Level
from ..safety import is_within

DEFAULT_WHITELIST = [
    "npm install", "npm i", "npm ci", "npm run dev", "npm run build", "npm run preview", "npm run test", "npm run lint",
    "npm start", "npm test",
    "pip install -r requirements.txt", "python -m pip install -r requirements.txt", "python -m venv .venv",
    "python -m pytest*", "python -m unittest*", "pytest*", "python -m uvicorn *", "uvicorn *",
    "python *.py", "python3 *.py", "py *.py", "node *.js",
    "git status*", "git diff*", "git log*", "git show*", "git add *", "git commit *", "git branch*", "git init",
]
# always refused, whatever the user would answer (in addition to safety.shell_blocked_patterns)
EXTRA_BLOCKED = [
    r"\brm\b", r"\brmdir\b", r"\brd\b", r"\bdel\b", r"\berase\b", r"\bRemove-Item\b", r"\bri\b\s+-r",
    r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\b", r"\bgit\s+push\b.*(--force|-f\b)", r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)",
    r"\bgit\s+rebase\b", r"\bgit\s+filter-", r"\bnpm\s+publish\b", r"\bnpm\s+login\b", r"\bnpm\s+config\s+set\b", r"\bnpm\s+adduser\b",
    r"\bsudo\b", r"\bchmod\s+-R\b", r"\bchown\b", r"\btaskkill\b", r"\bshutdown\b", r"\bnet\s+(user|localgroup)\b", r"\bicacls\b",
    r"\bpip\s+config\b", r"\bcurl\b.*\|\s*\w+", r"\bwget\b.*\|\s*\w+", r"\bpowershell\b.*\b(-enc|-e\b|-encodedcommand)", r"\bformat(\.com)?\s+[A-Za-z]:",
    r"\bmkfs\b", r"\bdd\s+if=", r"\bscp\b", r"\bssh\b", r"\bftp\b",
]
SHELL_LAUNCHERS = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "bash", "sh", "zsh", "wscript", "cscript", "mshta"}
PY_NAMES = {"python", "python3", "py", "python.exe", "py.exe", "python3.exe"}
LONG_RUNNING = [r"^npm run (dev|start|serve|preview)$", r"^npm (start)$", r"^(python3?|py)( -3)? -m (uvicorn|http\.server|flask)\b", r"^uvicorn\b",
                r"^flask run\b", r"^(npx )?vite( dev| preview)?( |$)", r"^node server\.js$", r"^node (app|index)\.js$"]

_META = re.compile(r"[&|;<>`\n\r^]|\$\(|\$\{|%[A-Za-z_][A-Za-z0-9_]*%")
_PATHISH = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~)|(?:^|[\\/])\.\.(?:[\\/]|$)")
_CMD_BAD_ARG = re.compile(r'[&|<>^%"\n\r]')


class CommandError(ValueError):
    pass


def tokenize(command: str) -> list[str]:
    """Small shell-free tokenizer: whitespace separated, '...' and "..." group (quotes removed); no escapes, no expansion."""
    out: list[str] = []
    cur: list[str] = []
    q = ""
    has = False
    for ch in command:
        if q:
            if ch == q:
                q = ""
            else:
                cur.append(ch)
        elif ch in "'\"":
            q = ch
            has = True
        elif ch.isspace():
            if cur or has:
                out.append("".join(cur))
                cur, has = [], False
        else:
            cur.append(ch)
    if q:
        raise CommandError("unbalanced quote")
    if cur or has:
        out.append("".join(cur))
    return out


def _norm(command: str) -> str:
    return " ".join(command.split()).lower()


def is_long_running(command: str) -> bool:
    n = _norm(command)
    return any(re.search(p, n) for p in LONG_RUNNING)


def classify(command: str, whitelist: list[str], blocked: list[str], project: Path | None = None) -> tuple[Level, str]:
    cmd = (command or "").strip()
    if not cmd:
        return Level.BLOCKED, "empty command"
    if len(cmd) > 500:
        return Level.BLOCKED, "command too long"
    for pat in blocked:
        try:
            if re.search(pat, cmd, re.I):
                return Level.BLOCKED, "destructive or security-sensitive command (always blocked)"
        except re.error:
            continue
    if _META.search(cmd):
        return Level.BLOCKED, "pipes, &&, ;, redirects, backticks and %VAR% are not supported: run one plain command at a time"
    try:
        argv = tokenize(cmd)
    except CommandError as e:
        return Level.BLOCKED, str(e)
    if not argv:
        return Level.BLOCKED, "empty command"
    exe = os.path.basename(argv[0].replace("\\", "/")).lower()
    if exe in SHELL_LAUNCHERS:
        return Level.BLOCKED, "starting another shell is not allowed; run the program directly"
    if "/" in argv[0] or "\\" in argv[0]:
        return Level.CONFIRM, "runs a program by path; needs your approval"
    pathy = [a for a in argv[1:] if _PATHISH.search(a.split("=", 1)[-1]) and not a.startswith("http")]
    if pathy:
        return Level.CONFIRM, f"mentions a path outside the project ({pathy[0]}); needs your approval"
    norm = " ".join(argv).lower()
    listed = any(fnmatch.fnmatchcase(norm, " ".join(w.split()).lower()) for w in whitelist)
    if listed and exe in PY_NAMES:
        rest = argv[1:]
        if rest and rest[0].startswith("-") and rest[0] != "-m":
            return Level.CONFIRM, "python flag that runs inline code; needs your approval"
        if rest and rest[0] == "-m" and len(rest) > 1 and rest[1] in ("pip",) and not (len(rest) >= 5 and rest[2] == "install" and rest[3] == "-r"):
            return Level.CONFIRM, "pip changes installed packages; needs your approval"
    if listed and exe in ("node", "node.exe") and len(argv) > 1 and argv[1].startswith("-"):
        return Level.CONFIRM, "node flag that runs inline code; needs your approval"
    if listed and exe == "git" and len(argv) > 1 and any(a in ("-c", "--exec-path", "--upload-pack") or a.startswith("--upload-pack") for a in argv[1:3]):
        return Level.CONFIRM, "unusual git option; needs your approval"
    if listed:
        return Level.SAFE, "on the Vibe command whitelist"
    return Level.CONFIRM, "not on the Vibe command whitelist; needs your approval"


# ------------------------------------------------------------------------------------------------ finding tools
_cache: dict[str, Any] = {}


def _first_existing(paths: list[str]) -> str | None:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def find_node_tool(name: str) -> str | None:
    """npm / npx / node. On Windows shutil.which honours PATHEXT, so `npm` -> `...\\nodejs\\npm.cmd`."""
    got = shutil.which(name)
    if got or sys.platform != "win32":
        return got
    pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
          os.path.expandvars(r"%LOCALAPPDATA%\Programs"), os.path.expandvars(r"%APPDATA%\npm")]
    ext = ".exe" if name == "node" else ".cmd"
    return _first_existing([os.path.join(base, "nodejs", name + ext) for base in pf[:3]] + [os.path.join(pf[3], name + ext)])


def find_vscode() -> str | None:
    """Returns something we can launch for `open in VS Code`. Prefers Code.exe (no .cmd/batch quoting involved)."""
    cached = _cache.get("code")
    if cached is not None:
        return cached or None
    found = shutil.which("code")
    if found and found.lower().endswith((".cmd", ".bat")):
        exe = Path(found).parent.parent / "Code.exe"       # <install>\bin\code.cmd -> <install>\Code.exe
        if exe.exists():
            found = str(exe)
    if not found and sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        found = _first_existing([os.path.join(la, "Programs", "Microsoft VS Code", "Code.exe"), os.path.join(pf, "Microsoft VS Code", "Code.exe")])
    _cache["code"] = found or ""
    return found


def find_python(configured: str = "") -> list[str] | None:
    """argv prefix for a real Python 3 (never the Windows Store stub, never Delta's own venv unless nothing else works)."""
    key = "py:" + configured
    if key in _cache:
        return _cache[key] or None
    cands: list[list[str]] = []
    if configured.strip():
        cands.append(tokenize(configured))
    if sys.platform == "win32":
        cands += [["py", "-3"], ["python"], ["python3"]]
    else:
        cands += [["python3"], ["python"]]
    cands.append([sys.executable])
    for c in cands:
        exe = shutil.which(c[0]) if not os.path.isabs(c[0]) else c[0]
        if not exe:
            continue
        try:
            cp = subprocess.run([exe, *c[1:], "-c", "import sys;print(sys.version_info[0])"], capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            continue
        if cp.returncode == 0 and cp.stdout.strip() == "3":
            _cache[key] = [exe, *c[1:]]
            return _cache[key]
    _cache[key] = []
    return None


def venv_python(project: Path) -> str | None:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        p = project / rel
        if p.exists():
            return str(p)
    return None


def resolve_argv(argv: list[str], project: Path, python_cfg: str = "") -> list[str]:
    """Turn the typed words into a launchable argv: python/pip -> project .venv or a real Python; npm/node/npx/git/code -> full path."""
    exe = argv[0]
    low = os.path.basename(exe.replace("\\", "/")).lower()
    rest = argv[1:]
    if low in PY_NAMES or low in ("pip", "pip3", "pytest", "uvicorn"):
        vpy = venv_python(project)
        base = [vpy] if vpy else find_python(python_cfg)
        if not base:
            raise CommandError("Python 3 was not found on this PC (install it from python.org and tick “Add to PATH”).")
        if low in PY_NAMES:
            if low in ("py", "py.exe") and rest[:1] and re.fullmatch(r"-3(\.\d+)?", rest[0]):
                rest = rest[1:]
            return [*base, *rest]
        if low in ("pip", "pip3"):
            return [*base, "-m", "pip", *rest]
        return [*base, "-m", low, *rest]
    if low in ("npm", "npx", "node"):
        found = find_node_tool(low)
        if not found:
            raise CommandError("Node.js was not found on this PC. Install it from https://nodejs.org (LTS) and restart Delta.")
        if found.lower().endswith((".cmd", ".bat")):
            for a in rest:
                if _CMD_BAD_ARG.search(a):
                    raise CommandError(f"argument {a!r} contains characters that are unsafe for npm.cmd on Windows")
        return [found, *rest]
    if low == "git":
        from .gitops import find_git
        g = find_git()
        if not g:
            raise CommandError("git was not found. Install it (winget install Git.Git).")
        return [g, *rest]
    found = shutil.which(exe)
    if not found:
        raise CommandError(f"“{exe}” was not found on PATH")
    if found.lower().endswith((".cmd", ".bat")):
        for a in rest:
            if _CMD_BAD_ARG.search(a):
                raise CommandError(f"argument {a!r} contains characters that are unsafe for a .cmd file")
    return [found, *rest]


def clean_env(secret_env_names: list[str], extra: dict | None = None) -> dict:
    """Environment for generated code: Delta's own LLM key (and anything named like a secret we know of) is removed."""
    e = dict(os.environ)
    for k in list(e):
        if k in secret_env_names or k.upper() in ("DELTA_LLM_API_KEY",):
            e.pop(k, None)
    e.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1",
              "npm_config_fund": "false", "npm_config_audit": "false", "npm_config_update_notifier": "false",
              "PIP_DISABLE_PIP_VERSION_CHECK": "1", "BROWSER": "none"})
    e.update(extra or {})
    return e


# ------------------------------------------------------------------------------------------------ running
def kill_tree(pid: int) -> None:
    try:
        import psutil
        p = psutil.Process(pid)
        kids = p.children(recursive=True)
        for c in kids:
            try:
                c.kill()
            except Exception:
                pass
        p.kill()
    except Exception:
        pass


@dataclass
class Job:
    argv: list[str]
    cwd: str
    lines: list[str] = field(default_factory=list)
    rc: int | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    error: str = ""
    timed_out: bool = False
    proc: Any = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def done(self) -> bool:
        return self.finished is not None

    def text(self, limit: int = 6000) -> str:
        with self._lock:
            t = "\n".join(self.lines)
        return t if len(t) <= limit else "[…earlier output trimmed…]\n" + t[-limit:]

    def cancel(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            kill_tree(self.proc.pid)


def start_job(argv: list[str], cwd: str, env: dict, timeout: float, on_line: Callable[[str], None] | None = None) -> Job:
    """Start argv (no shell) and read its output on a thread. Returns immediately; poll `job.done`."""
    job = Job(argv=argv, cwd=cwd)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        job.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    text=True, errors="replace", bufsize=1, shell=False, creationflags=flags,
                                    start_new_session=(sys.platform != "win32"))
    except (FileNotFoundError, PermissionError, OSError) as e:
        job.error = f"could not start: {e}"
        job.rc = -1
        job.finished = time.time()
        return job

    def reader():
        try:
            for ln in job.proc.stdout:
                ln = ln.rstrip("\r\n")
                with job._lock:
                    job.lines.append(ln)
                    if len(job.lines) > 4000:
                        del job.lines[:1000]
                if on_line:
                    on_line(ln)
        except Exception:
            pass

    def waiter():
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        try:
            job.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            job.timed_out = True
            kill_tree(job.proc.pid)
            try:
                job.proc.wait(5)
            except Exception:
                pass
        t.join(3)
        job.rc = job.proc.returncode
        job.finished = time.time()

    threading.Thread(target=waiter, daemon=True).start()
    return job
