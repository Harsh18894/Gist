"""Environment-based Gist configuration."""
import os
from pathlib import Path

from .errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[2]


def env_path(var: str, default: Path) -> Path:
    """Path from an environment variable; relative values resolve against the repository root.

    An unset or empty variable gives ``default``.
    """
    value = os.getenv(var)
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def database_path() -> Path:
    dataset = os.getenv("GIST_DATASET_VERSION", "v1")
    if dataset not in {"v1", "v2"}:
        raise ConfigurationError("GIST_DATASET_VERSION must be v1 or v2",
                                 public_message="GIST_DATASET_VERSION must be v1 or v2. Fix the API environment and restart it.")
    from .dataset import default_db_path  # local import: app.dataset imports ROOT from here

    return env_path("GIST_DB_PATH", default_db_path(dataset))


def cors_origin() -> str:
    return os.getenv("GIST_CORS_ORIGIN", "http://localhost:3000")
