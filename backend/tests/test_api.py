import sqlite3

from app.database import database_path


def test_health_and_record_detail(client):
    assert client.get("/api/health").json() == {"status": "ok", "app": "Gist"}
    listing = client.get("/api/records").json()
    assert listing["total"] == 400
    assert len(listing["items"]) == 20
    record_id = listing["items"][0]["id"]
    assert client.get(f"/api/records/{record_id}").json()["id"] == record_id
    assert client.get("/api/records/missing").json() == {"error": {"code": "not_found", "message": "Feedback record not found."}}


def test_filtering_search_and_pagination(client):
    first = client.get("/api/records?page=1&page_size=5").json()
    second = client.get("/api/records?page=2&page_size=5").json()
    assert first["pages"] == 80
    assert len(first["items"]) == len(second["items"]) == 5
    assert {r["id"] for r in first["items"]}.isdisjoint({r["id"] for r in second["items"]})
    result = client.get("/api/records", params={"category": "Integration failures", "segment": "Enterprise", "query": "CRM"}).json()
    assert result["total"] > 0
    assert all(r["issue_category"] == "Integration failures" and r["customer_segment"] == "Enterprise" and ("crm" in r["feedback_text"].lower() or "crm" in r["related_feature"].lower()) for r in result["items"])
    assert client.get("/api/records", params={"query": "___unlikely___"}).json()["total"] == 0


def test_invalid_inputs(client):
    for params in ({"page": 0}, {"page_size": 101}, {"category": "other"}, {"segment": "Unknown"}, {"query": "x" * 201}):
        response = client.get("/api/records", params=params)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


def test_dashboard_metrics_match_database(client):
    stats = client.get("/api/stats").json()
    with sqlite3.connect(database_path()) as db:
        assert stats["feedback_count"] == db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 400
        assert stats["support_ticket_count"] == db.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0] == 120
        assert stats["negative_feedback_count"] == db.execute("SELECT COUNT(*) FROM feedback WHERE sentiment = 'Negative'").fetchone()[0]
        assert stats["positive_feedback_count"] == db.execute("SELECT COUNT(*) FROM feedback WHERE sentiment = 'Positive'").fetchone()[0]
        assert stats["enterprise_feedback_count"] == db.execute("SELECT COUNT(*) FROM feedback WHERE customer_segment = 'Enterprise'").fetchone()[0]
    assert sum(row["count"] for row in stats["by_product_area"]) == 400
    assert sum(row["count"] for row in stats["by_category"]) == 400
