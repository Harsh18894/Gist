"""Shared test helpers for data that is not part of every checkout."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# The Pulse v2 index with stored embeddings: the local database if present, otherwise the identical
# read-only copy shipped in the deployment snapshot. Tests that write through the app copy it first.
def _has_index(path: Path) -> bool:
    """True for a populated Pulse index (an empty file left by a failed open does not count)."""
    import sqlite3
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            return db.execute("SELECT name FROM sqlite_master WHERE name = 'feedback'").fetchone() is not None
    except sqlite3.Error:
        return False


V2_DB = next((p for p in (ROOT / "backend/gist-v2.sqlite3", ROOT / "deploy/snapshot/gist-v2.sqlite3") if _has_index(p)),
             ROOT / "backend/gist-v2.sqlite3")

# The owner's review sheets (filled-in human reviews) are kept out of the public repository.
# Tests of the review and benchmark-freezing tooling need them and are skipped without them.
PRIVATE_REVIEW_FILES = [
    "evals/phase21/reviewed-v3/review-report.json",
    "evals/phase21/results/benchmark3-answer-claim-review-completed.csv",
    "evals/phase22/reviewed-v4/review-report.json",
    "evals/phase22/Gist_Benchmark4_Draft2_Questions_for_Human_Review.csv",
    "evals/phase23/reviewed-v5/review-report.json",
    "evals/phase23/Gist_Benchmark5_Questions_for_Human_Review.csv",
]
HAS_PRIVATE_REVIEWS = all((ROOT / p).exists() for p in PRIVATE_REVIEW_FILES)


def require_private():
    return pytest.mark.skipif(not HAS_PRIVATE_REVIEWS,
                              reason="needs the owner's private review sheets, which are not in the public repository")
