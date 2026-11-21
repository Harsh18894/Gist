"""SQLite connection and schema."""
import sqlite3
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import database_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, customer_segment TEXT NOT NULL,
  subscription_tier TEXT NOT NULL, product_area TEXT NOT NULL,
  feedback_channel TEXT NOT NULL, feedback_text TEXT NOT NULL,
  sentiment TEXT NOT NULL, issue_category TEXT NOT NULL,
  related_feature TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS support_tickets (
  id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, customer_segment TEXT NOT NULL,
  subscription_tier TEXT NOT NULL, product_area TEXT NOT NULL,
  subject TEXT NOT NULL, description TEXT NOT NULL, severity TEXT NOT NULL,
  issue_category TEXT NOT NULL, related_feature TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
  published_at TEXT NOT NULL, path TEXT NOT NULL, content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_filters ON feedback(issue_category, customer_segment, timestamp);
CREATE INDEX IF NOT EXISTS idx_feedback_area ON feedback(product_area);
CREATE INDEX IF NOT EXISTS idx_tickets_area ON support_tickets(product_area);
CREATE VIRTUAL TABLE IF NOT EXISTS feedback_fts USING fts5(id UNINDEXED, feedback_text);
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
  source_date TEXT, segment TEXT, product_area TEXT,
  path TEXT NOT NULL, content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL, content TEXT NOT NULL, word_count INTEGER NOT NULL,
  UNIQUE(source_id, ordinal)
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(chunk_id UNINDEXED, content);
CREATE TABLE IF NOT EXISTS embeddings (
  chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  model TEXT NOT NULL, dimensions INTEGER NOT NULL, vector BLOB NOT NULL,
  PRIMARY KEY(chunk_id, model)
);
CREATE TABLE IF NOT EXISTS query_embedding_cache (
  cache_key TEXT PRIMARY KEY, dataset_version TEXT NOT NULL,
  source_sha256 TEXT NOT NULL, model TEXT NOT NULL,
  dimensions INTEGER NOT NULL, vector BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS api_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
  endpoint TEXT NOT NULL, model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL, estimated_cost_usd REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_filters ON sources(segment, product_area, source_date);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model);
"""


@contextmanager
def connection(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target)
    db.execute("PRAGMA foreign_keys = ON")
    db.row_factory = sqlite3.Row
    try:
        if path is None:
            has_meta = db.execute("SELECT name FROM sqlite_master WHERE name = 'dataset_meta'").fetchone()
            if not has_meta and os.getenv("GIST_DATASET_VERSION", "v1") == "v2" and db.execute("SELECT name FROM sqlite_master WHERE name = 'sources'").fetchone():
                raise RuntimeError(f"{target} is an unversioned legacy database. Refusing to read it as v2.")
            version_row = db.execute("SELECT value FROM dataset_meta WHERE key = 'version'").fetchone() if has_meta else None
            if version_row:
                selected = os.getenv("GIST_DATASET_VERSION", "v1")
                if selected != version_row[0]:
                    raise RuntimeError(f"Selected {selected}, but {target} contains {version_row[0]}. Set GIST_DATASET_VERSION and GIST_DB_PATH together.")
                source_root = Path(__file__).resolve().parents[2] / "data" / ("v2" if selected == "v2" else "")
                files = [source_root / "feedback.jsonl", source_root / "support-tickets.jsonl", *sorted((source_root / "prds").glob("*.md")), *sorted((source_root / "release-notes").glob("*.md"))]
                digest = hashlib.sha256(b"".join(item.read_bytes() for item in files)).hexdigest()
                recorded = db.execute("SELECT value FROM dataset_meta WHERE key = 'source_sha256'").fetchone()
                if recorded and recorded[0] != digest:
                    raise RuntimeError(f"{selected} source files changed since indexing. Reseed explicitly with --replace before retrieval.")
        yield db
    finally:
        db.close()


def initialize(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)
