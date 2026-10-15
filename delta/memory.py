"""SQLite storage: conversation history, user facts, notes, todos, reminders. Never stores secrets."""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .safety import looks_like_secret

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session TEXT, role TEXT, content TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, text TEXT UNIQUE, ts REAL);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, text TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS todos(id INTEGER PRIMARY KEY, text TEXT, done INTEGER DEFAULT 0, ts REAL, done_ts REAL);
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY, text TEXT, kind TEXT DEFAULT 'reminder', due_ts REAL, status TEXT DEFAULT 'pending',
  created REAL, fired_ts REAL, missed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS routine_runs(name TEXT, date TEXT, PRIMARY KEY(name, date));
"""


class SecretRefused(ValueError):
    pass


class Memory:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _q(self, sql: str, args: tuple = (), commit: bool = False) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._db.execute(sql, args)
            rows = cur.fetchall()
            if commit:
                self._db.commit()
            self._last_id = cur.lastrowid
            return rows

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- messages
    def add_message(self, session: str, role: str, content: str) -> None:
        self._q("INSERT INTO messages(session,role,content,ts) VALUES(?,?,?,?)", (session, role, content, time.time()), True)

    def history(self, session: str, limit: int = 12) -> list[dict]:
        rows = self._q("SELECT role,content FROM messages WHERE session=? ORDER BY id DESC LIMIT ?", (session, limit))
        return [dict(r) for r in reversed(rows)]

    def all_messages(self, session: str, limit: int = 200) -> list[dict]:
        rows = self._q("SELECT role,content,ts FROM messages WHERE session=? ORDER BY id DESC LIMIT ?", (session, limit))
        return [dict(r) for r in reversed(rows)]

    def clear_history(self, session: str) -> None:
        self._q("DELETE FROM messages WHERE session=?", (session,), True)

    # --- facts
    def add_fact(self, text: str) -> int:
        text = " ".join(text.split())
        if not text:
            raise ValueError("empty fact")
        if looks_like_secret(text):
            raise SecretRefused("That looks like a password, key, PIN or card detail. I never store those.")
        self._q("INSERT OR IGNORE INTO facts(text,ts) VALUES(?,?)", (text, time.time()), True)
        return self._q("SELECT id FROM facts WHERE text=?", (text,))[0]["id"]

    def facts(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT id,text FROM facts ORDER BY id")]

    def forget_fact(self, fid: int) -> bool:
        n = len(self._q("SELECT id FROM facts WHERE id=?", (fid,)))
        self._q("DELETE FROM facts WHERE id=?", (fid,), True)
        return bool(n)

    # --- notes
    def add_note(self, text: str) -> int:
        self._q("INSERT INTO notes(text,ts) VALUES(?,?)", (text.strip(), time.time()), True)
        return self._last_id

    def notes(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self._q("SELECT id,text,ts FROM notes ORDER BY id DESC LIMIT ?", (limit,))]

    # --- todos
    def add_todo(self, text: str) -> int:
        self._q("INSERT INTO todos(text,ts) VALUES(?,?)", (text.strip(), time.time()), True)
        return self._last_id

    def todos(self, include_done: bool = False) -> list[dict]:
        sql = "SELECT id,text,done FROM todos" + ("" if include_done else " WHERE done=0") + " ORDER BY id"
        return [dict(r) for r in self._q(sql)]

    def complete_todo(self, tid: int) -> bool:
        n = len(self._q("SELECT id FROM todos WHERE id=? AND done=0", (tid,)))
        self._q("UPDATE todos SET done=1, done_ts=? WHERE id=?", (time.time(), tid), True)
        return bool(n)

    def delete_todo(self, tid: int) -> bool:
        n = len(self._q("SELECT id FROM todos WHERE id=?", (tid,)))
        self._q("DELETE FROM todos WHERE id=?", (tid,), True)
        return bool(n)

    # --- reminders
    def add_reminder(self, text: str, due: datetime, kind: str = "reminder") -> int:
        self._q("INSERT INTO reminders(text,kind,due_ts,created) VALUES(?,?,?,?)",
                (text.strip(), kind, due.timestamp(), time.time()), True)
        return self._last_id

    def reminders(self, status: str | None = "pending") -> list[dict]:
        if status:
            rows = self._q("SELECT * FROM reminders WHERE status=? ORDER BY due_ts", (status,))
        else:
            rows = self._q("SELECT * FROM reminders ORDER BY due_ts")
        return [dict(r) for r in rows]

    def due_reminders(self, now: float) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM reminders WHERE status='pending' AND due_ts<=? ORDER BY due_ts", (now,))]

    def mark_fired(self, rid: int, missed: bool = False) -> None:
        self._q("UPDATE reminders SET status='fired', fired_ts=?, missed=? WHERE id=?", (time.time(), int(missed), rid), True)

    def cancel_reminder(self, rid: int) -> bool:
        n = len(self._q("SELECT id FROM reminders WHERE id=? AND status='pending'", (rid,)))
        self._q("UPDATE reminders SET status='cancelled' WHERE id=? AND status='pending'", (rid,), True)
        return bool(n)

    # --- routine schedule bookkeeping (so a daily routine fires once per day)
    def routine_ran(self, name: str, date: str) -> bool:
        return bool(self._q("SELECT 1 FROM routine_runs WHERE name=? AND date=?", (name, date)))

    def mark_routine_ran(self, name: str, date: str) -> None:
        self._q("INSERT OR IGNORE INTO routine_runs(name,date) VALUES(?,?)", (name, date), True)
