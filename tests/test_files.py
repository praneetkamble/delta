import os
import time

import pytest

from delta.skills import files


def old(p, days=2):
    t = time.time() - days * 86400
    os.utime(p, (t, t))
    return p


def test_search_files_by_substring_and_glob(eng, home):
    (home / "Documents" / "Invoice-March.pdf").write_text("x")
    (home / "Downloads" / "invoice-april.pdf").write_text("x")
    (home / "Downloads" / "photo.png").write_text("x")
    r = eng.execute("search_files", {"query": "invoice"})
    assert r.status == "ok" and len(r.data["results"]) == 2
    r = eng.execute("search_files", {"query": "*.png", "folder": "downloads"})
    assert [os.path.basename(x) for x in r.data["results"]] == ["photo.png"]


def test_search_cannot_leave_the_sandbox(eng, tmp_path):
    (tmp_path / "secret.txt").write_text("x")
    r = eng.execute("search_files", {"query": "secret", "folder": str(tmp_path)})
    assert r.status == "blocked"


def test_move_never_overwrites(eng, home):
    (home / "Downloads" / "a.txt").write_text("new")
    (home / "Documents" / "a.txt").write_text("precious")
    r = eng.execute("move_path", {"source": "a.txt", "destination": "documents"})
    assert r.status == "ok"
    assert (home / "Documents" / "a.txt").read_text() == "precious"
    assert (home / "Documents" / "a (1).txt").read_text() == "new"
    assert not (home / "Downloads" / "a.txt").exists()


def test_move_outside_sandbox_is_blocked_and_audited(eng, ctx, home, tmp_path):
    (home / "Downloads" / "a.txt").write_text("x")
    r = eng.execute("move_path", {"source": "a.txt", "destination": str(tmp_path)})
    assert r.status == "blocked" and (home / "Downloads" / "a.txt").exists()
    assert any(e["event"] == "sandbox_violation" for e in ctx.audit.tail(10))


def test_cannot_move_a_folder_into_itself(eng, home):
    (home / "Documents" / "proj" / "sub").mkdir(parents=True)
    r = eng.execute("move_path", {"source": "proj", "destination": str(home / "Documents" / "proj" / "sub")})
    assert r.status == "error"


def test_copy_file_and_folder(eng, home):
    (home / "Downloads" / "d").mkdir()
    (home / "Downloads" / "d" / "x.txt").write_text("1")
    (home / "Downloads" / "f.txt").write_text("2")
    assert eng.execute("copy_path", {"source": "d", "destination": "documents"}).status == "ok"
    assert eng.execute("copy_path", {"source": "f.txt", "destination": "documents"}).status == "ok"
    assert (home / "Documents" / "d" / "x.txt").exists() and (home / "Downloads" / "f.txt").exists()


def test_create_folder(eng, home):
    r = eng.execute("create_folder", {"name": "Taxes 2026", "parent": "documents"})
    assert r.status == "ok" and (home / "Documents" / "Taxes 2026").is_dir()
    assert eng.execute("create_folder", {"name": "../escape", "parent": "documents"}).status == "blocked"


def test_organize_downloads_plan_and_run(eng, home):
    d = home / "Downloads"
    for n in ("pic.jpg", "song.mp3", "doc.pdf", "setup.exe", "weird.xyz", "partial.crdownload"):
        (d / n).write_text("x")
        old(d / n)
    (d / "fresh.pdf").write_text("x")  # modified just now: probably still downloading, must be skipped
    (d / "keepdir").mkdir()
    r = eng.execute("organize_downloads")
    assert r.status == "pending" and "Images (1)" in r.text and "Audio (1)" in r.text
    assert (d / "pic.jpg").exists()                    # nothing moved yet
    res = eng.resolve(r.pending_id, True)
    assert res.status == "ok"
    assert (d / "Images" / "pic.jpg").exists() and (d / "Audio" / "song.mp3").exists()
    assert (d / "Documents" / "doc.pdf").exists() and (d / "Installers" / "setup.exe").exists() and (d / "Other" / "weird.xyz").exists()
    assert (d / "fresh.pdf").exists() and (d / "partial.crdownload").exists() and (d / "keepdir").is_dir()


def test_organize_second_run_is_noop(eng, home):
    d = home / "Downloads"
    (d / "a.png").write_text("x")
    old(d / "a.png")
    eng.resolve(eng.execute("organize_downloads").pending_id, True)
    r = eng.execute("organize_downloads")
    eng.resolve(r.pending_id, True)
    assert (d / "Images" / "a.png").exists()


def test_find_duplicates_reports_but_never_deletes(eng, home):
    d = home / "Downloads"
    (d / "a.bin").write_bytes(b"A" * 5000)
    (d / "copy of a.bin").write_bytes(b"A" * 5000)
    (d / "b.bin").write_bytes(b"B" * 5000)       # same size, different content
    (d / "tiny1.txt").write_text("x")
    (d / "tiny2.txt").write_text("x")           # below the 1 KB floor
    r = eng.execute("find_duplicates", {"folder": "downloads"})
    assert len(r.data["groups"]) == 1 and len(r.data["groups"][0]) == 2
    assert all((d / n).exists() for n in ("a.bin", "copy of a.bin", "b.bin"))


def test_delete_goes_to_trash_only_after_confirmation(eng, home, adapter, tmp_path):
    f = home / "Documents" / "old-report.pdf"
    f.write_text("data")
    r = eng.handle_message("delete old-report.pdf")
    assert r.results[0].status == "pending" and f.exists()
    r2 = eng.handle_message("yes")
    assert r2.results[0].status == "ok"
    assert not f.exists() and (tmp_path / "trash" / "old-report.pdf").exists()
    assert ("trash", str(f)) in adapter.calls


def test_delete_denied_keeps_file(eng, home):
    f = home / "Documents" / "keep.txt"
    f.write_text("x")
    eng.handle_message("delete keep.txt")
    eng.handle_message("no")
    assert f.exists() and not eng.pending


def test_delete_allowed_root_or_outside_is_refused(eng, home, tmp_path):
    r = eng.execute("delete_path", {"path": "downloads"})      # an allowed folder itself
    assert r.status == "pending"
    assert eng.resolve(r.pending_id, True).status == "blocked"  # ...is refused even after a "yes"
    assert (home / "Downloads").exists()
    (tmp_path / "outside.txt").write_text("x")
    assert eng.execute("delete_path", {"path": str(tmp_path / "outside.txt")}).status == "blocked"
    assert (tmp_path / "outside.txt").exists()


def test_read_file_only_text_types(eng, home):
    (home / "Documents" / "n.txt").write_text("hello")
    (home / "Documents" / "p.pdf").write_bytes(b"%PDF")
    r = eng.execute("read_file", {"path": "n.txt"})
    assert r.status == "ok" and r.untrusted and r.text == "hello"
    assert eng.execute("read_file", {"path": "p.pdf"}).status == "error"


def test_unique_path(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "a (1).txt").write_text("1")
    assert files.unique_path(tmp_path / "a.txt").name == "a (2).txt"
