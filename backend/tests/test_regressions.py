"""Regression guards that had no dedicated test before Phase 4.5."""
import pytest

from app.investigate import executor
from app.investigate.plan import rule_plan, validate


@pytest.fixture
def events(events_db, monkeypatch):
    monkeypatch.setenv("GIST_EVENTS_DB_PATH", str(events_db[0]))


def test_small_groups_are_flagged_not_headlined(events):
    plan = rule_plan("Why did onboarding activation drop in October?")
    result = executor.run(plan, log=False)
    checks = {c["kind"] for c in result["checks"]}
    assert "small_sample" in checks
    small = {g for c in result["checks"] if c["kind"] == "small_sample" for g in c["message"].split(": ", 1)[1].rstrip(". Treat those rates as noisy").split(", ")}
    headlines = [f["text"] for f in result["findings"] if f["text"].startswith("Largest within-group change")]
    assert headlines and not any(h.split(": ", 1)[1].split(" ")[0] in small for h in headlines)
