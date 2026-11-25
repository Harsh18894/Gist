"""Read-only Pulse v2 corpus/index inventory and embedding cost preflight."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from freeze_v2_split import ROOT, source_hash, verify
from audit_v2 import audit
from app.dataset import default_db_path, source_dir

DATA = source_dir("v2", ROOT)
DB = default_db_path("v2", ROOT)
REQUIRED_FEEDBACK = {"id", "timestamp", "customer_segment", "subscription_tier", "product_area",
                     "feedback_channel", "feedback_text", "sentiment", "issue_category", "related_feature"}
REQUIRED_TICKET = {"id", "timestamp", "customer_segment", "subscription_tier", "product_area",
                   "subject", "description", "severity", "issue_category", "related_feature", "status"}


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def preflight() -> dict:
    split = verify()
    feedback = _rows(DATA / "feedback.jsonl")
    tickets = _rows(DATA / "support-tickets.jsonl")
    annotations = _rows(ROOT / "evals/v2/source_annotations.jsonl")
    questions = json.loads((ROOT / "evals/v2/questions.json").read_text())["questions"]
    docs = [*sorted((DATA / "prds").glob("*.md")), *sorted((DATA / "release-notes").glob("*.md"))]
    ids = [row["id"] for row in feedback + tickets] + [path.stem for path in docs]
    annotation_ids = [row["source_id"] for row in annotations]
    feedback_by_id = {row["id"]: row for row in feedback}
    issue_counts = Counter(issue for item in annotations if item["source_id"] in feedback_by_id for issue in item["issue_ids"])
    reaction_counts = Counter((issue, feedback_by_id[item["source_id"]]["sentiment"])
                              for item in annotations if item["source_id"] in feedback_by_id for issue in item["issue_ids"])
    hard_negative_groups = {"access": ["INVITE_LOOP", "RESET_LOGIN", "SSO_SETUP"],
                            "integration": ["CRM_SYNC", "CSV_MAPPING"],
                            "dashboard": ["DASH_SLOW", "DASH_FILTER"],
                            "templates": ["TEMPLATE_FIND", "TEMPLATE_ACCESS"]}
    hard_negatives_present = all(all(issue_counts[issue] > 0 for issue in group) for group in hard_negative_groups.values())
    contradictory_reactions_present = all(reaction_counts[(issue, "Positive")] > 0 and reaction_counts[(issue, "Negative")] > 0
                                           for issue in ("DIGEST_NOISE", "CRM_SYNC", "DASH_SLOW"))
    missing_fields = [row.get("id", "unknown") for row in feedback if not REQUIRED_FEEDBACK <= set(row) or any(row.get(key) in (None, "") for key in REQUIRED_FEEDBACK)]
    missing_fields += [row.get("id", "unknown") for row in tickets if not REQUIRED_TICKET <= set(row) or any(row.get(key) in (None, "") for key in REQUIRED_TICKET)]
    if not DB.is_file():
        raise FileNotFoundError("Seed backend/gist-v2.sqlite3 before preflight; no database is created automatically.")
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        meta = dict(db.execute("SELECT key,value FROM dataset_meta"))
        source_rows = db.execute("SELECT id,title,kind,source_date,segment,product_area,path,content FROM sources").fetchall()
        source_ids = [row["id"] for row in source_rows]
        chunks = db.execute("SELECT id,source_id,ordinal,content,word_count FROM chunks").fetchall()
        model_counts = dict(db.execute("SELECT model,COUNT(*) FROM embeddings GROUP BY model"))
        chunk_words = sum(row["word_count"] for row in chunks)
        chunk_chars = sum(len(row["content"]) for row in chunks)
        missing_source_metadata = [row["id"] for row in source_rows if not row["source_date"] or not row["product_area"] or not row["path"] or
                                   (row["kind"] in {"feedback", "support_ticket"} and not row["segment"])]
        stale_paths = [row["id"] for row in source_rows if not row["path"].startswith("data/v2/")]
        hidden_tokens = {issue for item in annotations for issue in item["issue_ids"]}
        hidden_marker_hits = sum("issue_ids" in row["content"] or any(token in row["content"] or token in row["title"] for token in hidden_tokens)
                                 for row in source_rows)
        index = {"dataset_version": meta.get("version"), "source_sha256": meta.get("source_sha256"),
                 "sources": len(source_rows), "source_kinds": dict(Counter(row["kind"] for row in source_rows)),
                 "chunks": len(chunks), "chunk_words": chunk_words, "chunk_characters": chunk_chars,
                 "approx_embedding_tokens_characters_divided_by_4": round(chunk_chars / 4),
                 "approx_embedding_tokens_words_times_1_5": round(chunk_words * 1.5),
                 "fts_rows": db.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0],
                 "orphan_fts_rows": db.execute("SELECT COUNT(*) FROM chunk_fts f LEFT JOIN chunks c ON c.id=f.chunk_id WHERE c.id IS NULL").fetchone()[0],
                 "chunks_missing_fts": db.execute("SELECT COUNT(*) FROM chunks c LEFT JOIN chunk_fts f ON f.chunk_id=c.id WHERE f.chunk_id IS NULL").fetchone()[0],
                 "embedding_models": model_counts,
                 "invalid_embedding_blobs": db.execute("SELECT COUNT(*) FROM embeddings WHERE dimensions <= 0 OR length(vector) != dimensions * 4").fetchone()[0],
                 "openai_embedding_rows": model_counts.get("text-embedding-3-small", 0),
                 "missing_source_metadata": missing_source_metadata,
                 "non_v2_paths": stale_paths, "hidden_marker_hits": hidden_marker_hits,
                 "orphan_chunks": db.execute("SELECT COUNT(*) FROM chunks c LEFT JOIN sources s ON s.id=c.source_id WHERE s.id IS NULL").fetchone()[0],
                 "unstable_chunk_ids": [row["id"] for row in chunks if row["id"] != f"{row['source_id']}:{row['ordinal']:03d}"],
                 "word_count_mismatches": sum(row["word_count"] != len(row["content"].split()) for row in chunks),
                 "api_usage": dict(db.execute("SELECT 'calls',COUNT(*) FROM api_usage")),
                 "api_tokens": db.execute("SELECT COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),COALESCE(SUM(estimated_cost_usd),0) FROM api_usage").fetchone()[:],
                 "integrity_check": db.execute("PRAGMA integrity_check").fetchone()[0]}
    unique = len(set(ids)) == len(ids) == len(set(source_ids)) and set(ids) == set(source_ids)
    annotation_matches = len(annotation_ids) == len(set(annotation_ids)) and set(annotation_ids) == set(ids)
    ground_truth_not_indexed = hidden_marker_hits == 0 and not stale_paths
    issues = []
    if len(source_rows) != 534 or len(chunks) != 536 or index["source_kinds"] != {"feedback": 400, "support_ticket": 120, "prd": 6, "release_note": 8}:
        issues.append("Pulse v2 source or chunk counts differ from the frozen 534-source/536-chunk corpus.")
    if not unique: issues.append("Source IDs are not unique or differ from the index.")
    if not annotation_matches: issues.append("Private annotations do not cover exactly the indexed sources.")
    if missing_fields or missing_source_metadata: issues.append("Required production metadata is missing.")
    if meta.get("version") != "v2" or meta.get("source_sha256") != source_hash(): issues.append("Index version or source fingerprint is stale.")
    if len(chunks) != index["fts_rows"] or index["orphan_fts_rows"] or index["chunks_missing_fts"] or index["invalid_embedding_blobs"] or index["orphan_chunks"] or index["word_count_mismatches"] or index["unstable_chunk_ids"]: issues.append("Chunk, embedding, or FTS index consistency failed.")
    if not ground_truth_not_indexed: issues.append("Potential hidden-ground-truth leakage into the source index.")
    if not hard_negatives_present: issues.append("A modeled hard-negative issue group is missing.")
    if not contradictory_reactions_present: issues.append("A modeled contradiction group lacks both positive and negative feedback.")
    if index["integrity_check"] != "ok": issues.append("SQLite integrity check failed.")
    if len(questions) < 50 or len({row["id"] for row in questions}) != len(questions): issues.append("Benchmark question count or IDs invalid.")
    quality = audit()
    if quality["timeline_errors"]: issues.append("Dataset timeline errors detected.")
    approximate_tokens = max(index["approx_embedding_tokens_characters_divided_by_4"], index["approx_embedding_tokens_words_times_1_5"])
    v1_db = default_db_path("v1", ROOT)
    v1_summary: dict = {"database_exists": v1_db.exists(), "feedback_source_exists": (ROOT / "data/feedback.jsonl").is_file()}
    if v1_db.exists():
        with sqlite3.connect(f"file:{v1_db}?mode=ro", uri=True) as old:
            v1_summary.update({"feedback": old.execute("SELECT COUNT(*) FROM feedback").fetchone()[0],
                               "tickets": old.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0],
                               "documents": old.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                               "v2_prefixed_sources": old.execute("SELECT COUNT(*) FROM sources WHERE id LIKE 'V2-%'").fetchone()[0]})
    return {"status": "FAIL" if issues else "PASS", "issues": issues,
            "source_hash_verified": meta.get("source_sha256") == source_hash(),
            "source_id_unique_and_indexed": unique, "annotations_match_sources": annotation_matches,
            "ground_truth_not_indexed": ground_truth_not_indexed,
            "feedback": len(feedback), "tickets": len(tickets), "prds": sum(path.parent.name == "prds" for path in docs),
            "release_notes": sum(path.parent.name == "release-notes" for path in docs),
            "missing_production_fields": missing_fields, "benchmark_questions": len(questions),
            "hard_negative_groups_present": hard_negatives_present,
            "contradictory_reactions_present": contradictory_reactions_present,
            "v1_preservation": v1_summary,
            "benchmark_categories": dict(Counter(row["evaluation_category"] for row in questions)),
            "split": {"development": len(split["development_ids"]), "heldout_test": len(split["heldout_test_ids"]),
                      "source_sha256": split["source_sha256"], "benchmark_sha256": split["benchmark_sha256"]},
            "index": index, "quality": quality,
            "embedding_cost_estimate_usd_at_0_02_per_m": round(approximate_tokens * 0.02 / 1_000_000, 8),
            "token_estimate_method": "Approximation only: max(characters/4, words*1.5); provider-reported usage will be authoritative."}


if __name__ == "__main__":
    print(json.dumps(preflight(), indent=2))
