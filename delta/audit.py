"""Append-only JSONL audit log with a SHA-256 hash chain (tampering with or deleting a middle line is detectable)."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from .safety import redact_secrets

_SENSITIVE_KEYS = ("password", "passwd", "pwd", "token", "secret", "api_key", "apikey", "authorization", "cookie")


def _clean(value: Any, key: str = "", hide: tuple = (), redact: bool = True) -> Any:
    if any(s in key.lower() for s in _SENSITIVE_KEYS):
        return "***"
    if key in hide and isinstance(value, str):
        return f"<{len(value)} chars>"
    if isinstance(value, dict):
        return {k: _clean(v, k, hide, redact) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, key, hide, redact) for v in value[:50]]
    if isinstance(value, str):
        v = redact_secrets(value) if redact else value
        return v if len(v) <= 500 else v[:500] + f"…(+{len(v) - 500} chars)"
    return value


class AuditLog:
    def __init__(self, path: Path, redact: bool = True, session: str = ""):
        self.path = Path(path)
        self.redact = redact
        self.session = session
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prev = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = ""
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return "0" * 64
        try:
            return json.loads(last).get("hash", "0" * 64)
        except json.JSONDecodeError:
            return "0" * 64

    @staticmethod
    def _digest(prev: str, record: dict) -> str:
        body = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()

    def log(self, event: str, hide: tuple = (), **fields: Any) -> dict:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, "session": self.session}
        rec.update({k: _clean(v, k, hide, self.redact) for k, v in fields.items()})
        with self._lock:
            rec["prev"] = self._prev
            rec["hash"] = self._digest(self._prev, {k: v for k, v in rec.items() if k != "hash"})
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._prev = rec["hash"]
        return rec

    def tail(self, n: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        out = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                out.append({"event": "corrupt_line", "raw": ln[:80]})
        return out

    def verify(self) -> tuple[bool, int | None]:
        """Returns (ok, first_bad_line_number)."""
        prev = "0" * 64
        if not self.path.exists():
            return True, None
        with open(self.path, "r", encoding="utf-8") as fh:
            for i, ln in enumerate(fh, 1):
                if not ln.strip():
                    continue
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError:
                    return False, i
                h = rec.pop("hash", None)
                if rec.get("prev") != prev or h != self._digest(prev, rec):
                    return False, i
                prev = h
        return True, None
