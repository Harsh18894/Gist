import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402
from scripts.seed import seed  # noqa: E402


@pytest.fixture
def client(tmp_path: Path):
    old = os.environ.get("GIST_DB_PATH")
    os.environ["GIST_DB_PATH"] = str(tmp_path / "test.sqlite3")
    seed()
    with TestClient(app) as test_client:
        yield test_client
    if old is None:
        os.environ.pop("GIST_DB_PATH", None)
    else:
        os.environ["GIST_DB_PATH"] = old
