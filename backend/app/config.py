"""Environment-based Gist configuration."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def database_path() -> Path:
    dataset = os.getenv("GIST_DATASET_VERSION", "v1")
    if dataset not in {"v1", "v2"}:
        raise ValueError("GIST_DATASET_VERSION must be v1 or v2")
    value = os.getenv("GIST_DB_PATH", f"backend/gist{'-v2' if dataset == 'v2' else ''}.sqlite3")
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def cors_origin() -> str:
    return os.getenv("GIST_CORS_ORIGIN", "http://localhost:3000")
