"""Local web UI + JSON API (FastAPI). Binds to 127.0.0.1 only; every request needs a random per-run token."""
from __future__ import annotations

import ipaddress
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .dashboard import VitalsSampler, make_lifespan, register_dashboard

STATIC = Path(__file__).parent / "ui" / "static"
COOKIE = "delta_token"
ASSETS = {"dashboard.css": "text/css", "dashboard.js": "text/javascript", "vibe.js": "text/javascript", "vibe.css": "text/css", "Geist.woff2": "font/woff2", "GeistMono.woff2": "font/woff2"}
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; frame-src http://127.0.0.1:* http://localhost:*; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def assert_loopback(host: str) -> None:
    """Refuse to start the server on anything but a loopback address (no network exposure)."""
    try:
        ok = ipaddress.ip_address(host).is_loopback
    except ValueError:
        ok = host == "localhost"
    if not ok:
        raise ValueError(f"Delta only binds to a loopback address (127.0.0.1); refusing {host!r}")


def new_token() -> str:
    return secrets.token_urlsafe(24)


class ChatIn(BaseModel):
    message: str


class ConfirmIn(BaseModel):
    id: str
    approve: bool


class DryRunIn(BaseModel):
    enabled: bool


def create_app(ctx: Any, token: str, port: int = 8765, voice_trigger: Callable[[], None] | None = None) -> FastAPI:
    sampler = VitalsSampler(ctx)
    app = FastAPI(title="Delta", docs_url=None, redoc_url=None, openapi_url=None, lifespan=make_lifespan(sampler))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    engine = ctx.engine
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def authed(request: Request) -> None:
        supplied = request.cookies.get(COOKIE) or request.headers.get("x-delta-token") or ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="missing or wrong token")
        # Browsers always send Sec-Fetch-Site and a page cannot forge it. A request from another localhost PORT (for example the
        # Vibe Coding preview iframe, which runs AI-written code) is "same-site" but not "same-origin": refuse it.
        site = request.headers.get("sec-fetch-site")
        if site is not None and site not in ("same-origin", "none"):
            raise HTTPException(status_code=403, detail="cross-origin request refused")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None and origin not in origins:
                raise HTTPException(status_code=403, detail="bad origin")

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        q = request.query_params.get("token")
        if q is not None:
            if not secrets.compare_digest(q, token):
                return PlainTextResponse("Wrong token. Open the link printed in the Delta window.", status_code=401)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
            return resp
        if not secrets.compare_digest(request.cookies.get(COOKIE) or "", token):
            return PlainTextResponse("Delta: open the full link (with ?token=…) that was printed when Delta started.", status_code=401)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                                           "Content-Security-Policy": CSP})

    @app.get("/assets/{name}", include_in_schema=False)
    def asset(name: str, request: Request):
        # fixed whitelist (no path joins from user input); same token cookie as the API
        if name not in ASSETS:
            raise HTTPException(status_code=404, detail="not found")
        if not secrets.compare_digest(request.cookies.get(COOKIE) or "", token):
            raise HTTPException(status_code=401, detail="missing or wrong token")
        sub = "fonts" if name.endswith(".woff2") else "."
        return FileResponse(STATIC / sub / name, media_type=ASSETS[name], headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

    def state_dict() -> dict:
        llm = ctx.llm
        return {
            "version": __version__, "user": ctx.config.get("user_name"),
            "adapter": ctx.adapter.describe(), "dry_run": ctx.dry_run, "killed": ctx.killed.is_set(),
            "brain": {"mode": ctx.config.get("brain.mode"), "llm": bool(llm and llm.available), "model": (llm.model if llm and llm.available else "")},
            "pending": engine.pending_list(), "voice": voice_trigger is not None,
            "counts": {"reminders": len(ctx.memory.reminders("pending")), "todos": len(ctx.memory.todos())},
            "audit_ok": ctx.audit.verify()[0],
        }

    @app.get("/api/state", dependencies=[Depends(authed)])
    def state():
        return state_dict()

    @app.post("/api/chat", dependencies=[Depends(authed)])
    def chat(body: ChatIn):
        if len(body.message) > 4000:
            raise HTTPException(status_code=413, detail="message too long")
        reply = engine.handle_message(body.message, origin="user", session="web")
        return {**reply.to_dict(), "state": state_dict()}

    @app.post("/api/confirm", dependencies=[Depends(authed)])
    def confirm(body: ConfirmIn):
        res = engine.resolve(body.id, body.approve, via="ui")
        return {"result": res.to_dict(), "state": state_dict()}

    @app.get("/api/history", dependencies=[Depends(authed)])
    def history():
        return {"messages": ctx.memory.all_messages("web", 60)}

    @app.post("/api/clear", dependencies=[Depends(authed)])
    def clear():
        ctx.memory.clear_history("web")
        engine.session("web").taint_ttl = 0
        return {"ok": True}

    @app.get("/api/panels", dependencies=[Depends(authed)])
    def panels():
        now = ctx.now()
        rem = [{"id": r["id"], "text": r["text"], "kind": r["kind"],
                "due": datetime.fromtimestamp(r["due_ts"]).strftime("%a %I:%M %p").replace(" 0", " ")} for r in ctx.memory.reminders("pending")[:6]]
        return {"reminders": rem, "todos": ctx.memory.todos()[:8],
                "routines": [{"name": r.name, "schedule": r.schedule_text} for r in ctx.routines.all()]}

    @app.get("/api/audit", dependencies=[Depends(authed)])
    def audit(limit: int = 30):
        rows = ctx.audit.tail(max(1, min(limit, 200)))
        keep = ("ts", "event", "tool", "status", "origin", "reason", "description", "result", "text")
        return {"entries": [{k: r.get(k) for k in keep if k in r} for r in rows][::-1]}

    @app.get("/api/events", dependencies=[Depends(authed)])
    def events(since: int = 0):
        return {"events": [e for e in list(ctx.events) if e["id"] > since]}

    @app.post("/api/kill", dependencies=[Depends(authed)])
    def kill():
        engine.kill("UI button")
        return state_dict()

    @app.post("/api/resume", dependencies=[Depends(authed)])
    def resume():
        engine.resume()
        return state_dict()

    @app.post("/api/dryrun", dependencies=[Depends(authed)])
    def dryrun(body: DryRunIn):
        ctx.dry_run = body.enabled
        ctx.audit.log("dry_run_changed", enabled=body.enabled)
        return state_dict()

    @app.post("/api/voice/listen", dependencies=[Depends(authed)])
    def voice_listen():
        if voice_trigger is None:
            raise HTTPException(status_code=400, detail="voice is not enabled (see README)")
        import threading
        threading.Thread(target=voice_trigger, daemon=True).start()
        return {"ok": True}

    register_dashboard(app, ctx, authed, state_dict, sampler, voice_trigger is not None)
    from .vibe.api import register_vibe_api
    register_vibe_api(app, ctx, authed, state_dict)
    return app
