"""Phase 3.1 analytics: every figure equals an independent SQL count, on both datasets."""
import re
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from scripts.seed import seed


@pytest.fixture(params=["v1", "v2"])
def api(request, tmp_path, monkeypatch):
    path = tmp_path / f"{request.param}.sqlite3"
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    if request.param == "v2":
        monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    seed(request.param, path=path)
    db = sqlite3.connect(path)
    with TestClient(app) as client:
        yield client, db, request.param
    db.close()


def _sql(db, table, where="", params=()):
    return db.execute(f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0]


def test_summary_matches_sql_and_breakdowns_sum(api):
    client, db, _ = api
    body = client.get("/api/analytics/summary").json()
    assert body["feedback_count"] == _sql(db, "feedback") == 400
    assert body["ticket_count"] == _sql(db, "support_tickets") == 120
    assert body["negative_feedback_count"] == _sql(db, "feedback", " WHERE sentiment='Negative'")
    for key in ("by_sentiment", "by_category", "by_segment", "by_area", "by_channel"):
        assert sum(item["count"] for item in body[key]) == body["feedback_count"], key
    for key in ("tickets_by_severity", "tickets_by_status"):
        assert sum(item["count"] for item in body[key]) == body["ticket_count"], key
    quality = body["data_quality"]
    assert quality["unspecified_feature"] == _sql(db, "feedback", " WHERE related_feature IN ('', 'unspecified')")
    assert quality["unclear_category"] == _sql(db, "feedback", " WHERE issue_category='Unclear'")
    assert body["date_range"]["first"] == db.execute("SELECT MIN(substr(timestamp,1,10)) FROM feedback").fetchone()[0]


def test_filters_apply_consistently_and_drill_down_exactly(api):
    client, db, _ = api
    params = {"from_date": "2025-03-01", "to_date": "2025-09-30", "segment": "Enterprise", "product_area": "Onboarding"}
    where = (" WHERE substr(timestamp,1,10) BETWEEN ? AND ? AND customer_segment=? AND product_area=?",
             ("2025-03-01", "2025-09-30", "Enterprise", "Onboarding"))
    body = client.get("/api/analytics/summary", params=params).json()
    assert body["feedback_count"] == _sql(db, "feedback", *where)
    assert body["ticket_count"] == _sql(db, "support_tickets", *where)
    records = client.get("/api/records", params={**params, "page_size": 100}).json()
    assert records["total"] == body["feedback_count"]
    assert all(params["from_date"] <= r["timestamp"][:10] <= params["to_date"] and r["customer_segment"] == "Enterprise"
               for r in records["items"])
    tickets = client.get("/api/tickets", params={**params, "page_size": 100}).json()
    assert tickets["total"] == body["ticket_count"]
    for item in body["by_category"]:
        drill = client.get("/api/records", params={**params, "category": item["name"]}).json()
        assert drill["total"] == item["count"], item
    for item in body["tickets_by_severity"]:
        assert client.get("/api/tickets", params={**params, "severity": item["name"]}).json()["total"] == item["count"]
    negative = client.get("/api/records", params={**params, "sentiment": "Negative"}).json()["total"]
    assert negative == body["negative_feedback_count"]


@pytest.mark.parametrize("metric", ["feedback", "negative_feedback", "tickets"])
@pytest.mark.parametrize("group_by", [None, "category", "area", "segment"])
def test_trends_are_contiguous_and_sum_to_totals(api, metric, group_by):
    client, db, _ = api
    params = {"metric": metric, **({"group_by": group_by} if group_by else {})}
    body = client.get("/api/analytics/trends", params=params).json()
    months = body["months"]
    assert months == sorted(months) and len(months) == len(set(months))
    for a, b in zip(months, months[1:]):
        y, m = int(a[:4]), int(a[5:])
        assert b == (f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}")
    table = "support_tickets" if metric == "tickets" else "feedback"
    where = " WHERE sentiment='Negative'" if metric == "negative_feedback" else ""
    assert body["total"] == _sql(db, table, where) == sum(s["total"] for s in body["series"])
    assert all(len(s["counts"]) == len(months) and sum(s["counts"]) == s["total"] for s in body["series"])


def test_trends_with_date_scope_zero_fill_requested_months(api):
    client, _, _ = api
    body = client.get("/api/analytics/trends", params={"from_date": "2025-02-15", "to_date": "2025-05-10"}).json()
    assert body["months"] == ["2025-02", "2025-03", "2025-04", "2025-05"]


def test_release_windows_match_sql_and_say_not_causation(api):
    client, db, _ = api
    body = client.get("/api/analytics/releases", params={"window_days": 30}).json()
    assert "not causation" in body["interpretation"]
    assert len(body["releases"]) == _sql(db, "documents", " WHERE kind='release_note'")
    for item in body["releases"]:
        day = date.fromisoformat(item["published"])
        assert item["before"]["to_date"] == (day - timedelta(days=1)).isoformat()
        assert item["after"]["from_date"] == item["published"]
        for window in ("before", "after"):
            w = item[window]
            where = (" WHERE substr(timestamp,1,10) BETWEEN ? AND ? AND product_area=?", (w["from_date"], w["to_date"], item["product_area"]))
            assert w["feedback"] == _sql(db, "feedback", *where)
            assert w["tickets"] == _sql(db, "support_tickets", *where)


def test_repeated_complaints_are_real_groups(api):
    client, db, _ = api
    body = client.get("/api/analytics/repeated").json()
    normalize = lambda text: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()
    for group in body["repeated_texts"]:
        assert group["count"] == len(group["record_ids"]) >= 2
        rows = db.execute(f"SELECT feedback_text, sentiment FROM feedback WHERE id IN ({','.join('?' * len(group['record_ids']))})",
                          group["record_ids"]).fetchall()
        assert len(rows) == group["count"] and len({normalize(t) for t, _ in rows}) == 1
        assert all(s in ("Negative", "Mixed") for _, s in rows)
    for item in body["top_negative_features"]:
        assert item["feature"] not in ("", "unspecified")
        assert item["count"] == _sql(db, "feedback", " WHERE sentiment='Negative' AND related_feature=? AND issue_category=?",
                                     (item["feature"], item["category"]))


def test_invalid_analytics_input_is_structured_422(api):
    client, _, _ = api
    for path in ("/api/analytics/summary", "/api/analytics/trends", "/api/analytics/releases",
                 "/api/analytics/repeated", "/api/tickets", "/api/records"):
        response = client.get(path, params={"from_date": "2025-06-01", "to_date": "2025-01-01"})
        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request", path
    assert client.get("/api/analytics/trends", params={"metric": "revenue"}).status_code == 422
    assert client.get("/api/analytics/trends", params={"group_by": "tier"}).status_code == 422
    assert client.get("/api/analytics/summary", params={"segment": "Galactic"}).status_code == 422
    assert client.get("/api/analytics/releases", params={"window_days": 0}).status_code == 422


def test_unspecified_features_are_counted_not_dropped(api):
    client, db, version = api
    quality = client.get("/api/analytics/summary").json()["data_quality"]["unspecified_feature"]
    drill = sum(client.get("/api/records", params={"feature": value}).json()["total"] for value in ("", "unspecified"))
    assert quality == drill
    if version == "v2":
        assert quality == 31
