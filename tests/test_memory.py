import pytest

from delta.memory import Memory, SecretRefused


@pytest.fixture
def mem(tmp_path):
    return Memory(tmp_path / "m.db")


def test_history_order_and_limit(mem):
    for i in range(5):
        mem.add_message("s", "user" if i % 2 == 0 else "assistant", f"m{i}")
    mem.add_message("other", "user", "zzz")
    assert [m["content"] for m in mem.history("s", 3)] == ["m2", "m3", "m4"]
    mem.clear_history("s")
    assert mem.history("s") == [] and len(mem.history("other")) == 1


def test_facts_deduplicate_and_forget(mem):
    a = mem.add_fact("my gym day is Tuesday")
    assert mem.add_fact("my  gym day is Tuesday") == a
    assert len(mem.facts()) == 1
    assert mem.forget_fact(a) and not mem.forget_fact(a)


@pytest.mark.parametrize("text", ["my password is hunter2", "my otp is 123456", "the api key: sk-abcdefghijklmnopqrstu", "card number 4111 1111 1111 1111", "my pin is 4321"])
def test_facts_refuse_secrets(mem, text):
    with pytest.raises(SecretRefused):
        mem.add_fact(text)
    assert mem.facts() == []


def test_remember_via_chat_refuses_password(eng, ctx):
    r = eng.handle_message("remember that my wifi password is abc12345")
    assert r.results[0].status == "error" and "never store" in r.text
    assert ctx.memory.facts() == []
    assert "abc12345" not in (ctx.config.data_dir / "audit.jsonl").read_text()


def test_todos_and_notes(mem):
    t1, t2 = mem.add_todo("a"), mem.add_todo("b")
    assert mem.complete_todo(t1) and not mem.complete_todo(t1)
    assert [t["text"] for t in mem.todos()] == ["b"]
    assert len(mem.todos(include_done=True)) == 2
    assert mem.delete_todo(t2)
    mem.add_note("hello")
    assert mem.notes()[0]["text"] == "hello"


def test_data_survives_reopen(tmp_path):
    p = tmp_path / "m.db"
    Memory(p).add_fact("I like tea")
    assert Memory(p).facts()[0]["text"] == "I like tea"
