"""Build the read-only data snapshot shipped with the public demo (Phase 5.3). No network, no API calls.

Copies (SQLite backup API, then VACUUM) into deploy/snapshot/:
  gist-v2.sqlite3              Pulse v2 index with the stored (already paid) embeddings
  gist-investigations.sqlite3  hash-chained audit log with the stored AI investigation runs
  gist-spend.sqlite3           spend ledger (project cost history)
  gist-ops.sqlite3             billing figures (feedback rows are cleared)
and writes manifest.json with SHA-256 hashes and the results of these checks:
  v2 source fingerprint verifies; audit chain verifies; no secrets or personal data.
The events database is not shipped: it is regenerated deterministically at start and checked
against the locked content hash.

  python deploy/make_snapshot.py [--replace]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
SNAPSHOT = ROOT / "deploy" / "snapshot"
SOURCES = {"gist-v2.sqlite3": ROOT / "backend/gist-v2.sqlite3", "gist-investigations.sqlite3": ROOT / "backend/gist-investigations.sqlite3",
           "gist-spend.sqlite3": ROOT / "backend/gist-spend.sqlite3", "gist-ops.sqlite3": ROOT / "backend/gist-ops.sqlite3"}
FORBIDDEN = {"home_path": re.compile(r"/Users/|/home/|C:\\\\Users", re.I), "email": re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I),
             "api_key": re.compile(r"sk-[A-Za-z0-9_-]{16,}")}
EXTRA_FORBIDDEN_ENV = "GIST_SNAPSHOT_FORBIDDEN"   # optional comma-separated words, e.g. the owner's name


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(source: Path, target: Path) -> None:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.execute("VACUUM")
    dst.close()


def privacy_scan(path: Path, words: list[str]) -> list[str]:
    patterns = dict(FORBIDDEN, **{f"word:{w}": re.compile(re.escape(w), re.I) for w in words})
    problems = []
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
            cols = [c[1] for c in db.execute(f"PRAGMA table_info({table})")]
            for row in db.execute(f"SELECT * FROM {table}"):
                for col, value in zip(cols, row):
                    if isinstance(value, str):
                        problems += [f"{path.name}:{table}.{col}: {name}" for name, p in patterns.items() if p.search(value)]
    return sorted(set(problems))


def check(snapshot: Path) -> dict:
    """Verify a snapshot folder; returns facts for the manifest or raises SystemExit."""
    os.environ.update({"GIST_DATASET_VERSION": "v2", "GIST_DB_PATH": str(snapshot / "gist-v2.sqlite3"),
                       "GIST_INVESTIGATIONS_DB_PATH": str(snapshot / "gist-investigations.sqlite3")})
    from app.database import connection
    from app.investigate import audit
    with connection() as db:                      # raises if the v2 source fingerprint does not match data/v2
        meta = dict(db.execute("SELECT key, value FROM dataset_meta"))
        vectors = db.execute("SELECT COUNT(*) FROM embeddings WHERE model = 'text-embedding-3-small'").fetchone()[0]
    chain = audit.verify()
    with sqlite3.connect(f"file:{snapshot / 'gist-investigations.sqlite3'}?mode=ro", uri=True) as db:
        ai_runs = db.execute("SELECT COUNT(*) FROM investigations WHERE report != 'null'").fetchone()[0]
    with sqlite3.connect(f"file:{snapshot / 'gist-spend.sqlite3'}?mode=ro", uri=True) as db:
        uncertain = db.execute("SELECT COUNT(*) FROM spend_requests WHERE state = 'uncertain'").fetchone()[0]
    words = [w.strip() for w in os.getenv(EXTRA_FORBIDDEN_ENV, "").split(",") if w.strip()]
    privacy = [p for name in SOURCES for p in privacy_scan(snapshot / name, words)]
    problems = ([] if chain["ok"] else ["audit chain does not verify"]) + (["learned vectors missing"] if not vectors else []) + \
               (["uncertain spend requests present"] if uncertain else []) + privacy
    if problems:
        raise SystemExit("Snapshot check failed: " + "; ".join(problems))
    lock = json.loads((ROOT / "evals/phase44/lock.json").read_text())["fingerprint"]
    return {"dataset_version": meta.get("version"), "source_sha256": meta.get("source_sha256"), "learned_vectors": vectors,
            "audit_entries": chain["entries"], "stored_ai_investigations": ai_runs,
            "events_content_sha256": lock["events_content_sha256"], "privacy_scan": "clean", "extra_words_checked": len(words)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if (SNAPSHOT / "manifest.json").exists() and not args.replace:
        raise SystemExit(f"{SNAPSHOT.relative_to(ROOT)} exists; pass --replace to rebuild it.")
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    for name, source in SOURCES.items():
        target = SNAPSHOT / name
        if target.exists():
            target.unlink()
        copy(source, target)
    with sqlite3.connect(SNAPSHOT / "gist-ops.sqlite3") as db:   # local feedback is not published
        db.execute("DELETE FROM feedback")
    sqlite3.connect(SNAPSHOT / "gist-ops.sqlite3").execute("VACUUM")
    facts = check(SNAPSHOT)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "checks": facts,
                "files": {name: {"sha256": sha256(SNAPSHOT / name), "bytes": (SNAPSHOT / name).stat().st_size} for name in SOURCES}}
    (SNAPSHOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
