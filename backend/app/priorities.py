"""Phase 3.4 transparent prioritization.

Measured parts come from stored data (via Phase 3.3 opportunities). PM estimates
(strategic relevance, effort, a note) and weights are optional, saved in a small local
SQLite file keyed by dataset version and source fingerprint, and always labelled as
estimates. Revenue, lifetime value, conversion and effort are never generated.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, env_path
from .dataset import read_meta
from .errors import InvalidRequest

PARTS = {
    "reach": ("Reach", "rank", "Primary feedback records (records, not distinct customers: no customer IDs exist)"),
    "recent": ("Recent frequency", "rank", "Records in the last 90 days of the data"),
    "negative": ("Negative sentiment", "share", "Share of records labelled Negative"),
    "support": ("Support pressure", "rank", "Linked support tickets weighted by severity (High = 2, Medium = 1)"),
    "evidence": ("Evidence checks", "share", "Evidence checklist points out of 4 (Phase 3.3)"),
}
DEFAULT_WEIGHTS = {"reach": 25, "recent": 20, "negative": 15, "support": 20, "evidence": 20}
STRATEGIC = {"low": 0.8, "medium": 1.0, "high": 1.2}
EFFORT = {"S": 1, "M": 2, "L": 3, "XL": 5}
TICKET_POINTS = {"High": 2, "Medium": 1}
NOTE_LIMIT = 500


def store_path() -> Path:
    return env_path("GIST_PRIORITIES_DB_PATH", ROOT / "backend" / "gist-priorities.sqlite3")


def _store() -> sqlite3.Connection:
    db = sqlite3.connect(store_path())
    db.executescript("""
    CREATE TABLE IF NOT EXISTS weights (dataset_key TEXT NOT NULL, part TEXT NOT NULL, weight INTEGER NOT NULL,
        PRIMARY KEY (dataset_key, part));
    CREATE TABLE IF NOT EXISTS inputs (dataset_key TEXT NOT NULL, opportunity_id TEXT NOT NULL, strategic TEXT,
        effort TEXT, note TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (dataset_key, opportunity_id));""")
    return db


def dataset_key(db: sqlite3.Connection) -> str:
    meta = read_meta(db) or {}
    return f"{meta.get('version', 'unknown')}:{meta.get('source_sha256', 'unknown')}"


def _rank_scores(values: list[float]) -> list[float]:
    """Mid-rank percentile, 0 = lowest, 100 = highest; ties share a score."""
    n = len(values)
    if n == 1:
        return [50.0]
    out = []
    for v in values:
        below = sum(x < v for x in values)
        equal = sum(x == v for x in values) - 1
        out.append(round(100 * (below + equal / 2) / (n - 1), 2))
    return out


def weights(key: str) -> dict[str, int]:
    with _store() as store:
        saved = dict(store.execute("SELECT part, weight FROM weights WHERE dataset_key = ?", (key,)))
    return {p: int(saved.get(p, DEFAULT_WEIGHTS[p])) for p in PARTS}


def set_weights(key: str, new: dict) -> dict[str, int]:
    if set(new) != set(PARTS):
        raise InvalidRequest("weights must name exactly: " + ", ".join(PARTS),
                             public_message="Weights must name exactly: " + ", ".join(PARTS) + ".")
    if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100 for v in new.values()) or sum(new.values()) == 0:
        raise InvalidRequest("weights must be whole numbers 0-100, not all zero",
                             public_message="Weights must be whole numbers from 0 to 100, and not all zero.")
    with _store() as store:
        store.executemany("INSERT OR REPLACE INTO weights VALUES (?, ?, ?)", [(key, p, v) for p, v in new.items()])
    return weights(key)


def reset_weights(key: str) -> dict[str, int]:
    with _store() as store:
        store.execute("DELETE FROM weights WHERE dataset_key = ?", (key,))
    return weights(key)


def set_input(key: str, opportunity_id: str, strategic, effort, note) -> dict:
    if strategic is not None and strategic not in STRATEGIC:
        raise InvalidRequest("bad strategic", public_message="Strategic relevance must be low, medium, high or empty.")
    if effort is not None and effort not in EFFORT:
        raise InvalidRequest("bad effort", public_message="Effort must be S, M, L, XL or empty.")
    if note is not None and (not isinstance(note, str) or len(note) > NOTE_LIMIT):
        raise InvalidRequest("bad note", public_message=f"The note must be text of at most {NOTE_LIMIT} characters.")
    note = (note or "").strip() or None
    with _store() as store:
        if strategic is None and effort is None and note is None:
            store.execute("DELETE FROM inputs WHERE dataset_key = ? AND opportunity_id = ?", (key, opportunity_id))
        else:
            store.execute("INSERT OR REPLACE INTO inputs VALUES (?, ?, ?, ?, ?, ?)",
                          (key, opportunity_id, strategic, effort, note, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return {"opportunity_id": opportunity_id, "strategic": strategic, "effort": effort, "note": note}


def _inputs(key: str) -> tuple[dict, int]:
    version = key.split(":", 1)[0]
    with _store() as store:
        rows = store.execute("SELECT opportunity_id, strategic, effort, note, updated_at FROM inputs WHERE dataset_key = ?", (key,)).fetchall()
        stale = store.execute("SELECT COUNT(*) FROM inputs WHERE dataset_key LIKE ? AND dataset_key != ?",
                              (version + ":%", key)).fetchone()[0]
    return {r[0]: {"strategic": r[1], "effort": r[2], "note": r[3], "updated_at": r[4]} for r in rows}, stale


def raw_parts(card: dict) -> dict[str, float]:
    return {"reach": card["frequency"]["records"], "recent": card["trend"]["recent_90_days"],
            "negative": card["severity_proxy"]["negative_share"],
            "support": sum(TICKET_POINTS.get(s, 1) * n for s, n in card["severity_proxy"]["tickets_by_severity"].items()),
            "evidence": card["confidence"]["points"] / 4}


def score(cards: list[dict], weight: dict[str, int], inputs: dict | None = None) -> list[dict]:
    """Pure scoring: one row per opportunity, sorted by priority (ties by ID)."""
    inputs = inputs or {}
    raws = [raw_parts(c) for c in cards]
    scaled = {}
    for part, (_, kind, _) in PARTS.items():
        values = [r[part] for r in raws]
        scaled[part] = _rank_scores(values) if kind == "rank" else [round(100 * v, 2) for v in values]
    total_weight = sum(weight.values())
    rows = []
    for i, card in enumerate(cards):
        parts = []
        for part, (label, kind, source) in PARTS.items():
            contribution = scaled[part][i] * weight[part] / total_weight
            parts.append({"part": part, "label": label, "raw": raws[i][part], "score": scaled[part][i], "weight": weight[part],
                          "contribution": round(contribution, 4), "scaling": kind, "source": source})
        evidence_score = round(sum(p["contribution"] for p in parts), 2)
        pm = inputs.get(card["id"], {})
        multiplier = STRATEGIC.get(pm.get("strategic"), 1.0)
        priority = round(evidence_score * multiplier, 2)
        effort = pm.get("effort")
        rows.append({"opportunity_id": card["id"], "title": card["title"], "problem": card["problem"],
                     "area": next(iter(card["areas"]), None), "measured": parts, "evidence_score": evidence_score,
                     "estimates": {"strategic": pm.get("strategic"), "strategic_multiplier": multiplier,
                                   "effort": effort, "effort_points": EFFORT.get(effort), "note": pm.get("note"),
                                   "updated_at": pm.get("updated_at")},
                     "priority": priority,
                     "priority_per_effort_point": round(priority / EFFORT[effort], 2) if effort else None})
    rows.sort(key=lambda r: (-r["priority"], r["opportunity_id"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def table(db: sqlite3.Connection, cards: list[dict]) -> dict:
    key = dataset_key(db)
    weight = weights(key)
    inputs, stale = _inputs(key)
    known = {c["id"] for c in cards}
    return {"dataset_key": key, "weights": weight, "default_weights": DEFAULT_WEIGHTS,
            "parts": [{"part": p, "label": l, "scaling": k, "source": s} for p, (l, k, s) in PARTS.items()],
            "strategic_multipliers": STRATEGIC, "effort_points": EFFORT,
            "rows": score(cards, weight, {k: v for k, v in inputs.items() if k in known}),
            "stale_inputs": stale + sum(k not in known for k in inputs),
            "formula": ("Evidence score = weighted mean of the measured parts (0–100). Priority = evidence score × "
                        "strategic multiplier (low 0.8, medium or not rated 1.0, high 1.2). Score per effort point is "
                        "shown only when you enter effort (S 1, M 2, L 3, XL 5)."),
            "interpretation": ("Measured parts come from stored synthetic data; strategic relevance and effort are your "
                               "estimates. Count-based parts are ranks among these opportunities, so scores are relative. "
                               "Revenue, lifetime value, conversion and engineering effort are not in the data and are "
                               "never estimated by Gist.")}
