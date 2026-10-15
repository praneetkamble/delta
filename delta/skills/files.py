"""File tools. Every path goes through the Sandbox; nothing is ever overwritten; delete = Recycle Bin + confirmation."""
from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import time
from collections import defaultdict
from pathlib import Path

from ..registry import I, Level, Tool, ToolRegistry, B, fail, obj, ok, S
from ..safety import is_executable_path, is_within
from ..util import fmt_bytes

SKIP_DIRS = {".git", "node_modules", "__pycache__", "AppData", "$Recycle.Bin", "System Volume Information", ".venv", "venv", ".cache"}
CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic", ".tiff", ".ico"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".flv", ".m4v"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".md", ".epub"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".iso"},
    "Installers": {".exe", ".msi", ".msix", ".appx", ".dmg"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".c", ".cpp", ".cs", ".ipynb", ".sql", ".sh", ".bat", ".ps1"},
}
IN_PROGRESS = {".crdownload", ".part", ".tmp", ".download", ".partial"}
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml", ".ini", ".xml", ".cfg", ".toml", ".bat", ".ps1", ".sql", ".rtf"}


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def category_of(path: Path) -> str:
    ext = path.suffix.lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "Other"


def plan_organize(folder: Path) -> list[tuple[Path, Path]]:
    plan = []
    for entry in sorted(folder.iterdir()):
        if not entry.is_file() or entry.is_symlink() or entry.name.startswith("."):
            continue
        if entry.suffix.lower() in IN_PROGRESS or time.time() - entry.stat().st_mtime < 60:
            continue
        plan.append((entry, folder / category_of(entry) / entry.name))
    return plan


def _folder_or_default(ctx, folder: str | None, default_alias: str = "downloads") -> Path:
    if folder:
        return ctx.sandbox.resolve(folder)
    return ctx.sandbox.alias(default_alias) or ctx.sandbox.allowed[0]


# --------------------------------------------------------------------------- handlers
def search_files(ctx, query: str, folder: str | None = None, limit: int = 25):
    roots = [ctx.sandbox.resolve(folder)] if folder else [a for a in ctx.sandbox.allowed if a.exists()]
    q = query.lower().strip()
    use_glob = any(c in q for c in "*?")
    hits, visited, t0 = [], 0, time.time()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            depth = Path(dirpath).relative_to(root).parts
            if len(depth) > 8:
                dirnames[:] = []
            for name in filenames + dirnames:
                visited += 1
                ok_ = fnmatch.fnmatch(name.lower(), q) if use_glob else q in name.lower()
                if ok_:
                    hits.append(Path(dirpath) / name)
                    if len(hits) >= limit:
                        break
            if len(hits) >= limit or visited > 50000 or time.time() - t0 > 8:
                break
        if len(hits) >= limit:
            break
    if not hits:
        return ok(f"No files matching “{query}”.", results=[])
    lines = []
    for p in hits:
        try:
            st = p.stat()
            lines.append(f"{p}  ({'folder' if p.is_dir() else fmt_bytes(st.st_size)})")
        except OSError:
            lines.append(str(p))
    return ok(f"Found {len(hits)} match{'es' if len(hits) != 1 else ''} for “{query}”:\n" + "\n".join(lines), results=[str(p) for p in hits])


def list_folder(ctx, path: str, limit: int = 40):
    p = ctx.sandbox.resolve(path)
    if not p.is_dir():
        return fail(f"{p} is not a folder.")
    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    lines = [f"{'📁' if e.is_dir() else '📄'} {e.name}" + ("" if e.is_dir() else f"  ({fmt_bytes(e.stat().st_size)})") for e in entries[:limit]]
    more = f"\n…and {len(entries) - limit} more" if len(entries) > limit else ""
    return ok(f"{p} ({len(entries)} items)\n" + "\n".join(lines) + more, count=len(entries))


def _classify_open_path(ctx, args):
    try:
        p = ctx.sandbox.resolve(args["path"])
    except PermissionError:
        return Level.SAFE  # the handler will refuse and the sandbox violation is logged
    return Level.CONFIRM if is_executable_path(p) else Level.SAFE


def open_path(ctx, path: str):
    p = ctx.sandbox.resolve(path)
    if not p.exists():
        return fail(f"{p} does not exist.")
    ctx.adapter.open_path(p)
    return ok(f"Opened {p}.")


def create_folder(ctx, name: str, parent: str | None = None):
    base = _folder_or_default(ctx, parent, "documents")
    target = ctx.sandbox.resolve(str(base / name)) if not os.path.isabs(name) else ctx.sandbox.resolve(name)
    ctx.sandbox.check_not_root(target)
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    return ok(f"Folder already exists: {target}" if existed else f"Created folder {target}.", path=str(target))


def _dest(ctx, src: Path, dst: str) -> Path:
    d = ctx.sandbox.resolve(dst)
    if d.is_dir():
        d = d / src.name
    if is_within(str(src), str(d)) and src.is_dir():
        raise ValueError("can't put a folder inside itself")
    if not d.parent.exists():
        raise FileNotFoundError(f"destination folder {d.parent} does not exist")
    return unique_path(d)


def move_path(ctx, source: str, destination: str):
    src = ctx.sandbox.resolve(source)
    ctx.sandbox.check_not_root(src)
    if not src.exists():
        return fail(f"{src} does not exist.")
    try:
        d = _dest(ctx, src, destination)
    except (ValueError, FileNotFoundError) as e:
        return fail(str(e))
    shutil.move(str(src), str(d))
    return ok(f"Moved {src.name} → {d}.", path=str(d))


def copy_path(ctx, source: str, destination: str):
    src = ctx.sandbox.resolve(source)
    if not src.exists():
        return fail(f"{src} does not exist.")
    try:
        d = _dest(ctx, src, destination)
    except (ValueError, FileNotFoundError) as e:
        return fail(str(e))
    if src.is_dir():
        shutil.copytree(src, d, symlinks=True)
    else:
        shutil.copy2(src, d)
    return ok(f"Copied {src.name} → {d}.", path=str(d))


def _describe_organize(ctx, args):
    folder = _folder_or_default(ctx, args.get("folder"))
    plan = plan_organize(folder)
    if not plan:
        return f"Organize {folder}: nothing to move"
    counts: dict[str, int] = defaultdict(int)
    for _, d in plan:
        counts[d.parent.name] += 1
    return f"Move {len(plan)} files in {folder} into sub-folders: " + ", ".join(f"{k} ({v})" for k, v in sorted(counts.items()))


def organize_downloads(ctx, folder: str | None = None):
    root = _folder_or_default(ctx, folder)
    plan = plan_organize(root)
    moved = 0
    counts: dict[str, int] = defaultdict(int)
    for src, dst in plan:
        dst.parent.mkdir(exist_ok=True)
        shutil.move(str(src), str(unique_path(dst)))
        moved += 1
        counts[dst.parent.name] += 1
    if not moved:
        return ok(f"{root} is already tidy (nothing to move).")
    return ok(f"Organized {moved} files in {root}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ".", moved=moved)


def _hash(path: Path, first_only: bool = False) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read(65536) if first_only else b"")
        if not first_only:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def find_duplicates(ctx, folder: str | None = None, min_kb: int = 1):
    root = _folder_or_default(ctx, folder)
    by_size: dict[int, list[Path]] = defaultdict(list)
    n = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = Path(dirpath) / f
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz >= min_kb * 1024 and not p.is_symlink():
                by_size[sz].append(p)
                n += 1
        if n > 50000:
            break
    groups = []
    for sz, paths in by_size.items():
        if len(paths) < 2:
            continue
        quick: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            quick[_hash(p, True)].append(p)
        for cands in quick.values():
            if len(cands) < 2:
                continue
            full: dict[str, list[Path]] = defaultdict(list)
            for p in cands:
                full[_hash(p)].append(p)
            groups += [(sz, ps) for ps in full.values() if len(ps) > 1]
    if not groups:
        return ok(f"No duplicate files found in {root}.", groups=[])
    groups.sort(key=lambda g: -g[0] * (len(g[1]) - 1))
    wasted = sum(sz * (len(ps) - 1) for sz, ps in groups)
    lines = [f"Found {len(groups)} sets of duplicates in {root} (about {fmt_bytes(wasted)} reclaimable). I don't delete anything automatically."]
    for sz, ps in groups[:10]:
        lines.append(f"• {fmt_bytes(sz)} × {len(ps)}: " + "  |  ".join(p.name for p in ps))
    return ok("\n".join(lines), groups=[[str(p) for p in ps] for _, ps in groups])


def _describe_delete(ctx, args):
    p = ctx.sandbox.resolve(args["path"])
    if p.is_dir():
        cnt = sum(len(fs) for _, _, fs in os.walk(p))
        return f"Move the folder {p} ({cnt} files) to the Recycle Bin"
    sz = p.stat().st_size if p.exists() else 0
    return f"Move {p} ({fmt_bytes(sz)}) to the Recycle Bin"


def delete_path(ctx, path: str):
    p = ctx.sandbox.resolve(path)
    ctx.sandbox.check_not_root(p)
    if not p.exists():
        return fail(f"{p} does not exist.")
    ctx.adapter.trash(p)
    return ok(f"Moved {p.name} to the Recycle Bin (you can restore it from there).", path=str(p))


def read_file(ctx, path: str, max_chars: int = 6000):
    p = ctx.sandbox.resolve(path)
    if not p.is_file():
        return fail(f"{p} is not a file.")
    if p.suffix.lower() not in TEXT_EXTS:
        return fail(f"I can only read text-like files ({', '.join(sorted(TEXT_EXTS)[:8])}…), not {p.suffix or 'this type'}.")
    text = p.read_text(encoding="utf-8", errors="replace")
    return ok(text[:max_chars] + ("\n[truncated]" if len(text) > max_chars else ""), source=str(p), untrusted=True)


def register(reg: ToolRegistry) -> None:
    c = "files"
    reg.register(Tool("search_files", "Find files/folders by name (substring or * wildcard) inside the allowed folders.",
                      obj({"query": S, "folder": S, "limit": {**I, "minimum": 1, "maximum": 100}}, ["query"]), search_files, category=c, side_effects=False))
    reg.register(Tool("list_folder", "List the contents of a folder inside the allowed folders.",
                      obj({"path": S, "limit": {**I, "minimum": 1, "maximum": 200}}, ["path"]), list_folder, category=c, side_effects=False))
    reg.register(Tool("open_path", "Open a file or folder with its default program. Programs/scripts need confirmation.",
                      obj({"path": S}, ["path"]), open_path, Level.SAFE, c, classify=_classify_open_path,
                      describe=lambda ctx, a: f"Run/open the program or script {a['path']}"))
    reg.register(Tool("create_folder", "Create a folder (inside the allowed folders).", obj({"name": S, "parent": S}, ["name"]), create_folder, category=c))
    reg.register(Tool("move_path", "Move a file/folder. Never overwrites: a name clash gets ' (1)' appended.",
                      obj({"source": S, "destination": S}, ["source", "destination"]), move_path, category=c, taint_sensitive=True))
    reg.register(Tool("copy_path", "Copy a file/folder. Never overwrites.", obj({"source": S, "destination": S}, ["source", "destination"]), copy_path, category=c, taint_sensitive=True))
    reg.register(Tool("organize_downloads", "Sort files in Downloads (or another folder) into Images/Videos/Documents/... sub-folders.",
                      obj({"folder": S}), organize_downloads, Level.CONFIRM, c, describe=_describe_organize))
    reg.register(Tool("find_duplicates", "Find identical files (by content hash). Reports only; never deletes.",
                      obj({"folder": S, "min_kb": {**I, "minimum": 0}}), find_duplicates, category=c, side_effects=False))
    reg.register(Tool("delete_path", "Move a file/folder to the Recycle Bin (always asks first).", obj({"path": S}, ["path"]),
                      delete_path, Level.CONFIRM, c, always_confirm=True, describe=_describe_delete))
    reg.register(Tool("read_file", "Read a text-like file (returned as untrusted data).", obj({"path": S, "max_chars": {**I, "minimum": 100, "maximum": 20000}}, ["path"]),
                      read_file, category=c, side_effects=False, untrusted_output=True))
