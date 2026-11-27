"""The one definition of a Pulse dataset's source files, fingerprint, and default database.

The fingerprint is recorded in seeded databases and frozen benchmark artifacts.
Do not change the file order, glob, or byte joining: any change invalidates
every recorded value. `backend/tests/test_dataset_fingerprint.py` pins it.

Functions take directories from the caller (rather than reading a module ROOT)
so scripts and tests that redirect their data folder keep working.
"""
import hashlib
import sqlite3
from pathlib import Path

from .config import ROOT
from .errors import SourceFilesMissing

DATASETS = ("v1", "v2")
SOURCE_FILE_COUNT = 16


def source_dir(version: str, root: Path = ROOT) -> Path:
    return root / "data" / ("v2" if version == "v2" else "")


def source_files(data_dir: Path) -> list[Path]:
    """Two JSONL files, then PRDs, then release notes, each sorted by path."""
    return [data_dir / "feedback.jsonl", data_dir / "support-tickets.jsonl",
            *sorted((data_dir / "prds").glob("*.md")), *sorted((data_dir / "release-notes").glob("*.md"))]


def require_complete(files: list[Path], version: str) -> list[Path]:
    if len(files) != SOURCE_FILE_COUNT or not all(path.is_file() for path in files):
        data_dir = files[0].parent if files else Path("?")
        raise SourceFilesMissing(
            f"Incomplete {version} source dataset in {data_dir}.",
            public_message=f"The Pulse {version} source files on the API server are incomplete. "
                           "Restore the data folder, then restart the API.")
    return files


def fingerprint(files: list[Path]) -> str:
    return hashlib.sha256(b"".join(path.read_bytes() for path in files)).hexdigest()


def default_db_path(version: str, root: Path = ROOT) -> Path:
    return root / "backend" / f"gist{'-v2' if version == 'v2' else ''}.sqlite3"


def read_meta(db: sqlite3.Connection) -> dict[str, str] | None:
    """The seeded database's ``dataset_meta`` rows, or None when the table does not exist."""
    if not db.execute("SELECT name FROM sqlite_master WHERE name = 'dataset_meta'").fetchone():
        return None
    return dict(db.execute("SELECT key, value FROM dataset_meta"))
