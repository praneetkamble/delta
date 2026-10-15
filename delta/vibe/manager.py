"""VibeManager: projects, staged changes (review-before-apply), runs, history/undo. The agent loop lives in agent.py,
the dev-server preview in preview.py, and the gate-facing tool wrappers in tools.py (everything goes through Engine.execute)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..safety import redact_secrets
from . import gitops, templates
from .commands import DEFAULT_WHITELIST, EXTRA_BLOCKED, classify, find_node_tool, find_python, find_vscode
from .difftools import PatchError, apply_file_patch, count_changes, make_diff, parse_patch
from .pathsafe import (HIDDEN_DIRS, VibeError, check_project_name, clean_rel, is_text_bytes, lang_of, project_dir, resolve_in,
                       resolve_root)

MAX_TREE = 2500


@dataclass
class Change:
    id: str
    project: str
    run_id: str
    path: str
    op: str                       # create | modify | delete
    old: str | None
    new: str | None
    diff: str = ""
    added: int = 0
    removed: int = 0
    status: str = "pending"       # pending | accepted | rejected | failed
    ts: float = field(default_factory=time.time)
    note: str = ""

    def summary(self, with_diff: bool = False) -> dict:
        d = {"id": self.id, "project": self.project, "run": self.run_id, "path": self.path, "op": self.op, "status": self.status,
             "added": self.added, "removed": self.removed, "note": self.note, "ts": self.ts, "lang": lang_of(self.path)}
        if with_diff:
            d["diff"] = self.diff if len(self.diff) < 120_000 else self.diff[:120_000] + "\n… diff truncated …\n"
        return d


@dataclass
class Step:
    id: int
    ts: float
    kind: str       # user | info | think | tool | result | change | approval | error | done
    text: str
    path: str = ""
    status: str = ""
    ref: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "ts": self.ts, "kind": self.kind, "text": self.text, "path": self.path, "status": self.status, "ref": self.ref}


class Run:
    def __init__(self, project: str, prompt: str, kind: str = "chat"):
        self.id = uuid.uuid4().hex[:8]
        self.project = project
        self.prompt = prompt
        self.kind = kind                      # chat | fix
        self.status = "queued"                # queued | running | waiting_approval | waiting_review | done | error | cancelled | stopped
        self.phase = "Starting"
        self.mode = "llm"                     # llm | rules
        self.steps: list[Step] = []
        self.final = ""
        self.snapshot = ""
        self.end_sha = ""
        self.started = time.time()
        self.finished: float | None = None
        self.cancel = threading.Event()
        self.tainted = False
        self.jobs: dict[str, Any] = {}
        self.results: dict[str, Any] = {}
        self.notices: list[str] = []
        self.live: dict | None = None
        self.change_ids: list[str] = []
        self.rev = 0                          # bumped whenever the set/status of changes changes
        self.waiting_pid = ""
        self._seq = 0
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None

    def add(self, kind: str, text: str, path: str = "", status: str = "", ref: str = "") -> Step:
        with self.lock:
            self._seq += 1
            s = Step(self._seq, time.time(), kind, text[:4000], path, status, ref)
            self.steps.append(s)
            return s

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running", "waiting_approval", "waiting_review")


class VibeManager:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.lock = threading.RLock()
        self.runs: dict[str, Run] = {}
        self.changes: dict[str, Change] = {}
        self.pending: dict[str, dict[str, str]] = {}       # project -> {path: change id}
        self._state_cache: dict[str, dict] = {}
        from .preview import PreviewManager
        self.preview = PreviewManager(self)
        self.llm_override: Any = None                        # tests / alternative clients

    # ------------------------------------------------------------------ config + environment
    def cfg(self, key: str, default: Any = None) -> Any:
        v = self.ctx.config.get("vibe." + key, default)
        return default if v is None else v

    def whitelist(self) -> list[str]:
        v = self.cfg("command_whitelist", None)
        return list(DEFAULT_WHITELIST) if v is None else [str(x) for x in v]          # [] = nothing runs without asking

    def blocked_patterns(self) -> list[str]:
        glob = [p for p in (self.ctx.config.get("safety.shell_blocked_patterns", []) or []) if p != r"\bformat\b"]
        extra = self.cfg("command_blocked_patterns", None) or []          # ADDS to the built-in list; it can never remove a built-in block
        return list(glob) + list(EXTRA_BLOCKED) + [str(x) for x in extra]

    def secret_env_names(self) -> list[str]:
        return [str(self.ctx.config.get("llm.api_key_env") or "DELTA_LLM_API_KEY")]

    def classify_command(self, command: str, project: Path | None = None):
        return classify(command, self.whitelist(), self.blocked_patterns(), project)

    def root(self) -> tuple[Path | None, str]:
        return resolve_root(self.ctx)

    def llm(self):
        if self.llm_override is not None:
            return self.llm_override
        if not self.cfg("use_llm", True):
            return None
        base = self.ctx.llm
        if base is None or not base.available:
            return None
        from ..llm import LLMClient
        return LLMClient(base.base_url, base.model, base.api_key, float(self.cfg("llm_timeout_s", 120)), 0.2, transport=base.transport)

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        root, problem = self.root()
        llm = self.llm()
        node = find_node_tool("node")
        npm = find_node_tool("npm")
        py = find_python(str(self.cfg("python", "") or ""))
        gv = gitops.version()
        return {
            "ready": root is not None, "problem": problem, "root": str(root) if root else str(os.path.expanduser(str(self.cfg("projects_root", "") or ""))),
            "root_exists": bool(root and root.is_dir()), "templates": templates.public_list(),
            "git": {"found": bool(gv), "version": gv or ""}, "node": {"found": bool(node and npm)}, "python": {"found": bool(py)},
            "vscode": {"found": bool(find_vscode())},
            "llm": {"available": bool(llm), "model": getattr(llm, "model", "") if llm else ""},
            "mode": "ai" if llm else "rules", "max_steps": int(self.cfg("max_steps", 16)),
            "active_runs": [r.id for r in self.runs.values() if r.active],
            "pending_changes": sum(len(v) for v in self.pending.values()),
        }

    # ------------------------------------------------------------------ per-project persisted state
    def _state_path(self, name: str) -> Path:
        d = self.ctx.config.data_dir / "vibe"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{check_project_name(name)}.json"

    def state(self, name: str) -> dict:
        with self.lock:
            st = self._state_cache.get(name)
            if st is None:
                p = self._state_path(name)
                try:
                    st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                except (OSError, ValueError):
                    st = {}
                st.setdefault("auto_accept", False)
                st.setdefault("history", [])
                st.setdefault("convo", [])
                st.setdefault("template", "")
                self._state_cache[name] = st
            return st

    def save_state(self, name: str) -> None:
        with self.lock:
            st = self._state_cache.get(name)
            if st is not None:
                try:
                    self._state_path(name).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
                except OSError:
                    pass

    # ------------------------------------------------------------------ projects
    def project_path(self, name: str, must_exist: bool = True) -> Path:
        root, problem = self.root()
        if root is None:
            raise VibeError(problem)
        p = project_dir(root, name)
        if must_exist and not p.is_dir():
            raise VibeError(f"No project called “{name}”.")
        return p

    def detect_kind(self, p: Path) -> str:
        pj = p / "package.json"
        if pj.exists():
            try:
                data = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
            except ValueError:
                data = {}
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "vite" in deps:
                return "react-vite" if "react" in deps else "vite"
            if "express" in deps:
                return "express"
            return "node"
        req = p / "requirements.txt"
        if (p / "main.py").exists() or (p / "app.py").exists():
            txt = req.read_text(encoding="utf-8", errors="replace").lower() if req.exists() else ""
            src = ""
            for f in ("main.py", "app.py"):
                if (p / f).exists():
                    src += (p / f).read_text(encoding="utf-8", errors="replace")[:20000].lower()
            if "fastapi" in txt or "fastapi" in src:
                return "fastapi"
            if "flask" in txt or "flask" in src:
                return "flask"
            return "python-script"
        if (p / "index.html").exists():
            return "static"
        return "blank"

    def list_projects(self) -> list[dict]:
        root, problem = self.root()
        if root is None or not root.is_dir():
            return []
        out = []
        for d in sorted(root.iterdir(), key=lambda x: x.name.lower()):
            if not d.is_dir() or d.name.startswith(".") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", d.name):
                continue
            try:
                mt = max([d.stat().st_mtime] + [f.stat().st_mtime for f in list(d.glob("*"))[:60] if f.is_file()])
            except OSError:
                mt = 0
            st = self.state(d.name)
            out.append({"name": d.name, "kind": self.detect_kind(d), "template": st.get("template", ""), "modified": mt,
                        "git": (d / ".git").exists(), "runs": len(st["history"]),
                        "pending": len(self.pending.get(d.name, {})), "active": any(r.active and r.project == d.name for r in self.runs.values())})
        out.sort(key=lambda r: r["modified"], reverse=True)
        return out

    def create_project(self, name: str, template: str) -> dict:
        name = check_project_name(name)
        if template not in templates.TEMPLATES:
            raise VibeError(f"Unknown template “{template}”. Choose one of: {', '.join(templates.TEMPLATES)}.")
        root, problem = self.root()
        if root is None:
            raise VibeError(problem)
        p = project_dir(root, name)
        if p.exists():
            raise VibeError(f"A folder called “{name}” already exists in {root}. Pick another name, or open it from the list.")
        root.mkdir(parents=True, exist_ok=True)
        p.mkdir()
        for rel, text in templates.render(template, name).items():
            tgt, _ = resolve_in(p, rel, for_write=True)
            tgt.parent.mkdir(parents=True, exist_ok=True)
            with open(tgt, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        git_ok = True
        try:
            gitops.snapshot(p, f"Delta: new {template} project")
        except gitops.GitError:
            git_ok = False
        st = self.state(name)
        st["template"] = template
        self.save_state(name)
        return {"name": name, "path": str(p), "template": template, "git": git_ok}

    def tree(self, name: str) -> list[dict]:
        p = self.project_path(name)
        out: list[dict] = []
        pend = self.pending.get(name, {})
        base = str(p)
        for root_dir, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d.lower() not in HIDDEN_DIRS and not d.startswith(".") or d in (".github",))
            rel_dir = os.path.relpath(root_dir, base).replace("\\", "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            for d in dirs:
                out.append({"path": (rel_dir + "/" if rel_dir else "") + d, "type": "dir"})
            for f in sorted(files):
                rel = (rel_dir + "/" if rel_dir else "") + f
                if f.startswith(".") and f not in (".gitignore", ".env.example"):
                    continue
                try:
                    size = os.path.getsize(os.path.join(root_dir, f))
                except OSError:
                    size = 0
                out.append({"path": rel, "type": "file", "size": size, "pending": rel in pend})
            if len(out) > MAX_TREE:
                break
        for rel, cid in pend.items():     # files that exist only as a staged change
            ch = self.changes.get(cid)
            if ch and ch.op == "create" and not any(o["path"] == rel for o in out):
                out.append({"path": rel, "type": "file", "size": len((ch.new or "").encode()), "pending": True, "staged": True})
        out.sort(key=lambda o: (o["path"].lower()))
        return out[:MAX_TREE]

    def read_for_view(self, name: str, rel: str) -> dict:
        p = self.project_path(name)
        real, clean = resolve_in(p, rel)
        if not real.is_file():
            ch = self.changes.get(self.pending.get(name, {}).get(clean, ""))
            if ch and ch.new is not None:
                return {"path": clean, "text": ch.new, "binary": False, "truncated": False, "size": len(ch.new), "lang": lang_of(clean), "staged": True}
            raise VibeError(f"“{clean}” is not a file.")
        data = real.read_bytes()[:400_001]
        if not is_text_bytes(data):
            return {"path": clean, "text": "", "binary": True, "truncated": False, "size": real.stat().st_size, "lang": "text"}
        trunc = len(data) > 400_000
        text = redact_secrets(data[:400_000].decode("utf-8", errors="replace")) if clean.lower().endswith((".env",)) else data[:400_000].decode("utf-8", errors="replace")
        return {"path": clean, "text": text, "binary": False, "truncated": trunc, "size": real.stat().st_size, "lang": lang_of(clean)}

    # ------------------------------------------------------------------ project file access (overlay of staged changes)
    def current_text(self, name: str, rel: str) -> str | None:
        """What the agent sees: the staged version if there is one, else the file on disk. None = does not exist."""
        with self.lock:
            cid = self.pending.get(name, {}).get(rel)
            if cid:
                return self.changes[cid].new
        p = self.project_path(name)
        real, _ = resolve_in(p, rel)
        return self._disk_text(real)

    @staticmethod
    def _disk_text(real: Path) -> str | None:
        if not real.is_file():
            return None
        data = real.read_bytes()
        if not is_text_bytes(data):
            raise VibeError("that is a binary file; I only edit text files")
        return data.decode("utf-8", errors="replace")

    def disk_text(self, name: str, rel: str) -> str | None:
        p = self.project_path(name)
        real, _ = resolve_in(p, rel)
        return self._disk_text(real)

    def iter_files(self, name: str, limit: int = 3000):
        p = self.project_path(name)
        base = str(p)
        seen = set()
        n = 0
        for root_dir, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d.lower() not in HIDDEN_DIRS and not d.startswith("."))
            for f in sorted(files):
                if f.startswith(".") and f != ".gitignore":
                    continue
                rel = os.path.relpath(os.path.join(root_dir, f), base).replace("\\", "/")
                seen.add(rel)
                n += 1
                yield rel
                if n >= limit:
                    return
        for rel, cid in list(self.pending.get(name, {}).items()):
            ch = self.changes.get(cid)
            if ch and ch.op == "create" and rel not in seen:
                yield rel

    # ------------------------------------------------------------------ staged changes
    def auto_accept(self, name: str) -> bool:
        return bool(self.state(name).get("auto_accept"))

    def set_auto_accept(self, name: str, enabled: bool) -> None:
        self.project_path(name)
        self.state(name)["auto_accept"] = bool(enabled)
        self.save_state(name)
        self.ctx.audit.log("vibe_auto_accept", project=name, enabled=bool(enabled), via="ui")

    def _check_size(self, text: str) -> None:
        if len(text.encode("utf-8", errors="replace")) > int(self.cfg("max_file_bytes", 400_000)):
            raise VibeError(f"file too large (limit {int(self.cfg('max_file_bytes', 400_000)) // 1000} KB)")

    def stage(self, run: Run, rel: str, new: str | None) -> Change | None:
        """Stage a create/modify (new is text) or delete (new is None). Returns the Change, or None if nothing would change."""
        name = run.project
        p = self.project_path(name)
        real, clean = resolve_in(p, rel, for_write=True)
        if real.is_dir():
            raise VibeError(f"“{clean}” is a folder")
        if new is not None:
            self._check_size(new)
        with self.lock:
            existing_id = self.pending.get(name, {}).get(clean)
            base = self.changes[existing_id].old if existing_id else self._disk_text(real)   # original on-disk text
            if len(run.change_ids) >= int(self.cfg("max_changes_per_run", 80)) and not existing_id:
                raise VibeError("too many files changed in one run; accept or reject the current ones first")
            if new is None and base is None and not existing_id:
                raise VibeError(f"“{clean}” does not exist")
            if new is not None and new == base:
                if existing_id:
                    self._drop(existing_id, "reverted to the original")
                return None
            if new is None and existing_id and base is None:      # created then deleted in the same review: nothing left
                self._drop(existing_id, "created then deleted")
                return None
            op = "delete" if new is None else ("create" if base is None else "modify")
            ch = Change(uuid.uuid4().hex[:8], name, run.id, clean, op, base, new)
            ch.diff = make_diff(clean, base, new)
            ch.added, ch.removed = count_changes(ch.diff)
            if existing_id:
                old = self.changes.pop(existing_id)
                if existing_id in run.change_ids:
                    run.change_ids.remove(existing_id)
                self.pending[name].pop(clean, None)
            self.changes[ch.id] = ch
            self.pending.setdefault(name, {})[clean] = ch.id
            run.change_ids.append(ch.id)
            run.rev += 1
        return ch

    def _drop(self, cid: str, why: str) -> None:
        ch = self.changes.get(cid)
        if ch:
            ch.status = "rejected"
            ch.note = why
            self.pending.get(ch.project, {}).pop(ch.path, None)
            r = self.runs.get(ch.run_id)
            if r:
                r.rev += 1

    def _apply_to_disk(self, ch: Change) -> None:
        p = self.project_path(ch.project)
        real, clean = resolve_in(p, ch.path, for_write=True)
        cur = self._disk_text(real)
        if cur != ch.old:
            raise VibeError(f"{clean} changed on disk after this edit was proposed (conflict). Reject this change and ask again.")
        if ch.op == "delete":
            real.unlink()
        else:
            real.parent.mkdir(parents=True, exist_ok=True)
            with open(real, "w", encoding="utf-8", newline="") as fh:
                fh.write(ch.new or "")

    def accept(self, cid: str, via: str = "ui") -> Change:
        with self.lock:
            ch = self.changes.get(cid)
            if ch is None or ch.status != "pending":
                raise VibeError("That change is not waiting for review (already handled or discarded).")
            try:
                self._apply_to_disk(ch)
            except (VibeError, OSError) as e:
                ch.status = "failed"
                ch.note = str(e)
                self.pending.get(ch.project, {}).pop(ch.path, None)
                self._bump(ch)
                self.ctx.audit.log("vibe_change", project=ch.project, path=ch.path, op=ch.op, status="failed", reason=str(e), via=via)
                raise VibeError(str(e))
            ch.status = "accepted"
            self.pending.get(ch.project, {}).pop(ch.path, None)
            self._bump(ch)
            self.ctx.audit.log("vibe_change", project=ch.project, path=ch.path, op=ch.op, status="accepted", added=ch.added, removed=ch.removed,
                               run=ch.run_id, via=via)
            return ch

    def reject(self, cid: str, via: str = "ui") -> Change:
        with self.lock:
            ch = self.changes.get(cid)
            if ch is None or ch.status != "pending":
                raise VibeError("That change is not waiting for review (already handled or discarded).")
            ch.status = "rejected"
            self.pending.get(ch.project, {}).pop(ch.path, None)
            self._bump(ch)
            r = self.runs.get(ch.run_id)
            if r:
                r.notices.append(f"The user REJECTED your change to {ch.path}; do not re-apply it unless they ask.")
            self.ctx.audit.log("vibe_change", project=ch.project, path=ch.path, op=ch.op, status="rejected", run=ch.run_id, via=via)
            return ch

    def _bump(self, ch: Change) -> None:
        r = self.runs.get(ch.run_id)
        if r:
            r.rev += 1

    def pending_changes(self, name: str, with_diff: bool = True) -> list[dict]:
        with self.lock:
            return [self.changes[c].summary(with_diff) for c in self.pending.get(name, {}).values() if c in self.changes]

    def pending_ids(self, name: str) -> list[str]:
        with self.lock:
            return list(self.pending.get(name, {}).values())

    # ------------------------------------------------------------------ patch application (used by the apply_patch tool)
    def stage_patch(self, run: Run, patch_text: str) -> list[Change]:
        fps = parse_patch(patch_text)
        staged: list[tuple[str, str | None]] = []
        for fp in fps:
            path = fp.path
            clean = clean_rel(path, for_write=True)
            cur = self.current_text(run.project, clean)
            if fp.new_path is None:
                if cur is None:
                    raise PatchError(f"{clean}: cannot delete a file that does not exist")
                staged.append((clean, None))
                continue
            if fp.old_path is None and cur not in (None, ""):
                raise PatchError(f"{clean} already exists; patch it with hunks against its current content (or use write_file)")
            staged.append((clean, apply_file_patch(cur, fp)))
        out = []
        for clean, text in staged:         # nothing is staged unless every file in the patch applies
            ch = self.stage(run, clean, text)
            if ch:
                out.append(ch)
        return out

    # ------------------------------------------------------------------ runs, history, undo
    def get_run(self, rid: str) -> Run | None:
        return self.runs.get(rid)

    def active_run(self, name: str) -> Run | None:
        for r in self.runs.values():
            if r.project == name and r.active:
                return r
        return None

    def history(self, name: str) -> list[dict]:
        st = self.state(name)
        rows = list(reversed(st["history"]))
        last_ok = next((r["id"] for r in rows if not r.get("undone") and r.get("snapshot")), None)
        for r in rows:
            r["can_undo"] = (r["id"] == last_ok) and not self.active_run(name)
        return rows

    def record_run(self, run: Run, summary: str) -> None:
        st = self.state(run.project)
        files = sorted({self.changes[c].path for c in run.change_ids if c in self.changes and self.changes[c].status in ("accepted", "pending")})
        pend = [self.changes[c].path for c in run.change_ids if c in self.changes and self.changes[c].status == "pending"]
        st["history"].append({"id": run.id, "prompt": run.prompt[:300], "ts": run.started, "status": run.status, "snapshot": run.snapshot,
                              "end_sha": run.end_sha, "files": files, "pending": pend, "mode": run.mode, "kind": run.kind,
                              "summary": summary[:600], "undone": False})
        st["history"] = st["history"][-60:]
        st["convo"].append({"role": "user", "content": run.prompt[:1500]})
        st["convo"].append({"role": "assistant", "content": (summary or run.final or "Done.")[:1200]})
        st["convo"] = st["convo"][-8:]
        self.save_state(run.project)

    def undo_last(self, name: str) -> str:
        """Called from the (confirmed) vibe_undo tool. Commits the current state first so even undo can be reversed."""
        p = self.project_path(name)
        if self.active_run(name):
            raise VibeError("A run is still in progress; stop it first.")
        st = self.state(name)
        target = next((r for r in reversed(st["history"]) if not r.get("undone") and r.get("snapshot")), None)
        if not target:
            raise VibeError("There is no earlier run to undo.")
        try:
            backup = gitops.snapshot(p, f"Delta: state before undoing run {target['id']}")
            gitops.reset_hard(p, target["snapshot"])
        except gitops.GitError as e:
            raise VibeError(str(e))
        with self.lock:                     # staged changes were proposed against the old files
            for cid in list(self.pending.get(name, {}).values()):
                self._drop(cid, "discarded by undo")
        target["undone"] = True
        target["undo_backup"] = backup
        self.save_state(name)
        self.ctx.audit.log("vibe_undo", project=name, run=target["id"], restored=target["snapshot"][:10], backup=(backup or "")[:10])
        return (f"Undid run {target['id']} (“{target['prompt'][:60]}”): files are back to how they were before it. "
                f"Your state just before the undo is saved in git as {(backup or '')[:8]}; `git reset --hard {(backup or '')[:8]}` in the project folder brings it back.")

    def on_kill(self) -> None:
        """Kill switch: stop every coding run and preview server (pending file changes stay staged; nothing is lost)."""
        for r in list(self.runs.values()):
            if r.active:
                r.cancel.set()
        self.preview.stop_all()

    # ------------------------------------------------------------------ open in editor
    def open_in_vscode(self, name: str) -> str:
        p = self.project_path(name)
        exe = find_vscode()
        if not exe:
            raise VibeError("VS Code's `code` command was not found. Install VS Code (and tick “Add to PATH”), or open the folder yourself: " + str(p))
        import subprocess
        ad = self.ctx.adapter
        if not getattr(ad, "is_real", False):
            ad._rec("open_in_vscode", [exe, str(p)]) if hasattr(ad, "_rec") else None
            return f"[demo] would open {p} in VS Code"
        try:
            subprocess.Popen([exe, str(p)], shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise VibeError(f"could not start VS Code: {e}")
        return f"Opened {p} in VS Code."
