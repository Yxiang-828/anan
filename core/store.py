"""SQLite state store + event log — the kernel's single source of truth.

Receipts over narration: every skill outcome, transition, and delivery lands
in `events` with what actually changed (`effect`), not just a status. All
skill state flows through here; skills never talk to each other directly.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,           -- injected-clock time (what the demo shows)
  wall REAL NOT NULL,         -- wall time (forensics)
  kind TEXT NOT NULL,         -- wake|transition|skill|delivery|heartbeat|inject|error
  source TEXT NOT NULL,
  detail TEXT NOT NULL,       -- JSON
  effect TEXT NOT NULL DEFAULT ''  -- what actually changed in the world
);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS med_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, med TEXT NOT NULL, status TEXT NOT NULL  -- taken|missed|reminded
);
CREATE TABLE IF NOT EXISTS mood_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, label TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, day INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS escalation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, step TEXT NOT NULL, contact TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT ''
);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._listeners: list[Any] = []

    # --- events (receipts) -------------------------------------------------
    def event(self, at: str, kind: str, source: str, detail: dict, effect: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events(at, wall, kind, source, detail, effect) VALUES (?,?,?,?,?,?)",
                (at, time.time(), kind, source, json.dumps(detail, ensure_ascii=False), effect),
            )
            self._conn.commit()
            row_id = cur.lastrowid
        payload = {"id": row_id, "at": at, "kind": kind, "source": source,
                   "detail": detail, "effect": effect}
        for fn in list(self._listeners):
            try:
                fn(payload)
            except Exception:
                pass  # a broken listener must never block the record
        return row_id

    def listen(self, fn) -> None:
        self._listeners.append(fn)

    def recent_events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, at, kind, source, detail, effect FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "at": r[1], "kind": r[2], "source": r[3],
             "detail": json.loads(r[4]), "effect": r[5]}
            for r in reversed(rows)
        ]

    # --- kv ----------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._conn.commit()

    # --- typed logs ---------------------------------------------------------
    def log(self, table: str, **cols: Any) -> None:
        keys = ",".join(cols)
        marks = ",".join("?" * len(cols))
        with self._lock:
            self._conn.execute(f"INSERT INTO {table}({keys}) VALUES ({marks})", tuple(cols.values()))
            self._conn.commit()

    def rows(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()
