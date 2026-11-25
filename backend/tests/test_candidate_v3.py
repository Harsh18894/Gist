"""Experimental candidate retriever: bounded config, generic splitting, MMR diversity."""
import sqlite3

import numpy as np
import pytest

from app.database import initialize
from app.rag.candidate_v3 import CandidateConfig, retrieve, split_question
from app.rag.retrieval import Filters


def _db(rows):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    initialize(db)
    for sid, kind, text, vector in rows:
        db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)", (sid, sid, kind, None, None, None, "x", text))
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (f"{sid}:000", sid, 0, text, len(text.split())))
        db.execute("INSERT INTO chunk_fts VALUES (?,?)", (f"{sid}:000", text))
        vec = np.asarray(vector, dtype=np.float32)
        db.execute("INSERT INTO embeddings VALUES (?,?,?,?)", (f"{sid}:000", "m", len(vec), (vec / np.linalg.norm(vec)).tobytes()))
    return db


def test_config_is_bounded():
    with pytest.raises(ValueError):
        CandidateConfig(max_subqueries=9)
    with pytest.raises(ValueError):
        CandidateConfig(mmr_lambda=1.5)


def test_split_only_for_multi_part_questions():
    assert split_question("Where is the export button?") == []
    assert split_question("How do we separate slow exports from failed webhook deliveries?") == [
        "How do we separate slow exports", "failed webhook deliveries"]


def test_mmr_promotes_a_distinct_viewpoint_and_keeps_filters():
    db = _db([("a1", "feedback", "export slow export slow", [1, 0, 0]),
              ("a2", "feedback", "export slow again", [0.99, 0.01, 0]),
              ("a3", "feedback", "export slow today", [0.98, 0.02, 0]),
              ("b1", "feedback", "delivery hook failed", [0, 1, 0])])
    query = np.asarray([0.95, 0.31, 0], dtype=np.float32)
    plain, _ = retrieve(db, "export slow webhook", Filters(), query, "m", CandidateConfig())
    diverse, trace = retrieve(db, "export slow webhook", Filters(), query, "m", CandidateConfig(mmr_lambda=0.5))
    assert set(plain) == set(diverse) and trace["mmr"]
    assert plain.index("b1") == 3 and diverse.index("b1") < 3
    assert retrieve(db, "export", Filters(segment="Enterprise"), query, "m", CandidateConfig(mmr_lambda=0.5))[0] == []
