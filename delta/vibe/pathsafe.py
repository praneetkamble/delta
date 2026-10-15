"""Path safety for Vibe Coding: project names, the projects root, and the per-project jail.

Every path the coding agent (or the viewer API) touches is a *relative* path that must stay inside ONE project folder.
Windows rules (drive letters, UNC, alternate data streams, reserved device names, trailing dots) are enforced on every
platform, so the same checks are testable on Linux.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from ..safety import SandboxError, is_within

NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
# directories the agent may not write into or list (huge, generated, or Git's own data)
HIDDEN_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".next", ".cache", ".idea"}
NO_WRITE_DIRS = HIDDEN_DIRS | {"dist", "build"}


class VibeError(SandboxError):
    """A refusal by the Vibe Coding safety rules (subclass of SandboxError so the gate reports it as 'Blocked')."""


def default_projects_root(platform: str | None = None) -> str:
    return "D:/Vibe" if (platform or sys.platform) == "win32" else "~/DeltaProjects"


def configured_root(ctx: Any) -> Path:
    raw = str(ctx.config.get("vibe.projects_root") or "").strip() or default_projects_root()
    return Path(os.path.expanduser(raw))


def resolve_root(ctx: Any) -> tuple[Path | None, str]:
    """(root, problem). root is None when it is not inside allowed_folders (then Vibe Coding refuses to write anything)."""
    root = configured_root(ctx)
    real = os.path.realpath(str(root))
    allowed = [os.path.realpath(os.path.expanduser(str(p))) for p in ctx.config.allowed_folders]
    if not any(is_within(a, real) for a in allowed):
        return None, (f"The projects folder {root} is not inside safety.allowed_folders. Add it (or a parent such as {root.parent}) to "
                      f"allowed_folders in config.yaml, or set vibe.projects_root to a folder that is already allowed.")
    return Path(real), ""


def check_project_name(name: str) -> str:
    n = (name or "").strip()
    if not NAME_RX.fullmatch(n):
        raise VibeError("Project names use letters, digits, dot, dash or underscore (max 64), and must start with a letter or digit.")
    if n.endswith((".", " ")) or n.split(".")[0].lower() in RESERVED:
        raise VibeError(f"“{n}” is not allowed as a project name on Windows.")
    if n.lower() in {".git", "node_modules"}:
        raise VibeError("That name is reserved.")
    return n


def project_dir(root: Path, name: str) -> Path:
    n = check_project_name(name)
    p = Path(os.path.realpath(str(root / n)))
    if not is_within(str(root), str(p)) or os.path.normcase(str(p)) == os.path.normcase(str(root)):
        raise VibeError("Project folder resolves outside the projects folder.")
    return p


_DRIVE = re.compile(r"^[A-Za-z]:")


def clean_rel(rel: str, *, for_write: bool = False) -> str:
    """Validate an agent/user supplied relative path and return it normalised to forward slashes."""
    if not isinstance(rel, str) or not rel.strip():
        raise VibeError("empty path")
    if "\x00" in rel or any(ord(c) < 32 for c in rel):
        raise VibeError("invalid characters in path")
    p = rel.strip().replace("\\", "/")
    if p.startswith("//") or _DRIVE.match(p) or p.startswith("/") or p.startswith("~"):
        raise VibeError(f"“{rel}” is an absolute path; use a path relative to the project folder")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts:
        raise VibeError("empty path")
    for part in parts:
        if part == "..":
            raise VibeError("“..” is not allowed: paths must stay inside the project")
        low = part.lower()
        if ":" in part:
            raise VibeError("“:” is not allowed in a path (drive letters and alternate data streams are refused)")
        if part.endswith((".", " ")) or low.split(".")[0] in RESERVED:
            raise VibeError(f"“{part}” is not a valid Windows file name")
        if any(c in part for c in '<>"|?*'):
            raise VibeError(f"“{part}” contains characters that are not allowed in file names")
        if low == ".git":
            raise VibeError("the .git folder is off limits")
    if for_write and any(x.lower() in NO_WRITE_DIRS for x in parts[:-1]):
        raise VibeError("writing inside node_modules, .venv, dist, build or caches is not allowed")
    if for_write and parts[-1].lower() in NO_WRITE_DIRS:
        raise VibeError("that name is reserved")
    return "/".join(parts)


def resolve_in(project: Path, rel: str, *, for_write: bool = False) -> tuple[Path, str]:
    """-> (absolute real path, clean relative path). Symlinks/junctions are resolved BEFORE the containment check."""
    clean = clean_rel(rel, for_write=for_write)
    base = os.path.realpath(str(project))
    real = os.path.realpath(os.path.join(base, *clean.split("/")))
    if not is_within(base, real) or os.path.normcase(real) == os.path.normcase(base):
        raise VibeError(f"“{rel}” resolves outside the project folder")
    return Path(real), clean


def is_text_bytes(data: bytes) -> bool:
    return b"\x00" not in data[:8192]


LANG_BY_EXT = {
    ".py": "python", ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".json": "json",
    ".html": "html", ".htm": "html", ".vue": "html", ".svelte": "html", ".xml": "html", ".svg": "html",
    ".css": "css", ".scss": "css", ".md": "md", ".yml": "yaml", ".yaml": "yaml", ".toml": "yaml", ".ini": "yaml",
    ".sh": "sh", ".bat": "sh", ".cmd": "sh", ".ps1": "sh", ".txt": "text", ".env": "yaml", ".gitignore": "text",
}


def lang_of(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1].lower()
    if name in LANG_BY_EXT:
        return LANG_BY_EXT[name]
    ext = os.path.splitext(name)[1]
    return LANG_BY_EXT.get(ext, "text")
