"""Benchmark-3 retrieval lock and one-time held-out guards; no retrieval or network."""
import pytest

from app.rag.candidate_v3 import LOCKED_CONFIG
from scripts import evaluate_benchmark3_heldout as heldout
from scripts import lock_benchmark3_retrieval as lock


def test_locked_config_is_mmr_0_7():
    assert LOCKED_CONFIG.mmr_lambda == 0.7 and not LOCKED_CONFIG.decompose and not LOCKED_CONFIG.document_slot


def test_lock_create_verify_and_tamper_detection(tmp_path, monkeypatch):
    path = tmp_path / "lock.json"
    lock.create(path)
    assert lock.verify_lock(path)["locked_config"]["mmr_lambda"] == 0.7
    with pytest.raises(FileExistsError):
        lock.create(path)
    original = lock._sha
    monkeypatch.setattr(lock, "_sha", lambda p: "changed" if p.name == "candidate_v3.py" else original(p))
    with pytest.raises(ValueError, match="files_sha256"):
        lock.verify_lock(path)


def test_heldout_selection_and_run_guards(tmp_path, monkeypatch):
    manifest, questions = heldout.heldout_questions()
    assert [q["id"] for q in questions] == manifest["heldout_ids"]
    def refuse():
        raise ValueError("lock changed")
    monkeypatch.setattr(heldout, "verify_lock", refuse)
    with pytest.raises(ValueError, match="lock changed"):
        heldout.run()
    monkeypatch.setattr(heldout, "verify_lock", lambda: {"lock_sha256": "x"})
    existing = tmp_path / "done.json"
    existing.write_text("{}")
    monkeypatch.setattr(heldout, "RESULT", existing)
    with pytest.raises(FileExistsError, match="already run once"):
        heldout.run()
