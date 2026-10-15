import ntpath
import os

import pytest

from delta.safety import Sandbox, SandboxError, is_within


@pytest.fixture
def sb(home):
    return Sandbox([home / "Downloads", home / "Documents"])


def test_inside_paths_resolve(sb, home):
    (home / "Downloads" / "a.txt").write_text("x")
    assert sb.resolve(str(home / "Downloads" / "a.txt")) == (home / "Downloads" / "a.txt").resolve()
    assert sb.resolve("a.txt") == (home / "Downloads" / "a.txt").resolve()      # relative -> found in an allowed folder
    assert sb.resolve("downloads") == (home / "Downloads").resolve()              # folder alias
    assert sb.resolve("new-file.txt").parent == (home / "Downloads").resolve()    # relative, not existing yet -> default dir


@pytest.mark.parametrize("bad", [
    "../outside.txt", "../../etc/passwd", "sub/../../escape.txt", "/etc/passwd", "/", "~/.ssh/id_rsa", "~",
    "", "   ", "foo\x00bar", "C:\\Windows\\System32\\cmd.exe", "\\\\server\\share\\x",
])
def test_escape_attempts_are_refused(sb, bad):
    with pytest.raises(SandboxError):
        sb.resolve(bad)


def test_sibling_folder_with_same_prefix_is_refused(sb, home):
    (home / "Downloads-evil").mkdir()
    with pytest.raises(SandboxError):
        sb.resolve(str(home / "Downloads-evil" / "x.txt"))


def test_symlink_escape_is_refused(sb, home, tmp_path):
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "pw.txt").write_text("hunter2")
    link = home / "Downloads" / "shortcut"
    try:
        os.symlink(secret, link)
    except OSError:
        pytest.skip("symlinks not available")
    with pytest.raises(SandboxError):
        sb.resolve(str(link / "pw.txt"))
    with pytest.raises(SandboxError):
        sb.resolve("shortcut/pw.txt")


def test_env_vars_are_not_expanded(sb, home, monkeypatch):
    monkeypatch.setenv("EVIL", "/etc")
    p = sb.resolve("$EVIL/passwd")
    assert str(p).startswith(str((home / "Downloads").resolve()))   # treated as a literal file name
    assert "$EVIL" in str(p)


def test_allowed_roots_cannot_be_modified(sb, home):
    with pytest.raises(SandboxError):
        sb.check_not_root(sb.resolve("downloads"))


@pytest.mark.parametrize("base,target,expected", [
    (r"C:\Users\Praneet\Downloads", r"C:\Users\Praneet\Downloads\a.zip", True),
    (r"C:\Users\Praneet\Downloads", r"c:\users\praneet\DOWNLOADS\sub\a.zip", True),       # Windows is case-insensitive
    (r"C:\Users\Praneet\Downloads", r"C:\Users\Praneet\Downloads\..\Documents\a.zip", False),
    (r"C:\Users\Praneet\Downloads", r"C:\Users\Praneet\Downloads2\a.zip", False),
    (r"C:\Users\Praneet\Downloads", r"D:\Users\Praneet\Downloads\a.zip", False),
    (r"C:\Users\Praneet\Downloads", r"\\server\share\a.zip", False),
    (r"C:\Users\Praneet\Downloads", r"C:\Windows\System32", False),
    (r"C:\Users\Praneet\Downloads", r"C:\Users\Praneet\Downloads", True),
])
def test_windows_path_rules_with_ntpath(base, target, expected):
    assert is_within(base, target, ntpath) is expected


def test_empty_allowed_list_refuses_relative(tmp_path):
    with pytest.raises(SandboxError):
        Sandbox([]).resolve("x.txt")
