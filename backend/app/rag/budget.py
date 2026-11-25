"""Project-wide, concurrency-safe paid API reservations (estimated USD).

The provider invoice remains authoritative. Uncertain requests hold their full
reservation until an operator reconciles them outside this automatic path.
"""
from __future__ import annotations

import os
import math
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import ROOT

MAX_VALIDATION_USD = 0.50
RESERVATION_FLOOR_USD = 0.05


def _path() -> Path:
    value = Path(os.getenv("GIST_SPEND_DB_PATH", "backend/gist-spend.sqlite3"))
    return value if value.is_absolute() else ROOT / value


@contextmanager
def _ledger() -> Iterator[sqlite3.Connection]:
    """Open the autocommit ledger connection and always close it.

    A plain `with sqlite3.connect(...)` only commits; it never closes. Callers
    keep their whole transaction (and any `SELECT changes()`) inside one block.
    """
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("""CREATE TABLE IF NOT EXISTS spend_requests (
            id TEXT PRIMARY KEY, request_key TEXT UNIQUE, created_at TEXT NOT NULL,
            endpoint TEXT NOT NULL, model TEXT NOT NULL, state TEXT NOT NULL,
            reserved_usd REAL NOT NULL, actual_estimated_usd REAL,
            input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER,
            failure TEXT)""")
        yield db
    finally:
        db.close()


def summary() -> dict:
    with _ledger() as db:
        row = db.execute("""SELECT COALESCE(SUM(CASE WHEN state IN ('completed','reconciled') THEN actual_estimated_usd
            ELSE reserved_usd END),0), COUNT(*), COALESCE(SUM(state='uncertain'),0),
            COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0)
            FROM spend_requests""").fetchone()
        uncertain = [dict(zip(("id", "created_at", "endpoint", "model", "reserved_usd", "failure"), item))
                     for item in db.execute("""SELECT id,created_at,endpoint,model,reserved_usd,failure
                         FROM spend_requests WHERE state='uncertain' ORDER BY created_at""")]
    return {"committed_or_reserved_usd": round(row[0], 8), "requests": row[1],
            "uncertain_requests": row[2], "input_tokens": row[3],
            "output_tokens": row[4], "allocation_usd": MAX_VALIDATION_USD,
            "uncertain_entries": uncertain}


def reserve(endpoint: str, model: str, worst_case_usd: float,
            request_key: str | None = None, limit_usd: float = MAX_VALIDATION_USD) -> str:
    amount = max(RESERVATION_FLOOR_USD, worst_case_usd)
    identifier = str(uuid.uuid4())
    with _ledger() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if request_key and db.execute("SELECT 1 FROM spend_requests WHERE request_key=?", (request_key,)).fetchone():
                raise ValueError("This paid request was already attempted. Reconcile its result before retrying.")
            if db.execute("SELECT 1 FROM spend_requests WHERE state='uncertain' LIMIT 1").fetchone():
                raise ValueError("A previous paid request has uncertain billing; reconcile it before new calls.")
            held = db.execute("""SELECT COALESCE(SUM(CASE WHEN state IN ('completed','reconciled') THEN actual_estimated_usd
                ELSE reserved_usd END),0) FROM spend_requests""").fetchone()[0]
            if held + amount > min(limit_usd, MAX_VALIDATION_USD) + 1e-10:
                raise ValueError("The project-wide validation allocation is exhausted or reserved.")
            db.execute("""INSERT INTO spend_requests
                (id,request_key,created_at,endpoint,model,state,reserved_usd)
                VALUES (?,?,?,?,?,'reserved',?)""",
                (identifier, request_key, datetime.now(timezone.utc).isoformat(), endpoint, model, amount))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
    return identifier


def finish(identifier: str, *, state: str, actual: float | None = None,
           input_tokens: int | None = None, output_tokens: int | None = None,
           latency_ms: int | None = None, failure: str | None = None) -> None:
    if state not in {"completed", "uncertain"}:
        raise ValueError("Invalid spend state")
    with _ledger() as db:
        db.execute("""UPDATE spend_requests SET state=?,actual_estimated_usd=?,input_tokens=?,
            output_tokens=?,latency_ms=?,failure=? WHERE id=? AND state='reserved'""",
            (state, actual, input_tokens, output_tokens, latency_ms, failure, identifier))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            raise RuntimeError("Spend reservation could not be reconciled.")


def reconcile(identifier: str, actual_usd: float) -> None:
    """Manual action after checking provider billing; never guesses a failed call's cost."""
    if not math.isfinite(actual_usd) or actual_usd < 0:
        raise ValueError("Confirmed charge must be non-negative and finite.")
    with _ledger() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""UPDATE spend_requests SET state='reconciled',actual_estimated_usd=?,
                failure='Manually reconciled against provider billing' WHERE id=? AND state='uncertain'""",
                (actual_usd, identifier))
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("No uncertain reservation has that ID.")
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
