"""Phase 4.1 product-events dataset and read-only tools: determinism, consistency, planted signals, safety."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from app.errors import InvalidRequest
from app.investigate import tools as T
from scripts import generate_events as gen

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db(events_db, monkeypatch):
    monkeypatch.setenv("GIST_EVENTS_DB_PATH", str(events_db[0]))
    return events_db[0]


def q(path, sql, *params):
    with sqlite3.connect(path) as conn:
        return conn.execute(sql, params).fetchall()


def test_generator_is_deterministic_and_refuses_overwrite(events_db):
    path, meta = events_db
    assert gen.content_hash(gen.build()) == meta["content_sha256"]
    with pytest.raises(FileExistsError):
        gen.write(path)
    assert 2500 <= int(meta["users"]) <= 4500 and 100_000 <= int(meta["events"]) <= 250_000


def test_consistency(events_db):
    path, _ = events_db
    assert q(path, """SELECT COUNT(*) FROM events e JOIN users u ON u.id = e.user_id
        WHERE e.name NOT IN ('invite_sent','invite_accepted','invite_verification_repeated') AND (u.signup_at IS NULL OR e.ts < u.signup_at)""") == [(0,)]
    assert q(path, "SELECT COUNT(*) FROM events e JOIN accounts a ON a.id = e.account_id WHERE e.ts < a.created_at") == [(0,)]
    assert q(path, """SELECT COUNT(*) FROM events c JOIN events i ON i.target_user_id = c.user_id AND i.name = 'invite_sent'
        WHERE c.name IN ('invite_accepted','invite_verification_repeated') AND c.ts < i.ts""") == [(0,)]
    assert q(path, """SELECT COUNT(*) FROM events v JOIN events c ON c.user_id = v.user_id AND c.name = 'invite_accepted'
        WHERE v.name = 'invite_verification_repeated' AND v.ts > c.ts""") == [(0,)]
    # An acceptance without its invitation is allowed only when the invitation fell in the tracking outage (lost event).
    orphans = q(path, """SELECT substr(u.invited_at,1,10) FROM events e JOIN users u ON u.id = e.user_id WHERE e.name = 'invite_accepted'
        AND e.user_id NOT IN (SELECT target_user_id FROM events WHERE name = 'invite_sent')""")
    assert all(day in {"2025-11-18", "2025-11-19"} for (day,) in orphans)
    assert q(path, "SELECT COUNT(*) FROM events WHERE ts < '2025-01-08 09:00:00' OR ts > '2025-12-15 18:00:00'") == [(0,)]
    assert q(path, "SELECT COUNT(*) FROM events e JOIN users u ON u.id = e.user_id WHERE e.account_id != u.account_id") == [(0,)]


def test_releases_match_pulse_v2_release_notes(events_db):
    notes = {}
    for f in sorted((ROOT / "data/v2/release-notes").glob("release-*.md")):
        notes[f.stem] = re.search(r"Published: (\d{4}-\d{2}-\d{2})", f.read_text()).group(1)
    assert dict(q(events_db[0], "SELECT id, released_on FROM releases")) == notes


def test_answer_key_never_in_events_database(events_db):
    key = json.loads(json.dumps(gen.ANSWER))
    ids = [p["id"] for p in key["planted"]] + [d["id"] for d in key["decoys"]]   # uppercase IDs: exact, case-sensitive
    words = ["decoy", "planted", "answer key", "mix shift", "outage"]
    with sqlite3.connect(events_db[0]) as conn:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
            for row in conn.execute(f"SELECT * FROM {table}"):
                text = " ".join(str(v) for v in row if isinstance(v, str))
                assert not any(re.search(rf"\b{i}\b", text) for i in ids), (table, row)
                assert not any(w in text.lower() for w in words), (table, row)


def _monthly(metric, by=None, group="all"):
    return {s["bucket"]: s["value"] for s in T.metric_series(metric, "month", by)["series"] if s["group"] == group}


def test_planted_effects_visible_through_tools(db):
    invite = _monthly("invite_acceptance_rate")
    assert invite["2025-01"] > 0.8 and max(invite[m] for m in ("2025-03", "2025-04", "2025-05", "2025-06")) < 0.72
    crm = _monthly("crm_sync_failure_rate")
    assert max(crm[m] for m in ("2025-02", "2025-03", "2025-04")) < 0.05
    assert min(crm[m] for m in ("2025-07", "2025-08", "2025-09")) > 0.12 and crm["2025-11"] < 0.05
    delayed = _monthly("alert_delayed_share")
    assert delayed["2025-07"] < 0.05 and delayed["2025-10"] > 0.25
    large = _monthly("dashboard_load_p50_ms", "workspace_size", "large")
    assert large["2025-06"] > 2 * large["2025-09"]
    standard = _monthly("dashboard_load_p50_ms", "workspace_size", "standard")
    assert abs(standard["2025-06"] - standard["2025-09"]) < 0.15 * standard["2025-06"]
    digest = _monthly("digest_emails_per_user_week")
    assert digest["2025-06"] > 2.5 * digest["2025-02"] and digest["2025-11"] < 1.5 * digest["2025-02"]
    templates = _monthly("template_uses")
    assert "2025-06" not in templates and templates["2025-08"] > 100


def test_mix_shift_decoy_reads_as_mix_not_rate(db):
    c = T.compare_periods("activation_rate", "2025-07-14", "2025-10-12", "2025-10-13", "2025-11-09", by="segment")
    d = c["decomposition"]
    assert d["mix_effect"] <= -0.04 and abs(d["rate_effect"]) <= abs(d["mix_effect"]) / 2
    assert abs(d["mix_effect"] + d["rate_effect"] - d["total_change"]) < 0.01
    shares = {g["group"]: g for g in c["groups"]}
    assert shares["Individual"]["share_b"] > 3 * shares["Individual"]["share_a"]


def test_data_quality_flags_outage_not_ordinary_days(db):
    flagged = {d["date"] for d in T.data_quality()["low_volume_days"]}
    assert {"2025-11-18", "2025-11-19"} <= flagged
    assert len(flagged) <= 6


def test_tools_are_read_only_and_validate(db):
    with T.connect() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM events")
    assert q(db, "SELECT COUNT(*) FROM events")[0][0] > 0
    bad = [dict(metric="revenue"), dict(metric="signups", grain="day"), dict(metric="signups", by="country"),
           dict(metric="signups", from_date="2025-13-01"), dict(metric="signups", from_date="2024-01-01"),
           dict(metric="signups", from_date="2025-06-01", to_date="2025-05-01"),
           dict(metric="crm_sync_failure_rate", by="role"), dict(metric="signups", by="segment); DROP TABLE events; --")]
    for kwargs in bad:
        with pytest.raises(InvalidRequest):
            T.metric_series(**kwargs)
    with pytest.raises(InvalidRequest):
        T.data_quality(threshold=2)
    weekly = T.metric_series("signups", "week")
    assert len({s["bucket"] for s in weekly["series"]}) <= T.MAX_BUCKETS and weekly["definition"]


def test_missing_events_db_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GIST_EVENTS_DB_PATH", str(tmp_path / "missing.sqlite3"))
    with pytest.raises(Exception, match="events"):
        T.metric_series("signups")
