"""Phase 3.6 Evidence Explorer: complete usage, consistent with opportunities, safe search."""
from app import evidence


def _all(client, **params):
    items, page = [], 1
    while True:
        data = client.get("/api/evidence", params={**params, "page": page, "page_size": 50}).json()
        items += data["items"]
        if page * 50 >= data["total"]:
            return items, data
        page += 1


def test_every_source_has_one_status_consistent_with_opportunities(client):
    items, data = _all(client)
    stats = client.get("/api/rag/status").json()
    assert len(items) == data["total"] == stats["sources"] == len({i["id"] for i in items})
    assert sum(data["status_counts"].values()) == data["total"]
    by_id = {i["id"]: i for i in items}
    for card in client.get("/api/opportunities").json()["opportunities"]:
        detail = client.get(f"/api/opportunities/{card['id']}").json()
        primary = [f["id"] for f in detail["evidence"]["feedback"][:detail["evidence"]["feedback_records"]]]
        for fid in primary:
            assert by_id[fid]["status"] == "opportunity_evidence"
            assert {"opportunity_id": card["id"], "role": "opportunity_evidence"} in by_id[fid]["used_in"]
        for t in detail["evidence"]["linked_tickets"]:
            assert by_id[t["id"]]["status"] == "linked_ticket"
        for d in detail["product_context"]:
            assert by_id[d["id"]]["status"] == "product_context"
    kinds = {"feedback": {"opportunity_evidence", "secondary_mention", "needs_triage", "not_grouped"},
             "support_ticket": {"linked_ticket", "unlinked_ticket"}, "prd": {"product_context", "unused_document"},
             "release_note": {"product_context", "unused_document"}}
    assert all(i["status"] in kinds[i["kind"]] for i in items)
    unlinked = client.get("/api/opportunities").json()["unlinked_tickets"]
    assert data["status_counts"].get("unlinked_ticket", 0) == unlinked


def test_search_filters_combine_and_wildcards_are_literal(client):
    items, _ = _all(client, q="invite", kind="feedback")
    assert items and all(i["kind"] == "feedback" for i in items)
    assert all("invite" in client.get(f"/api/sources/{i['id']}").json()["content"].lower() for i in items)
    both, _ = _all(client, q="invite slow")
    assert len(both) <= len(_all(client, q="slow")[0])      # terms are ANDed
    assert client.get("/api/evidence", params={"q": "%"}).json()["total"] == 0 or all(
        "%" in client.get(f"/api/sources/{i['id']}").json()["content"] for i in client.get("/api/evidence", params={"q": "%"}).json()["items"])
    assert client.get("/api/evidence", params={"q": "'; DROP TABLE sources; --"}).status_code == 200
    assert client.get("/api/rag/status").json()["sources"] > 0
    status_only, data = _all(client, status="needs_triage")
    assert all(i["status"] == "needs_triage" for i in status_only) and data["total"] == len(status_only)


def test_invalid_parameters_rejected(client):
    for params in ({"kind": "email"}, {"status": "great"}, {"page": 0}, {"page_size": 51}, {"q": "x" * 201}):
        assert client.get("/api/evidence", params=params).status_code == 422


def test_like_escape():
    assert evidence._like("50%_off\\") == "%50\\%\\_off\\\\%"


def test_status_labels_are_distinct():
    assert len(set(evidence.STATUS_LABELS.values())) == len(evidence.STATUS_LABELS)
