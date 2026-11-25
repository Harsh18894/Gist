"""Golden tests for the shared dataset fingerprint in `app.dataset`.

The fingerprint is recorded in seeded databases and in frozen benchmark
artifacts (split manifest, retrieval lock, Phase 2.1 benchmarks). Changing the
file order, glob, or byte joining changes the value and invalidates all of
them, and the frozen held-out set cannot be re-run to re-bless a new value.
Do not change the algorithm; if these tests fail, revert the change.
"""
import json
from pathlib import Path

import pytest

from app.config import ROOT, database_path
from app.database import connection
from app.dataset import (DATASETS, default_db_path, fingerprint, require_complete, source_dir,
                         source_files)
from app.errors import DatasetStateError

V1_FINGERPRINT = "482a605903f9720781f66bed39c923edfe759769c169cd1e2309c260403b89e7"
V2_FINGERPRINT = "f7f810d6949673611e9b434baf1717d4aa6c1637f1a309745cfb8789fd243d7f"
DOCS = [f"prds/prd-0{i}.md" for i in range(1, 7)] + [f"release-notes/release-0{i}.md" for i in range(1, 9)]
EXPECTED_FILES = {
    "v1": [f"data/{name}" for name in ("feedback.jsonl", "support-tickets.jsonl", *DOCS)],
    "v2": [f"data/v2/{name}" for name in ("feedback.jsonl", "support-tickets.jsonl", *DOCS)],
}


@pytest.mark.parametrize("version", DATASETS)
def test_source_file_list_and_order_are_pinned(version):
    files = source_files(source_dir(version))
    assert [str(path.relative_to(ROOT)) for path in files] == EXPECTED_FILES[version]
    assert require_complete(files, version) == files


def test_fingerprints_match_recorded_values():
    assert fingerprint(source_files(source_dir("v1"))) == V1_FINGERPRINT
    assert fingerprint(source_files(source_dir("v2"))) == V2_FINGERPRINT


def test_v2_fingerprint_matches_every_frozen_artifact():
    artifacts = ["evals/v2/split-manifest.json", "evals/v2/retrieval-lock.json",
                 "evals/phase21/benchmark-v2-draft.json", "evals/phase21/benchmark.json"]
    for artifact in artifacts:
        assert json.loads((ROOT / artifact).read_text())["source_sha256"] == V2_FINGERPRINT, artifact


def test_scripts_delegate_to_the_shared_fingerprint():
    from scripts.freeze_v2_split import source_hash
    from scripts.import_phase21_review import corpus

    assert source_hash() == V2_FINGERPRINT
    assert corpus()[1] == V2_FINGERPRINT


def test_default_db_paths_are_shared(monkeypatch):
    assert default_db_path("v1") == ROOT / "backend/gist.sqlite3"
    assert default_db_path("v2") == ROOT / "backend/gist-v2.sqlite3"
    monkeypatch.delenv("GIST_DB_PATH", raising=False)
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    assert database_path() == default_db_path("v2")
    # run_v2_retrieval.py is hash-locked and keeps its own constant; it must agree.
    # It imports sibling scripts by bare name, as when run directly.
    monkeypatch.syspath_prepend(str(ROOT / "backend/scripts"))
    from scripts.run_v2_retrieval import DB as LOCKED_DB
    assert LOCKED_DB == default_db_path("v2")


def test_incomplete_source_set_is_rejected(tmp_path: Path):
    (tmp_path / "prds").mkdir()
    (tmp_path / "release-notes").mkdir()
    (tmp_path / "feedback.jsonl").write_text("{}\n")
    with pytest.raises(DatasetStateError, match="Incomplete v2 source dataset") as caught:
        require_complete(source_files(tmp_path), "v2")
    assert caught.value.code == "source_files_missing"
    assert isinstance(caught.value, FileNotFoundError)  # seed.py callers and tests catch this


def test_missing_source_file_at_request_time_is_a_dataset_error(tmp_path: Path, monkeypatch):
    from scripts.seed import seed
    import app.database as database_module

    path = tmp_path / "v1.sqlite3"
    seed("v1", path=path)
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    fake_root = tmp_path / "root"
    (fake_root / "data").mkdir(parents=True)
    monkeypatch.setattr(database_module, "ROOT", fake_root)
    with pytest.raises(DatasetStateError) as caught:
        with connection():
            pass
    assert caught.value.code == "source_files_missing"
