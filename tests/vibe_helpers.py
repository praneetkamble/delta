"""Shared helpers for the Vibe Coding tests."""
import json
import time

import httpx
import pytest

from delta.adapters.mock import MockAdapter
from delta.config import Config
from delta.context import build_context
from delta.llm import LLMClient


def call(name, args, id=None):
    return {"id": id or f"c{abs(hash((name, json.dumps(args, sort_keys=True)))) % 10**6}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def msg(*calls, content=None):
    m = {"role": "assistant", "content": content}
    if calls:
        m["tool_calls"] = list(calls)
    return m


def scripted_llm(script):
    """script: list of assistant messages (or callables(body)->message / httpx.Response). Returns (client, recorded_bodies)."""
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        item = script.pop(0) if script else {"role": "assistant", "content": "done"}
        if callable(item):
            item = item(body)
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json={"choices": [{"message": item}]})

    return LLMClient("http://llm.test/v1", "test-model", "secret-key", transport=httpx.MockTransport(handler)), bodies


def make_vibe_ctx(tmp_path, llm=None, **vibe_cfg):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    proj_root = home / "Projects"
    data = {"data_dir": str(tmp_path / "data"),
            "safety": {"allowed_folders": [str(home / "Projects"), str(home / "Documents")]},
            "vibe": {"projects_root": str(proj_root), **vibe_cfg}}
    (home / "Documents").mkdir(exist_ok=True)
    cfg = Config(data)
    ad = MockAdapter(trash_dir=tmp_path / "trash")
    ctx = build_context(cfg, adapter=ad, llm=llm or LLMClient("", ""))
    ctx.sleep = lambda s: None
    return ctx


def wait_run(run, timeout=20, until=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if (until(run) if until else not run.active):
            return run
        time.sleep(0.05)
    raise AssertionError(f"run did not finish: status={run.status} phase={run.phase} steps={[s.text[:60] for s in run.steps]}")


def wait_for(cond, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = cond()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("condition not met in time")
