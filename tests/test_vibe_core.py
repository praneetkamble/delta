"""Vibe Coding: path jail, project names, command classification, diffs/patches, git safety net, staged changes."""
import ntpath
import os
import subprocess
import sys
from pathlib import Path

import pytest

from delta.registry import Level
from delta.vibe import gitops, templates
from delta.vibe.commands import (CommandError, classify, clean_env, find_vscode, is_long_running, resolve_argv, start_job, tokenize)
from delta.vibe.difftools import PatchError, apply_file_patch, count_changes, make_diff, parse_patch
from delta.vibe.manager import Run
from delta.vibe.pathsafe import (VibeError, check_project_name, clean_rel, default_projects_root, lang_of, resolve_in, resolve_root)

from vibe_helpers import make_vibe_ctx, wait_for

pytestmark = pytest.mark.skipif(gitops.find_git() is None, reason="git is required for the Vibe Coding tests")


# ------------------------------------------------------------------------------------------------ path jail
@pytest.mark.parametrize("bad", ["../x", "..\\x", "a/../../x", "/etc/passwd", "C:\\Windows\\win.ini", "c:/x", "\\\\server\\share\\f", "//server/share",
                                 "~/x", ".git/config", "sub/.git/hooks/pre-commit", "a:b.txt", "file.txt:stream", "con.txt", "NUL", "aux", "x.", "dir /b.txt",
                                 "a\x00b", "", "   ", ".", "src/<x>.js", "a/COM1.txt", "bad|name"])
def test_clean_rel_rejects_escapes_and_windows_traps(bad):
    with pytest.raises(VibeError):
        clean_rel(bad)


@pytest.mark.parametrize("good,expect", [("src/app.js", "src/app.js"), ("a\\b.txt", "a/b.txt"), ("./x/./y.py", "x/y.py"), (".gitignore", ".gitignore"),
                                         ("my file.txt", "my file.txt"), ("D/e.txt", "D/e.txt")])
def test_clean_rel_accepts_normal_paths(good, expect):
    assert clean_rel(good) == expect


def test_clean_rel_write_rules():
    for bad in ("node_modules/x/y.js", "dist/a.js", ".venv/bin/python", "__pycache__/x.pyc"):
        with pytest.raises(VibeError):
            clean_rel(bad, for_write=True)
    assert clean_rel("src/dist.js", for_write=True) == "src/dist.js"


def test_resolve_in_blocks_symlink_and_junction_escape(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    try:
        os.symlink(outside, proj / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(VibeError):
        resolve_in(proj, "link/secret.txt")
    with pytest.raises(VibeError):
        resolve_in(proj, "link/new.txt", for_write=True)
    (proj / "ok.txt").write_text("x")
    assert resolve_in(proj, "ok.txt")[1] == "ok.txt"


def test_resolve_in_never_returns_the_project_root_itself(tmp_path):
    with pytest.raises(VibeError):
        resolve_in(tmp_path, "sub/..")


@pytest.mark.parametrize("name", ["", "a/b", "..", ".hidden", "-x", "a" * 65, "a b", "CON", "nul.txt", "com1", "x.", "ünï", "a\\b"])
def test_project_names_are_validated(name):
    with pytest.raises(VibeError):
        check_project_name(name)


@pytest.mark.parametrize("name", ["cafe-site", "My_App.2", "a", "todo2026"])
def test_good_project_names(name):
    assert check_project_name(name) == name


def test_default_root_per_platform():
    assert default_projects_root("win32") == "D:/Vibe"
    assert default_projects_root("linux") == "~/DeltaProjects" and default_projects_root("darwin") == "~/DeltaProjects"


def test_windows_drive_paths_are_judged_with_ntpath_rules():
    from delta.safety import is_within
    assert is_within("D:/Vibe", "D:/Vibe/app", ntpath) and is_within("D:/", "d:\\vibe\\app", ntpath)
    assert not is_within("D:/Vibe", "D:/Vibe-evil/app", ntpath) and not is_within("D:/Vibe", "C:/Vibe/app", ntpath)


def test_root_outside_allowed_folders_is_refused(tmp_path):
    ctx = make_vibe_ctx(tmp_path, projects_root=str(tmp_path / "elsewhere"))
    root, problem = resolve_root(ctx)
    assert root is None and "allowed_folders" in problem
    assert ctx.vibe.status()["ready"] is False
    with pytest.raises(VibeError):
        ctx.vibe.create_project("x", "static")
    r = ctx.engine.execute("vibe_create_project", {"name": "x", "template": "static"})
    assert r.status == "error" and "allowed_folders" in r.text
    assert not (tmp_path / "elsewhere").exists()


def test_root_equal_to_or_inside_an_allowed_folder_is_accepted(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    root, problem = resolve_root(ctx)
    assert root is not None and not problem
    assert ctx.vibe.status()["ready"]


def test_lang_detection():
    assert lang_of("a/b.py") == "python" and lang_of("x.jsx") == "js" and lang_of("package.json") == "json" and lang_of(".gitignore") == "text"


# ------------------------------------------------------------------------------------------------ commands
WL = ["npm install", "npm run dev", "pip install -r requirements.txt", "python -m pytest*", "python *.py", "node *.js", "git status*", "git add *", "git commit *"]
BL = [r"\brm\b", r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\b", r"\bdel\b", r"\bgit\s+push\b.*(--force|-f\b)"]


@pytest.mark.parametrize("cmd,level", [
    ("npm install", Level.SAFE), ("NPM   Install", Level.SAFE), ("python main.py", Level.SAFE), ("python app/tool.py", Level.SAFE), ("python app/tool.py --x 1", Level.CONFIRM),
    ("python -m pytest -q", Level.SAFE), ("git status", Level.SAFE), ("git commit -m \"first version\"", Level.SAFE), ("node server.js", Level.SAFE),
    ("npm install lodash", Level.CONFIRM), ("pip install requests", Level.CONFIRM), ("curl https://example.com", Level.CONFIRM),
    ("python -c \"print(1)\" x.py", Level.CONFIRM), ("python -m pip install requests", Level.CONFIRM), ("node -e 1; x.js", Level.BLOCKED),
    ("python ../other/x.py", Level.CONFIRM), ("python C:/Users/me/x.py", Level.CONFIRM), ("python /tmp/x.py", Level.CONFIRM),
    ("git add ..\\other", Level.CONFIRM), ("tools\\run.exe", Level.CONFIRM),
    ("rm -rf .", Level.BLOCKED), ("rm file.txt", Level.BLOCKED), ("del file.txt", Level.BLOCKED), ("git reset --hard HEAD~1", Level.BLOCKED),
    ("git clean -fd", Level.BLOCKED), ("git push origin main --force", Level.BLOCKED), ("npm install && npm run dev", Level.BLOCKED),
    ("npm install | tee log", Level.BLOCKED), ("python main.py > out.txt", Level.BLOCKED), ("echo %USERPROFILE%", Level.BLOCKED),
    ("echo $(whoami)", Level.BLOCKED), ("python main.py; rm x", Level.BLOCKED), ("cmd /c dir", Level.BLOCKED), ("powershell -Command ls", Level.BLOCKED),
    ("bash -c ls", Level.BLOCKED), ("", Level.BLOCKED), ("   ", Level.BLOCKED), ("python 'unclosed", Level.BLOCKED), ("x" * 600, Level.BLOCKED),
])
def test_classify_commands(cmd, level):
    assert classify(cmd, WL, BL)[0] == level, cmd


def test_classify_always_includes_a_reason():
    assert classify("npm install lodash", WL, BL)[1]
    assert "whitelist" in classify("npm install", WL, BL)[1]


@pytest.mark.parametrize("cmd,yes", [("npm run dev", True), ("npm start", True), ("python -m uvicorn main:app", True), ("uvicorn main:app", True),
                                     ("python -m http.server 8000", True), ("npx vite", True), ("npm run build", False), ("python main.py", False),
                                     ("pytest", False)])
def test_long_running_servers_are_recognised(cmd, yes):
    assert is_long_running(cmd) is yes


def test_tokenizer():
    assert tokenize('git commit -m "first version"') == ["git", "commit", "-m", "first version"]
    assert tokenize("a   'b c'  d") == ["a", "b c", "d"] and tokenize('x ""') == ["x", ""]
    with pytest.raises(CommandError):
        tokenize('a "b')


def test_clean_env_removes_the_llm_key(monkeypatch):
    monkeypatch.setenv("DELTA_LLM_API_KEY", "gsk_supersecret")
    monkeypatch.setenv("MY_OTHER_KEY_NAME", "also-secret")
    env = clean_env(["MY_OTHER_KEY_NAME"], {"PORT": "1234"})
    assert "DELTA_LLM_API_KEY" not in env and "MY_OTHER_KEY_NAME" not in env and env["PORT"] == "1234"
    assert env["NO_COLOR"] == "1" and env["CI"] == "1"


def test_resolve_argv_prefers_project_venv_python(tmp_path):
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    vpy = tmp_path / ".venv" / "bin" / "python"
    vpy.write_text("")
    (tmp_path / ".venv" / "Scripts" / "python.exe").write_text("")
    argv = resolve_argv(["python", "main.py", "--x"], tmp_path)
    assert argv[0].endswith(("python", "python.exe")) and ".venv" in argv[0] and argv[1:] == ["main.py", "--x"]
    assert resolve_argv(["pip", "install", "-r", "requirements.txt"], tmp_path)[1:3] == ["-m", "pip"]
    assert resolve_argv(["pytest", "-q"], tmp_path)[1:3] == ["-m", "pytest"]
    assert resolve_argv(["py", "-3", "main.py"], tmp_path)[1:] == ["main.py"]


def test_npm_cmd_shims_on_windows_refuse_cmd_metacharacters(monkeypatch):
    import delta.vibe.commands as c
    monkeypatch.setattr(c, "find_node_tool", lambda name: r"C:\Program Files\nodejs\npm.cmd")
    assert resolve_argv(["npm", "run", "build"], Path("."))[0].endswith("npm.cmd")
    for bad in ("a&b", "x|y", "x>y", "50%", 'q"q', "a^b"):
        with pytest.raises(CommandError):
            resolve_argv(["npm", "install", bad], Path("."))


def test_missing_tools_give_helpful_messages(monkeypatch):
    import delta.vibe.commands as c
    monkeypatch.setattr(c, "find_node_tool", lambda name: None)
    with pytest.raises(CommandError, match="nodejs.org"):
        resolve_argv(["npm", "install"], Path("."))
    monkeypatch.setattr(gitops, "find_git", lambda: None)
    with pytest.raises(CommandError, match="git was not found"):
        resolve_argv(["git", "status"], Path("."))
    with pytest.raises(CommandError, match="not found on PATH"):
        resolve_argv(["definitely-not-a-program-xyz"], Path("."))


def test_find_vscode_prefers_code_exe_next_to_code_cmd(tmp_path, monkeypatch):
    import delta.vibe.commands as c
    install = tmp_path / "Microsoft VS Code"
    (install / "bin").mkdir(parents=True)
    (install / "bin" / "code.cmd").write_text("")
    (install / "Code.exe").write_text("")
    c._cache.pop("code", None)
    monkeypatch.setattr(c.shutil, "which", lambda n: str(install / "bin" / "code.cmd") if n == "code" else None)
    assert find_vscode() == str(install / "Code.exe")
    c._cache.pop("code", None)
    monkeypatch.setattr(c.shutil, "which", lambda n: None)
    monkeypatch.setattr(c.sys, "platform", "linux")
    assert find_vscode() is None
    c._cache.pop("code", None)


def test_start_job_captures_output_exit_code_and_times_out(tmp_path):
    job = start_job([sys.executable, "-c", "print('hello'); import sys; print('err', file=sys.stderr); sys.exit(3)"], str(tmp_path), dict(os.environ), 20)
    wait_for(lambda: job.done)
    assert job.rc == 3 and "hello" in job.text() and "err" in job.text()
    slow = start_job([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), dict(os.environ), 1)
    wait_for(lambda: slow.done, 15)
    assert slow.timed_out and slow.rc != 0
    missing = start_job(["/definitely/not/here"], str(tmp_path), dict(os.environ), 5)
    assert missing.done and "could not start" in missing.error and missing.rc == -1


# ------------------------------------------------------------------------------------------------ diffs and patches
def test_make_diff_for_create_modify_delete():
    d = make_diff("a.txt", "one\ntwo\n", "one\nTWO\n")
    assert d.startswith("--- a/a.txt\n+++ b/a.txt\n") and "-two" in d and "+TWO" in d and count_changes(d) == (1, 1)
    c = make_diff("n.txt", None, "x\ny\n")
    assert c.startswith("--- /dev/null\n+++ b/n.txt") and count_changes(c) == (2, 0)
    x = make_diff("n.txt", "x\ny\n", None)
    assert "+++ /dev/null" in x and count_changes(x) == (0, 2)
    assert make_diff("same.txt", "a\n", "a\n") == ""


SRC = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n"


def _patch(text):
    (fp,) = parse_patch(text)
    return fp


def test_apply_patch_basic_and_wrong_line_numbers():
    p = "--- a/f.txt\n+++ b/f.txt\n@@ -3,3 +3,3 @@\n line3\n-line4\n+LINE4\n line5\n"
    assert apply_file_patch(SRC, _patch(p)) == SRC.replace("line4", "LINE4")
    off = "--- a/f.txt\n+++ b/f.txt\n@@ -90,3 +90,3 @@\n line3\n-line4\n+LINE4\n line5\n"          # hint is way off: still found
    assert apply_file_patch(SRC, _patch(off)) == SRC.replace("line4", "LINE4")


def test_apply_patch_multiple_hunks_and_growth():
    p = ("--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,3 @@\n line1\n+inserted\n line2\n@@ -7,2 +8,2 @@\n line7\n-line8\n+last\n")
    assert apply_file_patch(SRC, _patch(p)) == "line1\ninserted\nline2\nline3\nline4\nline5\nline6\nline7\nlast\n"


def test_apply_patch_tolerates_whitespace_and_blank_context_lines():
    src = "a\n    b\n\nc\n"
    p = "--- a/f\n+++ b/f\n@@ -1,4 +1,4 @@\n a\n b\n\n-c\n+C\n"      # LLM lost indentation + blank context line has no leading space
    assert apply_file_patch(src, _patch(p)) == "a\n    b\n\nC\n" or apply_file_patch(src, _patch(p)).endswith("C\n")


def test_apply_patch_context_mismatch_is_a_clear_error():
    p = "--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n nothere\n-nope\n+yes\n"
    with pytest.raises(PatchError, match="does not match"):
        apply_file_patch(SRC, _patch(p))


def test_apply_patch_create_and_delete_and_crlf():
    (fp,) = parse_patch("--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+hello\n+world\n")
    assert fp.old_path is None and apply_file_patch(None, fp) == "hello\nworld\n"
    (fp,) = parse_patch("--- a/f.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-x\n-y\n")
    assert fp.new_path is None
    crlf = "a\r\nb\r\nc\r\n"
    p = "--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
    assert apply_file_patch(crlf, _patch(p)) == "a\r\nB\r\nc\r\n"


def test_parse_patch_rejects_garbage():
    with pytest.raises(PatchError):
        parse_patch("just some text")
    with pytest.raises(PatchError):
        parse_patch("--- a/x\n+++ b/x\nno hunks here\n")


# ------------------------------------------------------------------------------------------------ git safety net
def test_git_snapshot_undo_roundtrip(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "a.txt").write_text("v1")
    s1 = gitops.snapshot(p, "first")
    assert gitops.is_repo(p) and (p / ".gitignore").exists() and s1
    assert gitops.snapshot(p, "clean tree reuses HEAD") == s1                              # no empty commit
    (p / "a.txt").write_text("v2")
    (p / "new.txt").write_text("n")
    s2 = gitops.snapshot(p, "second")
    assert s2 != s1
    gitops.reset_hard(p, s1)
    assert (p / "a.txt").read_text() == "v1" and not (p / "new.txt").exists()
    with pytest.raises(gitops.GitError):
        gitops.reset_hard(p, "not-a-sha")
    with pytest.raises(gitops.GitError):
        gitops.reset_hard(p, "--hard")


def test_git_ignores_node_modules_even_if_gitignore_exists(tmp_path):
    p = tmp_path / "p"
    (p / "node_modules" / "dep").mkdir(parents=True)
    (p / "node_modules" / "dep" / "i.js").write_text("x")
    (p / ".gitignore").write_text("dist/\n")
    (p / "app.js").write_text("1")
    gitops.snapshot(p, "s")
    tracked = gitops.git(p, "ls-files").splitlines()
    assert "app.js" in tracked and not any(t.startswith("node_modules") for t in tracked)
    assert "dist/" in (p / ".gitignore").read_text() and "node_modules/" in (p / ".gitignore").read_text()


def test_git_commit_if_dirty_and_log(tmp_path):
    p = tmp_path / "p"
    p.mkdir()
    (p / "a").write_text("1")
    gitops.snapshot(p, "init")
    assert gitops.commit_if_dirty(p, "nothing") is None
    (p / "a").write_text("2")
    assert gitops.commit_if_dirty(p, "change") and gitops.log(p)[0]["subject"] == "change"
    assert gitops.branch(p)


# ------------------------------------------------------------------------------------------------ projects + templates
@pytest.mark.parametrize("key", list(templates.TEMPLATES))
def test_every_template_creates_a_committed_project(tmp_path, key):
    ctx = make_vibe_ctx(tmp_path)
    info = ctx.vibe.create_project("demo-app", key)
    p = Path(info["path"])
    assert info["git"] and (p / ".git").exists() and p.parent.name == "Projects"
    for rel in templates.TEMPLATES[key]["files"]:
        assert (p / rel).is_file()
    assert "{{" not in "".join((p / r).read_text() for r in templates.TEMPLATES[key]["files"])
    assert gitops.log(p)[0]["subject"].startswith("Delta: new")
    assert ctx.vibe.state("demo-app")["template"] == key
    assert any(x["name"] == "demo-app" for x in ctx.vibe.list_projects())


def test_template_kinds_are_detected(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    want = {"static": "static", "react-vite": "react-vite", "fastapi": "fastapi", "express": "express", "python-script": "python-script", "blank": "blank"}
    for key, kind in want.items():
        info = ctx.vibe.create_project("p-" + key, key)
        assert ctx.vibe.detect_kind(Path(info["path"])) == kind


def test_create_project_rejects_duplicates_bad_names_and_unknown_templates(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    ctx.vibe.create_project("one", "static")
    with pytest.raises(VibeError, match="already exists"):
        ctx.vibe.create_project("one", "static")
    for bad in ("../evil", "a/b", "con"):
        with pytest.raises(VibeError):
            ctx.vibe.create_project(bad, "static")
    with pytest.raises(VibeError, match="Unknown template"):
        ctx.vibe.create_project("two", "cobol")
    assert not (tmp_path / "home" / "evil").exists()


def test_project_path_refuses_names_that_escape_the_root(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    for bad in ("..", "../x", "Documents", "a/../..", ""):
        with pytest.raises(VibeError):
            ctx.vibe.project_path(bad)


def test_tree_hides_junk_and_marks_staged_files(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    ctx.vibe.create_project("t", "static")
    p = ctx.vibe.project_path("t")
    (p / "node_modules" / "x").mkdir(parents=True)
    (p / "node_modules" / "x" / "i.js").write_text("1")
    (p / ".env").write_text("A=1")
    run = Run("t", "x")
    run.status = "running"
    ctx.vibe.stage(run, "new/page.html", "<p>hi</p>")
    paths = [e["path"] for e in ctx.vibe.tree("t")]
    assert "index.html" in paths and "new/page.html" in paths
    assert not any("node_modules" in x or x == ".env" or ".git/" in x for x in paths)
    assert next(e for e in ctx.vibe.tree("t") if e["path"] == "new/page.html")["staged"]


def test_read_for_view_limits(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    ctx.vibe.create_project("v", "static")
    p = ctx.vibe.project_path("v")
    (p / "blob.bin").write_bytes(b"\x00\x01\x02" * 100)
    assert ctx.vibe.read_for_view("v", "blob.bin")["binary"] is True
    assert "<h1>" in ctx.vibe.read_for_view("v", "index.html")["text"]
    for bad in (".git/config", "../x", "/etc/passwd", "C:\\Windows\\win.ini"):
        with pytest.raises(VibeError):
            ctx.vibe.read_for_view("v", bad)
    with pytest.raises(VibeError):
        ctx.vibe.read_for_view("v", "nope.txt")


# ------------------------------------------------------------------------------------------------ staged changes (review-before-apply)
@pytest.fixture
def vm(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    ctx.vibe.create_project("site", "static")
    run = Run("site", "test")
    run.status = "running"
    ctx.vibe.runs[run.id] = run
    return ctx, ctx.vibe, run, ctx.vibe.project_path("site")


def test_stage_does_not_touch_disk_until_accepted(vm):
    ctx, m, run, p = vm
    before = (p / "style.css").read_text()
    ch = m.stage(run, "style.css", before + "\nbody { color: red; }\n")
    assert ch.op == "modify" and ch.status == "pending" and "+body { color: red; }" in ch.diff and ch.added == 2
    assert (p / "style.css").read_text() == before                      # not applied
    assert m.current_text("site", "style.css").endswith("red; }\n")      # the agent sees its staged version
    m.accept(ch.id)
    assert (p / "style.css").read_text().endswith("red; }\n") and ch.status == "accepted" and not m.pending_ids("site")


def test_reject_leaves_the_file_alone_and_tells_the_agent(vm):
    ctx, m, run, p = vm
    ch = m.stage(run, "new.html", "<p>x</p>")
    assert ch.op == "create"
    m.reject(ch.id)
    assert not (p / "new.html").exists() and ch.status == "rejected" and any("REJECTED" in n and "new.html" in n for n in run.notices)
    with pytest.raises(VibeError, match="not waiting"):
        m.accept(ch.id)


def test_two_writes_to_one_file_collapse_into_one_diff_against_the_original(vm):
    ctx, m, run, p = vm
    orig = (p / "script.js").read_text()
    a = m.stage(run, "script.js", "one\n")
    b = m.stage(run, "script.js", "two\n")
    assert len(m.pending_ids("site")) == 1 and a.id not in m.changes and b.old == orig and "+two" in b.diff and "+one" not in b.diff


def test_writing_the_same_content_stages_nothing(vm):
    ctx, m, run, p = vm
    assert m.stage(run, "script.js", (p / "script.js").read_text()) is None and not m.pending_ids("site")
    ch = m.stage(run, "script.js", "x\n")
    assert m.stage(run, "script.js", (p / "script.js").read_text()) is None and ch.status == "rejected" and not m.pending_ids("site")


def test_delete_flow_and_create_then_delete(vm):
    ctx, m, run, p = vm
    d = m.stage(run, "script.js", None)
    assert d.op == "delete" and "+++ /dev/null" in d.diff and (p / "script.js").exists()
    m.accept(d.id)
    assert not (p / "script.js").exists()
    n = m.stage(run, "tmp.txt", "x")
    assert m.stage(run, "tmp.txt", None) is None and not m.pending_ids("site")
    with pytest.raises(VibeError, match="does not exist"):
        m.stage(run, "ghost.txt", None)


def test_accept_detects_a_file_that_changed_on_disk_meanwhile(vm):
    ctx, m, run, p = vm
    ch = m.stage(run, "style.css", "body{}\n")
    (p / "style.css").write_text("someone else edited this\n")
    with pytest.raises(VibeError, match="changed on disk"):
        m.accept(ch.id)
    assert ch.status == "failed" and (p / "style.css").read_text() == "someone else edited this\n"


def test_stage_refuses_escapes_binary_and_size(vm):
    ctx, m, run, p = vm
    for bad in ("../outside.txt", "/tmp/x", "C:\\x.txt", ".git/config", "node_modules/x/a.js", "a/../../b"):
        with pytest.raises(VibeError):
            m.stage(run, bad, "x")
    (p / "pic.bin").write_bytes(b"\x00\x01" * 50)
    with pytest.raises(VibeError, match="binary"):
        m.stage(run, "pic.bin", "text")
    with pytest.raises(VibeError, match="too large"):
        m.stage(run, "big.txt", "x" * 500_000)
    with pytest.raises(VibeError, match="is a folder"):
        (p / "sub").mkdir()
        m.stage(run, "sub", "x")
    assert not (tmp_outside := p.parent / "outside.txt").exists()


def test_patch_staging_is_all_or_nothing(vm):
    ctx, m, run, p = vm
    good = "--- a/style.css\n+++ b/style.css\n@@ -1,1 +1,1 @@\n-:root { --bg: #0e1116; --ink: #e8eef2; --accent: #4fd6f2; --muted: #93a4ae; }\n+:root { --bg: #000; --ink: #e8eef2; --accent: #4fd6f2; --muted: #93a4ae; }\n"
    bad = "--- a/script.js\n+++ b/script.js\n@@ -1,1 +1,1 @@\n-this line does not exist\n+x\n"
    with pytest.raises(PatchError):
        m.stage_patch(run, good + bad)
    assert not m.pending_ids("site")
    (ch,) = m.stage_patch(run, good)
    assert "--bg: #000" in ch.diff
    with pytest.raises(PatchError, match="already exists"):
        m.stage_patch(run, "--- /dev/null\n+++ b/index.html\n@@ -0,0 +1,1 @@\n+x\n")


def test_run_change_limit(tmp_path):
    ctx = make_vibe_ctx(tmp_path, max_changes_per_run=3)
    ctx.vibe.create_project("lim", "blank")
    run = Run("lim", "x")
    run.status = "running"
    for i in range(3):
        ctx.vibe.stage(run, f"f{i}.txt", "x")
    with pytest.raises(VibeError, match="too many"):
        ctx.vibe.stage(run, "f9.txt", "x")


# ------------------------------------------------------------------------------------------------ gate integration
def test_vibe_tools_are_hidden_from_the_chat_llm_and_have_valid_levels(ctx):
    names = [t.name for t in ctx.registry.all() if t.category == "vibe"]
    assert len(names) >= 12 and all(n.startswith("vibe_") for n in names)
    assert all(not ctx.registry.get(n).expose_to_llm for n in names)
    assert not any("vibe" in s["function"]["name"] for s in ctx.registry.llm_schemas())


def test_undo_and_auto_accept_enable_always_ask(tmp_path):
    ctx = make_vibe_ctx(tmp_path, )
    c = ctx
    c.config.set("safety.overrides", {"vibe_undo": "safe", "vibe_run_command": "safe", "vibe_auto_accept": "safe"})
    ctx.vibe.create_project("g", "static")
    assert c.engine.execute("vibe_undo", {"project": "g"}).status == "pending"
    assert c.engine.execute("vibe_auto_accept", {"project": "g", "enabled": True}).status == "pending"
    assert c.engine.execute("vibe_auto_accept", {"project": "g", "enabled": False}).status == "ok"


def test_blocked_tools_config_stops_vibe_writes(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    ctx.config.set("safety.blocked_tools", ["vibe_write_file", "vibe_review_change"])
    ctx.vibe.create_project("b", "static")
    run = Run("b", "x")
    run.status = "running"
    ctx.vibe.runs[run.id] = run
    assert ctx.engine.execute("vibe_write_file", {"run": run.id, "path": "a.txt", "content": "x"}).status == "blocked"
    assert not ctx.vibe.pending_ids("b")


def test_dry_run_and_kill_switch_apply_to_vibe_writes(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    ctx.vibe.create_project("d", "static")
    run = Run("d", "x")
    run.status = "running"
    ctx.vibe.runs[run.id] = run
    ctx.dry_run = True
    r = ctx.engine.execute("vibe_write_file", {"run": run.id, "path": "a.txt", "content": "x"})
    assert r.status == "dry_run" and not ctx.vibe.pending_ids("d")
    ctx.dry_run = False
    ctx.engine.kill("test")
    assert ctx.engine.execute("vibe_write_file", {"run": run.id, "path": "a.txt", "content": "x"}).status == "killed"
    assert run.cancel.is_set()


def test_tools_refuse_an_unknown_or_finished_run(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    ctx.vibe.create_project("r", "static")
    r = ctx.engine.execute("vibe_read_file", {"run": "nope", "path": "index.html"})
    assert r.status == "error" and "no active coding run" in r.text
    r = ctx.engine.execute("vibe_run_command", {"run": "nope", "command": "git status"})
    assert r.status == "blocked"


def test_read_tools_see_staged_files_and_search_works(vm):
    ctx, m, run, p = vm
    m.stage(run, "notes/todo.md", "buy MILK\nand eggs\n")
    ex = lambda tool, **a: ctx.engine.execute(tool, {"run": run.id, **a})
    out = ex("vibe_read_file", path="notes/todo.md")
    assert out.status == "ok" and "buy MILK" in out.data["text"] and "[staged version]" in out.text
    ls = ex("vibe_list_files").data["text"]
    assert "index.html" in ls and "notes/" in ls and ".git/" not in ls
    assert "notes/todo.md:1: buy MILK" in ex("vibe_search_code", query="milk").data["text"]
    assert "no matches" in ex("vibe_search_code", query="zzzz-none").data["text"]
    assert "index.html" in ex("vibe_search_code", query="re:<h1>.*</h1>", glob="*.html").data["text"]
    big = "\n".join(f"line {i}" for i in range(1000))
    m.stage(run, "big.txt", big)
    part = ex("vibe_read_file", path="big.txt", offset=401, limit=5)
    assert part.data["text"].startswith("line 400") and "lines 401-405 of 1000" in part.text
    assert ex("vibe_read_file", path="../../etc/passwd").status == "error"
    assert ex("vibe_read_file", path="missing.txt").status == "error"
