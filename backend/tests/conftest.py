"""Shared test setup. Every test runs offline and away from the real spend ledger.

`backend/gist-spend.sqlite3` is the project's only record of paid API spend.
Tests must never read or write it:

* At import time (before collection and any module- or session-scoped fixture)
  `GIST_SPEND_DB_PATH` points at a throwaway session ledger. Subprocesses that
  inherit `os.environ` get it too; a subprocess built with a fresh `env={}`
  would fall back to the real path, so always start from `os.environ`.
* The autouse `_offline_env` fixture gives each test its own empty ledger and
  clears paid-mode and dataset variables a developer may have exported. Tests
  that need one set it with `monkeypatch.setenv` inside the test.
* After each test, the real ledger's size and mtime must be unchanged.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

REAL_LEDGER = ROOT / "backend" / "gist-spend.sqlite3"
os.environ["GIST_SPEND_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="gist-test-ledger-")) / "spend.sqlite3")

from app.main import app  # noqa: E402
from scripts.seed import seed  # noqa: E402

CLEARED_ENV = ("GIST_ENABLE_PAID_API", "GIST_PAID_EVAL_APPROVED", "OPENAI_API_KEY",
               "GIST_MAX_API_SPEND_USD", "GIST_LLM_MODEL", "GIST_LLM_INPUT_USD_PER_M",
               "GIST_LLM_OUTPUT_USD_PER_M", "GIST_DATASET_VERSION")


def _ledger_state() -> tuple[int, int] | None:
    try:
        stat = REAL_LEDGER.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GIST_SPEND_DB_PATH", str(tmp_path / "spend.sqlite3"))
    for name in CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    before = _ledger_state()
    yield
    assert _ledger_state() == before, (
        f"{REAL_LEDGER} changed during this test. Tests must use a temporary GIST_SPEND_DB_PATH. "
        "If you were running the app or a paid script against the real ledger at the same time, rerun the tests.")


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIST_DB_PATH", str(tmp_path / "test.sqlite3"))
    seed()
    with TestClient(app) as test_client:
        yield test_client
