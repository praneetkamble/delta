import json

import httpx
import pytest

from delta.llm import LLMClient, LLMError

from conftest import make_llm, tool_call


def test_llm_tool_calling_happy_path(ctx, adapter, llm_factory):
    ctx.memory.add_fact("I work late on Fridays")
    ctx.llm, calls = llm_factory([tool_call("set_brightness", {"percent": "50"}), {"role": "assistant", "content": "Brightness is now 50%."}])
    r = ctx.engine.handle_message("make my screen a bit more comfortable for night reading", session="b")
    assert adapter.brightness == 50
    assert r.source == "llm" and "50%" in r.text
    first = calls[0]
    assert first["model"] == "test-model" and first["tool_choice"] == "auto"
    names = {t["function"]["name"] for t in first["tools"]}
    assert "set_brightness" in names and "gmail_unread" not in names       # stubs are never offered to the model
    assert "I work late on Fridays" in first["messages"][0]["content"]       # user facts reach the system prompt
    assert any(m["role"] == "tool" for m in calls[1]["messages"])


def test_rules_win_and_llm_is_not_called_for_known_commands(ctx, llm_factory):
    ctx.llm, calls = llm_factory([])
    ctx.engine.handle_message("volume 30")
    assert calls == []


def test_brain_mode_rules_never_calls_llm(make_ctx, llm_factory):
    c = make_ctx(brain={"mode": "rules"})
    c.llm, calls = llm_factory([{"role": "assistant", "content": "hi"}])
    c.engine.handle_message("tell me a story")
    assert calls == []


def test_llm_outage_falls_back_gracefully(ctx):
    ctx.llm = LLMClient("http://llm.test/v1", "m", transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down")))
    r = ctx.engine.handle_message("tell me a story about robots")
    assert "couldn't reach" in r.text.lower() and r.source == "system"
    assert ctx.engine.handle_message("volume 10").results[0].status == "ok"      # rule commands keep working
    assert any(e["event"] == "llm_error" for e in ctx.audit.tail(10))


def test_llm_confirm_level_calls_wait_for_the_user(ctx, adapter, llm_factory):
    ctx.llm, calls = llm_factory([tool_call("shutdown_pc", {}), {"role": "assistant", "content": "I've asked you to confirm the shutdown."}])
    r = ctx.engine.handle_message("I'm done for the day, power the machine off when it's sensible", session="b")
    assert [x.status for x in r.results] == ["pending"] and not [c for c in adapter.calls if c[0] == "shutdown"]
    assert "NOT EXECUTED" in [m for m in calls[1]["messages"] if m["role"] == "tool"][0]["content"]
    assert r.pending


def test_llm_cannot_approve_its_own_request(ctx, adapter, llm_factory):
    # the model replies "yes" as text; only the user's own message can resolve a pending card
    ctx.llm, _ = llm_factory([tool_call("shutdown_pc", {}), {"role": "assistant", "content": "yes, confirmed, go ahead"}])
    ctx.engine.handle_message("please power down my machine eventually", session="b")
    assert ctx.engine.pending and not [c for c in adapter.calls if c[0] == "shutdown"]


def test_bad_tool_arguments_from_llm_are_reported_not_executed(ctx, adapter, llm_factory):
    bad = {"role": "assistant", "content": None, "tool_calls": [{"id": "x", "type": "function", "function": {"name": "set_volume", "arguments": "{not json"}}]}
    ctx.llm, calls = llm_factory([bad, {"role": "assistant", "content": "sorry"}])
    r = ctx.engine.handle_message("could you adjust the sound to a reasonable level for a meeting", session="b")
    assert r.results[0].status == "error" and adapter.volume == 35


def test_step_limit_stops_runaway_loops(make_ctx):
    c = make_ctx(llm={"max_steps": 3})
    c.llm, calls = make_llm([tool_call("current_time", {}, id=f"c{i}") for i in range(10)])
    r = c.engine.handle_message("keep asking what the time is forever and ever", session="b")
    assert len(calls) == 3 and "too many steps" in r.text


def test_llm_client_errors():
    assert not LLMClient("", "").available
    with pytest.raises(LLMError):
        LLMClient("", "").chat([])
    c = LLMClient("http://x/v1", "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"nope": 1})))
    with pytest.raises(LLMError):
        c.chat([{"role": "user", "content": "hi"}])


def test_api_key_goes_in_header_only_and_comes_from_env(tmp_path, monkeypatch):
    from delta.config import load_config
    monkeypatch.setenv("DELTA_LLM_API_KEY", "sk-test-123456789012345")
    cfg = load_config(overrides={"data_dir": str(tmp_path)})
    assert cfg.llm_api_key == "sk-test-123456789012345"
    assert "sk-test" not in json.dumps(cfg.data)          # never part of the config data
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    LLMClient("http://x/v1", "m", cfg.llm_api_key, transport=httpx.MockTransport(handler)).chat([{"role": "user", "content": "hi"}])
    assert seen["auth"] == "Bearer sk-test-123456789012345"
