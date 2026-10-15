import json

from delta.audit import AuditLog


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_audit_writes_jsonl_with_chain(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl", session="s1")
    a.log("tool_call", tool="set_volume", args={"percent": 30}, status="ok")
    a.log("blocked", tool="x", reason="nope")
    rows = lines(tmp_path / "a.jsonl")
    assert [r["event"] for r in rows] == ["tool_call", "blocked"]
    assert rows[0]["args"] == {"percent": 30} and rows[0]["session"] == "s1"
    assert rows[1]["prev"] == rows[0]["hash"]
    assert a.verify() == (True, None)


def test_audit_redacts_secrets_and_sensitive_keys(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl")
    a.log("tool_call", args={"password": "hunter2", "api_key": "abc", "note": "my password is swordfish"}, result="Bearer abcdefghijklmnopqrstuvwxyz")
    raw = (tmp_path / "a.jsonl").read_text()
    for leak in ("hunter2", "swordfish", "abcdefghijklmnopqrstuvwxyz", '"abc"'):
        assert leak not in raw


def test_audit_hides_named_args_and_truncates(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl")
    a.log("tool_call", hide=("text",), args={"text": "private clipboard content"}, result="y" * 2000)
    r = lines(tmp_path / "a.jsonl")[0]
    assert r["args"]["text"] == "<25 chars>"
    assert len(r["result"]) < 600


def test_tampering_is_detected(tmp_path):
    p = tmp_path / "a.jsonl"
    a = AuditLog(p)
    for i in range(4):
        a.log("tool_call", tool=f"t{i}", status="ok")
    rows = p.read_text().splitlines()
    rows[1] = rows[1].replace("t1", "tX")
    p.write_text("\n".join(rows) + "\n")
    ok, bad = AuditLog(p).verify()
    assert ok is False and bad == 2


def test_deleting_a_line_is_detected(tmp_path):
    p = tmp_path / "a.jsonl"
    a = AuditLog(p)
    for i in range(4):
        a.log("e", n=i)
    rows = p.read_text().splitlines()
    del rows[1]
    p.write_text("\n".join(rows) + "\n")
    assert AuditLog(p).verify()[0] is False


def test_chain_continues_after_restart(tmp_path):
    p = tmp_path / "a.jsonl"
    AuditLog(p).log("one")
    b = AuditLog(p)
    b.log("two")
    assert b.verify() == (True, None) and len(b.tail(10)) == 2


def test_engine_audits_every_decision(eng, ctx, home):
    (home / "Downloads" / "x.txt").write_text("1")
    eng.handle_message("volume 20")
    eng.handle_message("delete x.txt")
    eng.handle_message("no")
    eng.handle_message("run command: format c:")
    events = [(r["event"], r.get("tool")) for r in ctx.audit.tail(50)]
    assert ("tool_call", "set_volume") in events
    assert ("confirm_requested", "delete_path") in events
    assert ("confirm_denied", "delete_path") in events
    assert ("blocked", "run_command") in events
    assert ctx.audit.verify()[0]
