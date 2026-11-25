"""Initialize and replace local SQLite data from synthetic files."""
import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import connection, initialize  # noqa: E402
from app.dataset import default_db_path, fingerprint as source_fingerprint, require_complete, source_dir, source_files  # noqa: E402
from app.rag.ingest import index_seed_data  # noqa: E402


def seed(dataset: str = "v1", *, path: Path | None = None, replace: bool = False) -> None:
    if dataset not in {"v1", "v2"}:
        raise ValueError("Dataset must be v1 or v2.")
    # Uses this module's ROOT (tests redirect it) and the dataset argument, not
    # GIST_DATASET_VERSION, to pick the default database.
    data = source_dir(dataset, ROOT)
    target = path or (Path(os.environ["GIST_DB_PATH"]) if "GIST_DB_PATH" in os.environ else default_db_path(dataset, ROOT))
    if not target.is_absolute():
        target = ROOT / target
    if target.exists() and not replace:
        raise FileExistsError(f"{target} already exists. Choose a new path or pass --replace explicitly.")
    if target.exists():
        with closing(sqlite3.connect(target)) as existing_db:
            names = {row[0] for row in existing_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            prior = existing_db.execute("SELECT value FROM dataset_meta WHERE key='version'").fetchone() if "dataset_meta" in names else None
            if prior and prior[0] != dataset:
                raise ValueError(f"Refusing to replace {prior[0]} database with {dataset} data.")
            if not prior and dataset == "v2" and "feedback" in names and existing_db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]:
                raise ValueError("Refusing to replace an unversioned existing corpus with v2 data.")
    files = require_complete(source_files(data), dataset)
    fingerprint = source_fingerprint(files)
    with connection(target) as db:
        initialize(db)
        with db:
            existing = db.execute("SELECT value FROM dataset_meta WHERE key = 'version'").fetchone()
            if existing and existing[0] != dataset:
                raise ValueError(f"Refusing to replace {existing[0]} database with {dataset} data.")
            if not existing and dataset == "v2" and db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]:
                raise ValueError("Refusing to replace an unversioned existing corpus with v2 data.")
            db.execute("DELETE FROM feedback_fts")
            db.execute("DELETE FROM feedback")
            db.execute("DELETE FROM support_tickets")
            db.execute("DELETE FROM documents")
            feedback = [json.loads(line) for line in (data / "feedback.jsonl").read_text().splitlines()]
            tickets = [json.loads(line) for line in (data / "support-tickets.jsonl").read_text().splitlines()]
            feedback_columns = ["id", "timestamp", "customer_segment", "subscription_tier", "product_area", "feedback_channel", "feedback_text", "sentiment", "issue_category", "related_feature"]
            db.executemany("INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?)", [tuple(row[column] for column in feedback_columns) for row in feedback])
            db.executemany("INSERT INTO feedback_fts (id, feedback_text) VALUES (?,?)", [(row["id"], row["feedback_text"]) for row in feedback])
            ticket_columns = ["id", "timestamp", "customer_segment", "subscription_tier", "product_area", "subject", "description", "severity", "issue_category", "related_feature", "status"]
            db.executemany("INSERT INTO support_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?)", [tuple(row[column] for column in ticket_columns) for row in tickets])
            docs = []
            for kind, folder in [("prd", "prds"), ("release_note", "release-notes")]:
                for path in sorted((data / folder).glob("*.md")):
                    content = path.read_text()
                    published = next(line.split(": ", 1)[1] for line in content.splitlines() if line.startswith("Published:"))
                    docs.append((path.stem, kind, content.splitlines()[0][2:], published, str(path.relative_to(ROOT)), content))
            db.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?)", docs)
            source_count, chunk_count = index_seed_data(db, dataset)
            db.execute("INSERT OR REPLACE INTO dataset_meta VALUES ('version', ?)", (dataset,))
            db.execute("INSERT OR REPLACE INTO dataset_meta VALUES ('source_sha256', ?)", (fingerprint,))
    print(f"Seeded {dataset} at {target}: {len(feedback)} feedback, {len(tickets)} tickets, {len(docs)} documents; indexed {source_count} sources in {chunk_count} chunks.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a versioned synthetic Pulse database.")
    parser.add_argument("--dataset", choices=["v1", "v2"], default="v1")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--replace", action="store_true", help="Explicitly replace an existing database; clears its indexed embeddings.")
    args = parser.parse_args()
    seed(args.dataset, path=args.db, replace=args.replace)
