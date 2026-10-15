"""Git safety net: init, snapshot before each agent run, undo (reset to the snapshot). Uses the `git` executable; never a shell."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_IGNORE = "node_modules/\n.venv/\nvenv/\n__pycache__/\n*.pyc\ndist/\n.env\n.DS_Store\nThumbs.db\n"
IDENT = ["-c", "user.name=Delta", "-c", "user.email=delta@localhost", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
         "-c", "core.safecrlf=false", "-c", "core.quotepath=off"]
_WIN_GIT = [r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files (x86)\Git\cmd\git.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe")]


class GitError(RuntimeError):
    pass


def find_git() -> str | None:
    g = shutil.which("git")
    if g:
        return g
    if sys.platform == "win32":
        for c in _WIN_GIT:
            if c and os.path.exists(c):
                return c
    return None


def _env() -> dict:
    e = dict(os.environ)
    e.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    return e


def git(project: Path, *args: str, check: bool = True, timeout: int = 60, git_exe: str | None = None) -> str:
    exe = git_exe or find_git()
    if not exe:
        raise GitError("git was not found. Install it (Windows: `winget install Git.Git`) and restart Delta.")
    try:
        cp = subprocess.run([exe, *IDENT, *args], cwd=str(project), capture_output=True, text=True, timeout=timeout, env=_env(),
                            errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} timed out")
    if check and cp.returncode != 0:
        raise GitError(f"git {' '.join(args[:2])} failed: {(cp.stderr or cp.stdout).strip()[:300]}")
    return (cp.stdout or "").strip()


def version() -> str | None:
    exe = find_git()
    if not exe:
        return None
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10, env=_env(),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip() or None
    except Exception:
        return None


def is_repo(project: Path) -> bool:
    # must be a repo rooted AT the project (not an enclosing repo found by walking up)
    return (project / ".git").exists()


def head(project: Path) -> str | None:
    out = git(project, "rev-parse", "--verify", "-q", "HEAD", check=False)
    return out or None


def ensure_repo(project: Path) -> None:
    if not is_repo(project):
        git(project, "init", "-q")
        # make sure the first commit has a stable branch name
        git(project, "symbolic-ref", "HEAD", "refs/heads/main", check=False)
    gi = project / ".gitignore"
    existing = gi.read_text(encoding="utf-8", errors="replace") if gi.exists() else ""
    need = []
    if (project / "node_modules").exists() and "node_modules" not in existing:
        need.append("node_modules/")
    if (project / ".venv").exists() and ".venv" not in existing:
        need.append(".venv/")
    if not gi.exists():
        gi.write_text(DEFAULT_IGNORE, encoding="utf-8")
    elif need:
        gi.write_text(existing.rstrip("\n") + "\n" + "\n".join(need) + "\n", encoding="utf-8")


def snapshot(project: Path, message: str) -> str:
    """Commit everything (so nothing is lost) and return the commit id. A clean tree reuses HEAD instead of adding an empty commit."""
    ensure_repo(project)
    git(project, "add", "-A")
    dirty = bool(git(project, "status", "--porcelain"))
    h = head(project)
    if dirty or h is None:
        git(project, "commit", "-q", "--allow-empty", "-m", message[:200])
        h = head(project)
    return h or ""


def commit_if_dirty(project: Path, message: str) -> str | None:
    git(project, "add", "-A")
    if git(project, "status", "--porcelain"):
        git(project, "commit", "-q", "-m", message[:200])
        return head(project)
    return None


def reset_hard(project: Path, sha: str) -> None:
    if not sha or not all(c in "0123456789abcdef" for c in sha.lower()) or len(sha) < 7:
        raise GitError("bad commit id")
    git(project, "reset", "--hard", "-q", sha)


def branch(project: Path) -> str:
    return git(project, "rev-parse", "--abbrev-ref", "HEAD", check=False) or "main"


def log(project: Path, n: int = 20) -> list[dict]:
    out = git(project, "log", f"-n{n}", "--pretty=format:%h%x1f%s%x1f%ct", check=False)
    rows = []
    for ln in out.splitlines():
        p = ln.split("\x1f")
        if len(p) == 3:
            rows.append({"sha": p[0], "subject": p[1], "ts": int(p[2] or 0)})
    return rows
