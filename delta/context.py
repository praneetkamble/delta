"""Wires config, adapter, storage, audit, tools, routines and the engine together."""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable

from .adapters import Adapter, get_adapter
from .audit import AuditLog
from .config import Config
from .llm import LLMClient
from .memory import Memory
from .registry import ToolRegistry
from .routines import RoutineBook
from .safety import PermissionPolicy, Sandbox


class Context:
    def __init__(self, config: Config, adapter: Adapter, memory: Memory, audit: AuditLog, registry: ToolRegistry,
                 sandbox: Sandbox, llm: LLMClient | None, routines: RoutineBook):
        self.config = config
        self.adapter = adapter
        self.memory = memory
        self.audit = audit
        self.registry = registry
        self.sandbox = sandbox
        self.llm = llm
        self.routines = routines
        self.policy = PermissionPolicy(config)
        self.killed = threading.Event()
        self.events: deque[dict] = deque(maxlen=200)
        self._event_seq = 0
        self._dry_run = config.dry_run
        self.engine: Any = None
        self.vibe: Any = None                             # VibeManager (Vibe Coding), set by build_context
        self.scheduler: Any = None                        # set by `delta serve`; the dashboard only reads its status
        self.started = time.time()
        self.clock: Callable[[], datetime] = datetime.now
        self.sleep: Callable[[float], None] = time.sleep
        self.speak: Callable[[str], None] | None = None   # set by the voice layer
        self.http_transport = None                        # tests inject httpx.MockTransport

    def now(self) -> datetime:
        return self.clock()

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @dry_run.setter
    def dry_run(self, v: bool) -> None:
        self._dry_run = bool(v)

    def emit(self, type_: str, **data: Any) -> dict:
        self._event_seq += 1
        ev = {**data, "id": self._event_seq, "type": type_, "ts": time.time()}   # reserved keys win
        self.events.append(ev)
        return ev


def build_context(config: Config, adapter: Adapter | None = None, llm: LLMClient | None = None,
                  memory: Memory | None = None, session: str = "default") -> Context:
    from .engine import Engine
    from .skills import register_all

    adapter = adapter or get_adapter(config)
    data = config.data_dir
    memory = memory or Memory(data / "delta.db")
    audit = AuditLog(data / "audit.jsonl", redact=bool(config.get("safety.redact_secrets", True)), session=session)
    registry = register_all(ToolRegistry())
    sandbox = Sandbox(config.allowed_folders)
    if llm is None:
        lc = config.get("llm", {})
        llm = LLMClient(lc.get("base_url", ""), lc.get("model", ""), config.llm_api_key, lc.get("timeout_s", 60), lc.get("temperature", 0.2))
    routines = RoutineBook.load(config.routines_path)
    ctx = Context(config, adapter, memory, audit, registry, sandbox, llm, routines)
    ctx.engine = Engine(ctx)
    from .vibe import VibeManager
    ctx.vibe = VibeManager(ctx)
    return ctx
