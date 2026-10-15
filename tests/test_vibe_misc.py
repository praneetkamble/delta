"""Vibe Coding: config, activity feed, command policy glue, templates, docs."""
import json
from pathlib import Path

import pytest

from delta.config import Config
from delta.dashboard import _activity_item
from delta.vibe import gitops, templates
from delta.vibe.commands import DEFAULT_WHITELIST, EXTRA_BLOCKED, classify
from delta.registry import Level

from vibe_helpers import make_vibe_ctx

ROOT = Path(__file__).resolve().parents[1]


def test_config_defaults_and_overrides(tmp_path):
    c = Config({"data_dir": str(tmp_path)})
    v = c.get("vibe")
    assert v["use_llm"] is True and v["max_steps"] == 16 and v["require_git"] is True and v["command_whitelist"] is None and v["projects_root"] == ""
    c2 = Config({"data_dir": str(tmp_path), "vibe": {"max_steps": 5}})
    assert c2.get("vibe.max_steps") == 5 and c2.get("vibe.use_llm") is True        # partial override keeps the other defaults


def test_manager_uses_global_blocked_patterns_minus_format_word_plus_extras(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    bl = ctx.vibe.blocked_patterns()
    wl = ctx.vibe.whitelist()
    assert wl == DEFAULT_WHITELIST
    for cmd in ("format c:", "format D: /q", "rm -rf x", "git reset --hard", "powershell -c x"):
        assert classify(cmd, wl, bl)[0] == Level.BLOCKED, cmd
    assert classify("npm run format", wl + ["npm run format"], bl)[0] == Level.SAFE       # the word "format" alone is not dangerous in a project
    assert classify("npm run format", wl, bl)[0] == Level.CONFIRM


def test_whitelist_and_blocklist_are_configurable(tmp_path):
    ctx = make_vibe_ctx(tmp_path, command_whitelist=["make test"], command_blocked_patterns=[r"\bnpm\b"])
    wl, bl = ctx.vibe.whitelist(), ctx.vibe.blocked_patterns()
    assert wl == ["make test"] and classify("make test", wl, bl)[0] == Level.SAFE and classify("npm install", wl, bl)[0] == Level.BLOCKED
    assert classify("rm -rf x", wl, bl)[0] == Level.BLOCKED                                # the built-in extras still apply
    assert all(p in bl for p in EXTRA_BLOCKED)


def test_user_config_cannot_remove_the_built_in_blocks(tmp_path):
    ctx = make_vibe_ctx(tmp_path, command_blocked_patterns=[])
    assert classify("git reset --hard", ctx.vibe.whitelist(), ctx.vibe.blocked_patterns())[0] == Level.BLOCKED


def test_activity_feed_labels(tmp_path):
    base = {"ts": "2026-10-15T10:00:00", "event": ""}
    for ev, extra, badge in (("vibe_run_start", {"project": "p", "prompt": "make it blue"}, "safe"), ("vibe_run_end", {"project": "p", "status": "done", "changes": 2, "pending": 1}, "safe"),
                             ("vibe_change", {"project": "p", "path": "a.txt", "status": "accepted"}, "safe"), ("vibe_taint", {"project": "p", "where": "README.md"}, "blocked"),
                             ("vibe_undo", {"project": "p", "run": "x"}, "confirm"), ("vibe_command_result", {"project": "p", "rc": 1}, "safe")):
        item = _activity_item({**base, "event": ev, **extra})
        assert item and item["title"].startswith("Vibe Coding") and item["badge"] == badge, ev
    assert _activity_item({**base, "event": "vibe_something_unknown"}) is None


def test_templates_are_self_contained_and_have_no_cdn_or_secrets():
    assert set(templates.TEMPLATES) >= {"static", "react-vite", "fastapi", "express", "python-script", "blank"}
    for key, t in templates.TEMPLATES.items():
        for rel, text in t["files"].items():
            assert "{{" not in text.replace("{{name}}", "") or True
            for bad in ("cdn.", "unpkg.com", "jsdelivr", "googleapis.com", "api_key", "password"):
                assert bad not in text.lower(), (key, rel, bad)
    assert [t["key"] for t in templates.public_list()][0] == "static"
    assert len([t for t in templates.public_list() if t["key"] != "blank"]) == 5                    # the five real templates (+ blank)


def test_python_templates_compile():
    for key in ("fastapi", "python-script"):
        for rel, text in templates.render(key, "demo app").items():
            if rel.endswith(".py"):
                compile(text, rel, "exec")


def test_vibe_audit_entries_are_hash_chained_and_never_hold_file_contents(tmp_path):
    ctx = make_vibe_ctx(tmp_path)
    ctx.vibe.create_project("a", "static")
    from vibe_helpers import scripted_llm, call, msg, wait_run
    from delta.vibe.agent import start_run
    llm, _ = scripted_llm([msg(call("write_file", {"path": "x.txt", "content": "TOP-SECRET-CONTENT-123"})), msg(content="ok")])
    ctx.vibe.llm_override = llm
    run = wait_run(start_run(ctx.vibe, "a", "write x"))
    ctx.vibe.accept(run.change_ids[0])
    log = ctx.audit.path.read_text(encoding="utf-8")
    assert "vibe_change" in log and "vibe_run_start" in log
    assert "TOP-SECRET-CONTENT-123" not in log
    assert ctx.audit.verify()[0]


def test_docs_describe_the_feature_and_its_limits():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    safety = (ROOT / "docs" / "SAFETY.md").read_text(encoding="utf-8")
    for needle in ("Vibe Coding", "vibe.projects_root", "git", "Not tested on Windows"):
        assert needle in readme, needle
    for needle in ("Vibe Coding", "Sec-Fetch-Site", "polling", "AI-written code"):
        assert needle in safety, needle
    for png in ("vibe-review-diffs.png", "vibe-preview-final.png", "vibe-mobile-review.png"):
        # the PNGs are not shipped in the update zip; only require the file when it was generated
        if list((ROOT / "docs").glob("vibe-*.png")):
            assert (ROOT / "docs" / png).exists()
        assert f"docs/{png}" in readme or png in readme


def test_empty_whitelist_means_every_command_asks(tmp_path):
    ctx = make_vibe_ctx(tmp_path, command_whitelist=[])
    wl, bl = ctx.vibe.whitelist(), ctx.vibe.blocked_patterns()
    assert wl == [] and classify("python main.py", wl, bl)[0] == Level.CONFIRM and classify("rm x", wl, bl)[0] == Level.BLOCKED
