import pytest
from fastapi.testclient import TestClient

from delta.server import assert_loopback, create_app, new_token

TOKEN = "t" * 32


@pytest.fixture
def client(ctx):
    app = create_app(ctx, TOKEN, 8765)
    return TestClient(app, base_url="http://127.0.0.1:8765")


@pytest.fixture
def authed(client):
    client.cookies.set("delta_token", TOKEN)
    return client


def test_api_requires_the_token(client):
    for path in ("/api/state", "/api/history", "/api/audit", "/api/panels", "/api/events"):
        assert client.get(path).status_code == 401
    assert client.post("/api/chat", json={"message": "volume 10"}).status_code == 401
    assert client.post("/api/kill").status_code == 401
    assert client.get("/api/state", headers={"x-delta-token": "wrong"}).status_code == 401


def test_header_token_works(client):
    assert client.get("/api/state", headers={"x-delta-token": TOKEN}).status_code == 200


def test_index_requires_token_and_sets_cookie(client):
    assert client.get("/").status_code == 401
    assert client.get("/?token=nope").status_code == 401
    r = client.get(f"/?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    page = client.get("/")
    assert page.status_code == 200 and "DELTA" in page.text
    assert page.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_foreign_host_header_is_rejected(authed):
    r = authed.get("/api/state", headers={"host": "evil.example.com"})
    assert r.status_code == 400                                       # DNS-rebinding protection


def test_cross_origin_post_is_rejected(authed):
    r = authed.post("/api/chat", json={"message": "volume 10"}, headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403
    ok = authed.post("/api/chat", json={"message": "volume 10"}, headers={"origin": "http://127.0.0.1:8765"})
    assert ok.status_code == 200


def test_chat_roundtrip_and_state(authed, adapter):
    r = authed.post("/api/chat", json={"message": "volume 61"}).json()
    assert r["results"][0]["status"] == "ok" and adapter.volume == 61
    assert r["state"]["adapter"] == {"name": "mock", "real": False}
    assert authed.get("/api/history").json()["messages"][-1]["role"] == "assistant"


def test_confirmation_over_the_api(authed, adapter):
    r = authed.post("/api/chat", json={"message": "restart"}).json()
    pid = r["pending"][0]["id"]
    assert r["results"][0]["status"] == "pending" and not adapter.calls
    res = authed.post("/api/confirm", json={"id": pid, "approve": True}).json()
    assert res["result"]["status"] == "ok" and ("restart", 30) in adapter.calls and res["state"]["pending"] == []
    again = authed.post("/api/confirm", json={"id": pid, "approve": True}).json()
    assert again["result"]["status"] == "expired"


def test_kill_resume_and_dry_run_endpoints(authed, adapter):
    assert authed.post("/api/kill").json()["killed"] is True
    assert "paused" in authed.post("/api/chat", json={"message": "volume 10"}).json()["text"].lower()
    assert authed.post("/api/resume").json()["killed"] is False
    assert authed.post("/api/dryrun", json={"enabled": True}).json()["dry_run"] is True
    assert authed.post("/api/chat", json={"message": "volume 10"}).json()["results"][0]["status"] == "dry_run"
    assert adapter.volume == 35


def test_audit_endpoint_and_panels(authed):
    authed.post("/api/chat", json={"message": "add todo test the panel"})
    assert any(e["event"] == "tool_call" for e in authed.get("/api/audit").json()["entries"])
    assert authed.get("/api/panels").json()["todos"][0]["text"] == "test the panel"
    assert authed.get("/api/state").json()["audit_ok"] is True


def test_oversized_message_rejected(authed):
    assert authed.post("/api/chat", json={"message": "x" * 5000}).status_code == 413


def test_voice_endpoint_disabled_by_default(authed):
    assert authed.post("/api/voice/listen").status_code == 400


def test_no_docs_or_openapi_exposed(authed):
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert authed.get(p).status_code == 404


def test_only_loopback_binding_allowed():
    assert_loopback("127.0.0.1")
    assert_loopback("localhost")
    assert_loopback("::1")
    for bad in ("0.0.0.0", "192.168.1.5", "::", "example.com", ""):
        with pytest.raises(ValueError):
            assert_loopback(bad)


def test_tokens_are_random_and_long():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 32


def test_events_endpoint_survives_events_with_their_own_ids(authed, eng):
    # regression: events carrying an `id` field used to overwrite the event sequence id and crash /api/events
    eng.execute("shutdown_pc")                       # emits a "confirm" event
    r = authed.get("/api/events?since=0")
    assert r.status_code == 200
    evs = r.json()["events"]
    assert evs and all(isinstance(e["id"], int) for e in evs)
    assert authed.get(f"/api/events?since={evs[-1]['id']}").json()["events"] == []
