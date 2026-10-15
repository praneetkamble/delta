"""Unified diffs: build one for a change, and apply an LLM-written unified diff tolerantly (line numbers are only hints)."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


def make_diff(path: str, old: str | None, new: str | None, context: int = 3) -> str:
    """Unified diff of a create (old None), modify, or delete (new None)."""
    a = (old or "").splitlines(keepends=True)
    b = (new or "").splitlines(keepends=True)
    fa = "/dev/null" if old is None else f"a/{path}"
    fb = "/dev/null" if new is None else f"b/{path}"
    lines = list(difflib.unified_diff(a, b, fa, fb, n=context))
    out = []
    for ln in lines:
        out.append(ln if ln.endswith("\n") else ln + "\n\\ No newline at end of file\n")
    return "".join(out)


def count_changes(diff: str) -> tuple[int, int]:
    add = rem = 0
    for ln in diff.splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            add += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            rem += 1
    return add, rem


class PatchError(ValueError):
    pass


@dataclass
class FilePatch:
    old_path: str | None      # None = /dev/null (create)
    new_path: str | None      # None = deleted
    hunks: list[tuple[int, list[str]]]   # (old start hint (1-based), lines each prefixed ' ', '-' or '+')

    @property
    def path(self) -> str:
        return (self.new_path or self.old_path or "").strip()


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _strip_prefix(p: str) -> str | None:
    p = p.split("\t")[0].strip()
    if p == "/dev/null":
        return None
    if p.startswith(("a/", "b/")):
        p = p[2:]
    return p.strip('"')


def parse_patch(text: str) -> list[FilePatch]:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    patches: list[FilePatch] = []
    i = 0
    cur: FilePatch | None = None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            cur = FilePatch(_strip_prefix(ln[4:]), _strip_prefix(lines[i + 1][4:]), [])
            patches.append(cur)
            i += 2
            continue
        m = _HUNK.match(ln)
        if m and cur is not None:
            start = int(m.group(1))
            body: list[str] = []
            i += 1
            while i < len(lines):
                l2 = lines[i]
                if l2.startswith("@@") or (l2.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")) or l2.startswith("diff --git"):
                    break
                if l2.startswith("\\"):   # "\ No newline at end of file"
                    i += 1
                    continue
                if l2[:1] in (" ", "+", "-"):
                    body.append(l2)
                elif l2 == "":
                    # a blank context line whose leading space was stripped by the LLM / transport; trailing blank at the very end is ignored
                    if i + 1 < len(lines) and (lines[i + 1][:1] in (" ", "+", "-") and not lines[i + 1].startswith(("--- ", "+++ "))):
                        body.append(" ")
                else:
                    break
                i += 1
            cur.hunks.append((start, body))
            continue
        i += 1
    if not patches:
        raise PatchError("no file headers found: a patch needs '--- a/path' and '+++ b/path' lines followed by '@@ -l,n +l,n @@' hunks")
    for p in patches:
        if not p.hunks:
            raise PatchError(f"no hunks found for {p.path}")
    return patches


def _find(src: list[str], old: list[str], hint: int, loose: bool) -> int:
    n = len(old)
    if n == 0:
        return max(0, min(hint, len(src)))
    norm = (lambda s: s.strip()) if loose else (lambda s: s.rstrip())
    target = [norm(x) for x in old]
    cands = [k for k in range(0, len(src) - n + 1) if [norm(x) for x in src[k:k + n]] == target]
    if not cands:
        return -1
    return min(cands, key=lambda k: abs(k - (hint - 1)))


def apply_file_patch(original: str | None, fp: FilePatch) -> str:
    """Apply the hunks of ONE file patch to `original` (None = file does not exist). Returns the new text."""
    eol = "\r\n" if original and "\r\n" in original else "\n"
    text0 = (original or "").replace("\r\n", "\n")
    src = text0.split("\n") if text0 else []
    if src and src[-1] == "":
        src.pop()
    trailing_nl = (not original) or original.endswith("\n")
    offset = 0
    for idx, (start, body) in enumerate(fp.hunks, 1):
        old = [x[1:] for x in body if x[:1] in (" ", "-")]
        new = [x[1:] for x in body if x[:1] in (" ", "+")]
        pos = _find(src, old, start + offset, loose=False)
        if pos < 0:
            pos = _find(src, old, start + offset, loose=True)
        if pos < 0:
            sample = "\n".join(old[:4])
            raise PatchError(f"hunk {idx} for {fp.path} does not match the file (the context lines were not found). "
                             f"Re-read the file and send a fresh patch, or use write_file. First lines I looked for:\n{sample}")
        src[pos:pos + len(old)] = new
        offset += len(new) - len(old)
    text = "\n".join(src)
    if trailing_nl and src:
        text += "\n"
    return text.replace("\n", eol) if eol == "\r\n" else text
