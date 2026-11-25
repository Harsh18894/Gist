"""The real spend ledger stays out of tests, and every ledger connection closes."""
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.rag import budget

from conftest import CLEARED_ENV, REAL_LEDGER


def test_tests_never_resolve_the_real_ledger_or_paid_env():
    path = budget._path().resolve()
    assert path != REAL_LEDGER.resolve()
    assert path.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert not any(name in os.environ for name in CLEARED_ENV)


def test_shell_exports_do_not_reach_tests():
    # The autouse fixture runs before this test body; anything a developer
    # exported in their shell has already been removed.
    assert os.getenv("GIST_ENABLE_PAID_API") is None
    assert os.getenv("OPENAI_API_KEY") is None
    assert os.getenv("GIST_DATASET_VERSION") is None


def test_every_ledger_connection_is_closed(monkeypatch):
    opened: list[sqlite3.Connection] = []
    closed: list[sqlite3.Connection] = []

    class Tracking(sqlite3.Connection):
        def close(self) -> None:
            closed.append(self)
            super().close()

    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, factory=Tracking, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(budget.sqlite3, "connect", tracking_connect)
    identifier = budget.reserve("embeddings", "test", 0.001, "close-a")
    budget.finish(identifier, state="uncertain", failure="test")
    budget.reconcile(identifier, 0.0)
    assert budget.summary()["requests"] == 1
    with pytest.raises(ValueError):
        budget.reserve("embeddings", "test", 0.001, "close-a")  # duplicate key: rollback path
    with pytest.raises(ValueError):
        budget.reconcile(identifier, 0.0)  # already reconciled: rollback path
    assert len(opened) == 6
    assert len(closed) == len(opened)
    assert [c for c in opened if c not in closed] == []


def test_ledger_transactions_still_commit_after_closing():
    identifier = budget.reserve("responses", "test", 0.002, "commit-a")
    budget.finish(identifier, state="completed", actual=0.001, input_tokens=3, output_tokens=2, latency_ms=5)
    with sqlite3.connect(budget._path()) as db:
        row = db.execute("SELECT state, actual_estimated_usd, input_tokens FROM spend_requests WHERE id = ?",
                         (identifier,)).fetchone()
    assert row == ("completed", 0.001, 3)
    assert budget.summary()["committed_or_reserved_usd"] == 0.001
