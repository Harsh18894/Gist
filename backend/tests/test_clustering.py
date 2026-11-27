"""Phase 3.2 clustering: deterministic mechanics, no annotations, no network."""
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from app import clustering
from scripts import evaluate_clustering as evaluation
from helpers import V2_DB, require_private  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def test_average_linkage_merges_close_vectors_and_stops_at_threshold():
    vectors = clustering._normalize(np.array([[1, 0], [0.99, 0.05], [0, 1], [0.05, 0.99]], dtype=np.float32))
    labels = clustering.average_linkage(vectors, 0.9)
    assert labels[0] == labels[1] and labels[2] == labels[3] and labels[0] != labels[2]
    assert len(set(clustering.average_linkage(vectors, 0.0))) == 1


def test_boilerplate_needs_repetition_across_areas():
    records = [{"text": f"Export broke. I'm reporting this after our weekly planning session.", "area": a}
               for a in ("Billing", "Dashboard", "Onboarding")] + [{"text": "Export broke again today.", "area": "Billing"}]
    filler = clustering.boilerplate(records)
    assert "i m reporting this after our weekly planning session" in filler
    assert clustering.clean("Invoice wrong. I'm reporting this after our weekly planning session.", filler) == "Invoice wrong."


def test_config_validation():
    with pytest.raises(ValueError):
        clustering.ClusterConfig(method="kmeans")
    with pytest.raises(ValueError):
        clustering.ClusterConfig(threshold=1.5)


def test_cluster_output_is_explained_and_deterministic():
    with sqlite3.connect(f"file:{V2_DB}?mode=ro", uri=True) as db:
        config = clustering.ClusterConfig("tfidf", 0.3, 3, 0.45, remove_boilerplate=True)
        first, second = clustering.cluster(db, config), clustering.cluster(db, config)
    assert first == second and first["records"] == 400
    for c in first["clusters"]:
        assert c["label"] and c["representative_ids"] and c["size"] >= 3
        assert c["size"] + c["secondary_members"] == len(c["members"])
        assert all(m["membership"] in {"primary", "secondary"} for m in c["members"])
    ids = {m["id"] for c in first["clusters"] for m in c["members"]}
    assert ids.isdisjoint(first["unclustered_ids"])
    assert len(ids) + len(first["unclustered_ids"]) == 400


def test_evaluation_split_is_fixed_and_uses_truth_only_for_scoring():
    assert evaluation.split_of("V2-FB-0001") == evaluation.split_of("V2-FB-0001")
    truth = evaluation.load_truth()
    halves = {evaluation.split_of(i) for i in truth}
    assert halves == {"development", "test"} and len(truth) == 400
    assert evaluation.adjusted_rand([1, 1, 2, 2], ["a", "a", "b", "b"]) == 1.0
    import inspect
    assert "source_annotations" not in inspect.getsource(clustering)


def test_theme_hierarchy_is_consistent():
    with sqlite3.connect(f"file:{V2_DB}?mode=ro", uri=True) as db:
        result = clustering.themes(db, clustering.ClusterConfig("embedding", 0.7, 3, 0.45), 0.6, "embedding")
        with pytest.raises(ValueError):
            clustering.themes(db, clustering.ClusterConfig("embedding", 0.7), 0.6, "colour")
    sub_ids = {s["id"] for s in result["sub_themes"]}
    assert set(result["theme_of_sub_theme"]) == sub_ids
    assert sorted(s for t in result["themes"] for s in t["sub_themes"]) == sorted(sub_ids)
    assert len(result["themes"]) <= len(sub_ids)
    theme_index = {t["id"]: n for n, t in enumerate(result["themes"])}
    for rid, subs in result["sub_memberships"].items():
        expected = sorted({theme_index[result["theme_of_sub_theme"][f"C{c + 1:02d}"]] for c in subs})
        assert result["memberships"][rid] == expected


def test_labels_do_not_repeat_words_from_their_leading_phrase():
    with sqlite3.connect(f"file:{V2_DB}?mode=ro", uri=True) as db:
        result = clustering.cluster(db, clustering.ClusterConfig("embedding", 0.65, 3, 0.45))
    for c in result["clusters"]:
        parts = c["label"].split(" / ")
        if " " in parts[0]:
            assert not set(parts[0].split()) & set(parts[1:]), c["label"]
