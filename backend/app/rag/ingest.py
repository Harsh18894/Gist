"""Local source ingestion, cleaning, chunking, and demo vector indexing."""
import csv
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

DEMO_MODEL = "gist-demo-hash-v1"
DEMO_DIMENSIONS = 256
MAX_FILE_BYTES = 5_000_000
STOPWORDS = {"a", "about", "an", "and", "are", "area", "as", "at", "be", "by", "customer", "customers", "did", "do", "does", "for", "from", "gist", "how", "in", "is", "it", "many", "of", "on", "or", "our", "owns", "product", "pulse", "saying", "the", "to", "was", "were", "what", "when", "which", "who", "with"}


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    kind: str
    content: str
    path: str
    source_date: str | None = None
    segment: str | None = None
    product_area: str | None = None


def clean_text(value: str) -> str:
    """Remove control characters and normalize whitespace without changing words."""
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def chunk_text(value: str, max_words: int = 140, overlap_words: int = 25) -> list[str]:
    if max_words < 1 or overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("Chunk size must exceed overlap and be positive.")
    words = clean_text(value).split()
    if not words:
        return []
    step = max_words - overlap_words
    return [" ".join(words[start:start + max_words]) for start in range(0, len(words), step)
            if start == 0 or start + overlap_words < len(words)]


def demo_vector(value: str) -> np.ndarray:
    """Deterministic lexical hash vector for the no-key demo; not a learned embedding."""
    vector = np.zeros(DEMO_DIMENSIONS, dtype=np.float32)
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if token in STOPWORDS or len(token) < 2:
            continue
        digest = hashlib.blake2b(token.encode(), digest_size=4).digest()
        index = int.from_bytes(digest[:2], "little") % DEMO_DIMENSIONS
        vector[index] += 1.0 if digest[2] % 2 == 0 else -1.0
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def _date(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value[:10]
    date.fromisoformat(normalized)
    return normalized


def upsert_source(db: sqlite3.Connection, source: Source) -> int:
    content = clean_text(source.content)
    if not content:
        raise ValueError(f"Source {source.id} has no text.")
    existing = db.execute("""SELECT title,kind,source_date,segment,product_area,path,content
        FROM sources WHERE id=?""", (source.id,)).fetchone()
    fields = (source.title, source.kind, _date(source.source_date), source.segment,
              source.product_area, source.path, source.content)
    if existing is not None and tuple(existing) == fields:
        # Re-importing identical content must not delete paid cached vectors.
        return db.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (source.id,)).fetchone()[0]
    if existing is not None and existing["title"] == source.title and clean_text(existing["content"]) == content:
        # Metadata changes do not alter chunk text or its cached embedding.
        db.execute("""UPDATE sources SET kind=?,source_date=?,segment=?,product_area=?,path=?,content=?
            WHERE id=?""", (source.kind, _date(source.source_date), source.segment,
                            source.product_area, source.path, source.content, source.id))
        return db.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (source.id,)).fetchone()[0]
    old_ids = [row[0] for row in db.execute("SELECT id FROM chunks WHERE source_id = ?", (source.id,))]
    for chunk_id in old_ids:
        db.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (chunk_id,))
    db.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE source_id = ?)", (source.id,))
    db.execute("DELETE FROM chunks WHERE source_id = ?", (source.id,))
    db.execute("""INSERT INTO sources (id,title,kind,source_date,segment,product_area,path,content)
        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
        title=excluded.title,kind=excluded.kind,source_date=excluded.source_date,
        segment=excluded.segment,product_area=excluded.product_area,path=excluded.path,content=excluded.content""",
        (source.id, source.title, source.kind, _date(source.source_date), source.segment, source.product_area, source.path, source.content))
    chunks = chunk_text(f"{source.title}. {content}")
    for ordinal, chunk in enumerate(chunks):
        chunk_id = f"{source.id}:{ordinal:03d}"
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (chunk_id, source.id, ordinal, chunk, len(chunk.split())))
        db.execute("INSERT INTO chunk_fts (chunk_id, content) VALUES (?,?)", (chunk_id, chunk))
        vector = demo_vector(chunk)
        db.execute("INSERT INTO embeddings VALUES (?,?,?,?)", (chunk_id, DEMO_MODEL, DEMO_DIMENSIONS, vector.tobytes()))
    return len(chunks)


def index_seed_data(db: sqlite3.Connection, dataset_version: str = "v1") -> tuple[int, int]:
    """Rebuild the synthetic search corpus from Phase 1 tables."""
    db.execute("DELETE FROM chunk_fts")
    db.execute("DELETE FROM embeddings")
    db.execute("DELETE FROM chunks")
    db.execute("DELETE FROM sources")
    sources: list[Source] = []
    for row in db.execute("SELECT * FROM documents ORDER BY id"):
        content = row["content"]
        area = next((line.split(": ", 1)[1] for line in content.splitlines() if line.startswith("Product area: ")), None)
        sources.append(Source(row["id"], row["title"], row["kind"], content, row["path"], row["published_at"], product_area=area))
    prefix = "data/v2" if dataset_version == "v2" else "data"
    for row in db.execute("SELECT * FROM feedback ORDER BY id"):
        title = f"Feedback {row['id']}" if dataset_version == "v2" else f"{row['issue_category']} feedback {row['id']}"
        sources.append(Source(row["id"], title, "feedback", row["feedback_text"],
                              f"{prefix}/feedback.jsonl#{row['id']}", row["timestamp"], row["customer_segment"], row["product_area"]))
    for row in db.execute("SELECT * FROM support_tickets ORDER BY id"):
        sources.append(Source(row["id"], row["subject"], "support_ticket", row["description"],
                              f"{prefix}/support-tickets.jsonl#{row['id']}", row["timestamp"], row["customer_segment"], row["product_area"]))
    count = sum(upsert_source(db, source) for source in sources)
    return len(sources), count


def _field(row: dict[str, str], *names: str) -> str | None:
    return next((row[name].strip() for name in names if row.get(name) and row[name].strip()), None)


def import_file(db: sqlite3.Connection, path: Path, *, segment: str | None = None,
                product_area: str | None = None, source_date: str | None = None) -> tuple[int, int]:
    """Import a local synthetic .csv, .txt, or .md file. Metadata flags are fallbacks."""
    path = path.resolve()
    if path.suffix.lower() not in {".csv", ".txt", ".md"}:
        raise ValueError("Supported formats are CSV, TXT, and Markdown.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Source file exceeds the 5 MB local limit.")
    raw = path.read_text(encoding="utf-8-sig")
    identity = hashlib.sha256(str(path).encode()).hexdigest()[:12]
    sources: list[Source] = []
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(raw.splitlines())
        if not reader.fieldnames or not set(reader.fieldnames) & {"text", "content", "feedback_text", "description"}:
            raise ValueError("CSV needs a text, content, feedback_text, or description column.")
        for index, row in enumerate(reader, 1):
            body = _field(row, "text", "content", "feedback_text", "description")
            if not body:
                continue
            sources.append(Source(f"csv-{identity}-{index:04d}", _field(row, "title", "subject") or f"{path.stem} row {index}",
                                  "csv", body, f"{path}#row={index}", _field(row, "source_date", "date", "timestamp", "published_at") or source_date,
                                  _field(row, "segment", "customer_segment") or segment, _field(row, "product_area") or product_area))
    else:
        lines = raw.splitlines()
        title = next((line.lstrip("# ").strip() for line in lines if line.startswith("# ")), path.stem)
        metadata = {key.lower(): value.strip() for line in lines if ": " in line for key, value in [line.split(": ", 1)]}
        sources.append(Source(f"file-{identity}", title, "markdown" if path.suffix.lower() == ".md" else "text",
                              raw, str(path), metadata.get("published") or metadata.get("date") or source_date,
                              metadata.get("segment") or segment, metadata.get("product area") or product_area))
    chunks = sum(upsert_source(db, source) for source in sources)
    return len(sources), chunks
