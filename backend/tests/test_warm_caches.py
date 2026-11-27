"""Startup cache warming: opt-in, fills the deterministic caches, and never blocks startup."""
from fastapi.testclient import TestClient

from app import issues, main, opportunities
from app.main import app
from scripts.seed import seed


def _fresh(monkeypatch, tmp_path, warm: str | None):
    monkeypatch.setenv("GIST_DB_PATH", str(tmp_path / "warm.sqlite3"))
    seed()
    if warm is not None:
        monkeypatch.setenv("GIST_WARM_CACHES", warm)
    issues._cache.clear()
    opportunities._cache.clear()


def test_warming_fills_caches_before_the_first_request(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path, "true")
    with TestClient(app) as client:
        assert issues._cache and opportunities._cache          # built during startup, not by a request
        assert client.get("/api/opportunities").status_code == 200


def test_warming_is_off_by_default(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path, None)
    monkeypatch.delenv("GIST_WARM_CACHES", raising=False)
    with TestClient(app):
        assert not issues._cache and not opportunities._cache


def test_warming_failure_never_blocks_startup(monkeypatch, tmp_path):
    _fresh(monkeypatch, tmp_path, "true")

    def broken():
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(main, "connection", broken)
    assert main.warm_caches() is None
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
