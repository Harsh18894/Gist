"""Append-only, hash-chained audit log of investigations (Phase 4.2).

Each entry's hash covers its content and the previous entry's hash, so editing or deleting
any past entry breaks verification. Gist exposes no route that updates or deletes entries.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import ROOT

GENESIS = "0" * 64
FIELDS = ("id", "created_at", "question", "planner", "status", "plan", "trace", "results", "checks", "findings", "cost_usd", "report")
JSON_FIELDS = ("plan", "trace", "results", "checks", "findings", "report")


def log_path() -> Path:
    value = os.getenv("GIST_INVESTIGATIONS_DB_PATH")
    if not value:
        return ROOT / "backend" / "gist-investigations.sqlite3"
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(log_path())
    db.execute("""CREATE TABLE IF NOT EXISTS investigations (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL, question TEXT NOT NULL, planner TEXT NOT NULL, status TEXT NOT NULL, plan TEXT NOT NULL,
        trace TEXT NOT NULL, results TEXT NOT NULL, checks TEXT NOT NULL, findings TEXT NOT NULL, cost_usd REAL NOT NULL,
        prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL)""")
    if "report" not in {r[1] for r in db.execute("PRAGMA table_info(investigations)")}:
        db.execute("ALTER TABLE investigations ADD COLUMN report TEXT NOT NULL DEFAULT 'null'")   # added in Phase 4.3
    return db


def _digest(entry: dict, prev_hash: str) -> str:
    # "report" joined in Phase 4.3; entries without one hash exactly as before, so older chains still verify.
    fields = [k for k in FIELDS if not (k == "report" and entry.get(k) in (None, "null"))]
    body = json.dumps({k: entry[k] for k in fields}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def append(entry: dict) -> dict:
    entry = {"id": f"INV-{uuid.uuid4().hex[:10]}", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "report": None, **entry}
    stored = {k: json.dumps(entry[k], ensure_ascii=False, default=str) if k in JSON_FIELDS else entry[k] for k in FIELDS}
    with _db() as db:
        prev = db.execute("SELECT entry_hash FROM investigations ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = prev[0] if prev else GENESIS
        digest = _digest(stored, prev_hash)
        db.execute(f"INSERT INTO investigations ({', '.join(FIELDS)}, prev_hash, entry_hash) VALUES ({', '.join('?' * (len(FIELDS) + 2))})",
                   [stored[k] for k in FIELDS] + [prev_hash, digest])
    return {**entry, "entry_hash": digest}


def _row(r: tuple, full: bool) -> dict:
    item = dict(zip(FIELDS + ("prev_hash", "entry_hash"), r))
    for k in JSON_FIELDS:
        item[k] = json.loads(item[k])
    if not full:
        item = {k: item[k] for k in ("id", "created_at", "question", "planner", "status", "cost_usd", "entry_hash")} | \
               {"has_report": bool(item["report"] and item["report"].get("report"))}
    return item


def recent(limit: int = 20) -> list[dict]:
    with _db() as db:
        rows = db.execute(f"SELECT {', '.join(FIELDS)}, prev_hash, entry_hash FROM investigations ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r, False) for r in rows]


def get(investigation_id: str) -> dict | None:
    with _db() as db:
        row = db.execute(f"SELECT {', '.join(FIELDS)}, prev_hash, entry_hash FROM investigations WHERE id = ?", (investigation_id,)).fetchone()
    return _row(row, True) if row else None


def verify() -> dict:
    """Recompute the chain. Returns {'ok': bool, 'entries': n, 'first_bad': id | None}."""
    with _db() as db:
        rows = db.execute(f"SELECT {', '.join(FIELDS)}, prev_hash, entry_hash FROM investigations ORDER BY seq").fetchall()
    prev = GENESIS
    for r in rows:
        stored = dict(zip(FIELDS, r[:len(FIELDS)]))
        if r[-2] != prev or _digest(stored, prev) != r[-1]:
            return {"ok": False, "entries": len(rows), "first_bad": stored["id"]}
        prev = r[-1]
    return {"ok": True, "entries": len(rows), "first_bad": None}
