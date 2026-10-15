import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delta.adapters.mock import MockAdapter  # noqa: E402
from delta.config import Config  # noqa: E402
from delta.context import build_context  # noqa: E402
from delta.llm import LLMClient  # noqa: E402

FIXED_NOW = datetime(2026, 10, 15, 10, 0, 0)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    for n in ("Downloads", "Documents", "Desktop", "Pictures"):
        (h / n).mkdir(parents=True)
    return h


def make_cfg(tmp_path, home, **extra):
    data = {"data_dir": str(tmp_path / "data"),
            "safety": {"allowed_folders": [str(home / n) for n in ("Downloads", "Documents", "Desktop", "Pictures")]}}
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k].update(v)
        else:
            data[k] = v
    return Config(data)


@pytest.fixture
def make_ctx(tmp_path, home):
    def _make(**extra):
        cfg = make_cfg(tmp_path, home, **extra)
        ad = MockAdapter(trash_dir=tmp_path / "trash")
        ctx = build_context(cfg, adapter=ad, llm=LLMClient("", ""))
        ctx.clock = lambda: FIXED_NOW
        ctx.sleep = lambda s: None
        return ctx
    return _make


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()


@pytest.fixture
def eng(ctx):
    return ctx.engine


@pytest.fixture
def adapter(ctx):
    return ctx.adapter


def tool_call(name, args, id="c1"):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def make_llm(script):
    """script: list of assistant message dicts (or callables(body)->dict). Returns (client, recorded_request_bodies)."""
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        item = script.pop(0) if script else {"role": "assistant", "content": "done"}
        if callable(item):
            item = item(body)
        return httpx.Response(200, json={"choices": [{"message": item}]})

    return LLMClient("http://llm.test/v1", "test-model", "key", transport=httpx.MockTransport(handler)), calls


@pytest.fixture
def llm_factory():
    return make_llm
