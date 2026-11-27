"""Issue Explorer API: consistent hierarchy, complete coverage, explanations, both clustering paths."""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import issues
from app.main import app
from scripts.seed import seed
from helpers import V2_DB  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _check(client):
    data = client.get("/api/issues").json()
    sub_ids = [s["id"] for s in data["sub_themes"]]
    assert sorted(i for t in data["themes"] for i in t["sub_theme_ids"]) == sorted(sub_ids)
    assert all("members" not in s for s in data["sub_themes"])
    covered = set()
    for sub_id in sub_ids:
        detail = client.get(f"/api/issues/{sub_id}").json()
        assert len(detail["members"]) == detail["size"] + detail["secondary_members"]
        assert all(m["membership"] in ("primary", "secondary") and m["text"] for m in detail["members"])
        assert detail["label"] and detail["representatives"]
        covered |= {m["id"] for m in detail["members"]}
    unclustered = client.get("/api/issues/unclustered").json()
    assert len(unclustered) == data["unclustered_count"]
    assert covered.isdisjoint({r["id"] for r in unclustered})
    assert len(covered) + len(unclustered) == data["records"] == 400
    assert client.get("/api/issues/C999").status_code == 404
    return data


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_issue_map_without_stored_vectors_falls_back_to_words(version, tmp_path, monkeypatch):
    issues._cache.clear()
    path = tmp_path / f"{version}.sqlite3"
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    if version == "v2":
        monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    seed(version, path=path)
    with TestClient(app) as client:
        data = _check(client)
    assert data["method"].startswith("word similarity")


def test_issue_map_uses_stored_learned_vectors_on_the_real_v2_index(monkeypatch, tmp_path):
    issues._cache.clear()
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    copy = tmp_path / "gist-v2.sqlite3"
    shutil.copyfile(V2_DB, copy)   # never write to the shipped snapshot
    monkeypatch.setenv("GIST_DB_PATH", str(copy))
    with TestClient(app) as client:
        data = _check(client)
    assert data["method"].startswith("learned vectors")
    assert len(data["sub_themes"]) == 67 and len(data["themes"]) == 32
    assert any(s["needs_triage"] for s in data["sub_themes"])
    assert "not confirmed root causes" in data["interpretation"]
    issues._cache.clear()
