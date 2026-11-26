"""Issue Explorer data: sub-themes (primary unit) inside loose themes, with explanations.

Display settings were chosen on the development half in Phase 3.2 (see PLAN.md). Results
are cached per dataset version and source fingerprint, since clustering is deterministic.
"""
from __future__ import annotations

import sqlite3
from collections import Counter

from .clustering import ClusterConfig, themes

DISPLAY_SUB = ClusterConfig("embedding", 0.65, 3, 0.45)
DISPLAY_THEME_THRESHOLD = 0.65
FALLBACK_SUB = ClusterConfig("tfidf", 0.25, 3, 0.45, remove_boilerplate=True)
FALLBACK_THEME_THRESHOLD = 0.3
_cache: dict[tuple, dict] = {}


def _key(db: sqlite3.Connection) -> tuple:
    has_meta = db.execute("SELECT name FROM sqlite_master WHERE name = 'dataset_meta'").fetchone()
    meta = dict(db.execute("SELECT key, value FROM dataset_meta")) if has_meta else {}
    count = db.execute("SELECT COUNT(*), MAX(id) FROM feedback").fetchone()
    return (meta.get("version"), meta.get("source_sha256"), tuple(count))


def issue_map(db: sqlite3.Connection) -> dict:
    key = _key(db)
    if key in _cache:
        return _cache[key]
    try:
        result, method = themes(db, DISPLAY_SUB, DISPLAY_THEME_THRESHOLD, "embedding"), "learned vectors (text-embedding-3-small, stored)"
    except RuntimeError:
        result, method = themes(db, FALLBACK_SUB, FALLBACK_THEME_THRESHOLD, "words"), "word similarity (no stored learned vectors)"
    records = {row[0]: dict(zip(("id", "text", "date", "segment", "area", "sentiment", "category"), row)) for row in db.execute(
        "SELECT id, feedback_text, substr(timestamp,1,10), customer_segment, product_area, sentiment, issue_category FROM feedback")}
    theme_of = result["theme_of_sub_theme"]
    sub_themes = []
    for sub in result["sub_themes"]:
        primary = [m["id"] for m in sub["members"] if m["membership"] == "primary"]
        unclear = sum(records[i]["category"] == "Unclear" for i in primary)
        sub_themes.append({
            "id": sub["id"], "theme_id": theme_of[sub["id"]], "label": sub["label"], "top_terms": sub["top_terms"],
            "size": sub["size"], "secondary_members": sub["secondary_members"], "distinct_texts": sub["distinct_texts"],
            "trend": sub["trend"], "recent_90_days": sub["recent_90_days"], "prior_90_days": sub["prior_90_days"],
            "first_date": sub["first_date"], "last_date": sub["last_date"],
            "segments": sub["segments"], "areas": sub["areas"], "sentiment": sub["sentiment"],
            "needs_triage": unclear * 2 > len(primary),
            "representatives": [{"id": i, "text": records[i]["text"]} for i in sub["representative_ids"]],
            "members": [{**m, **{k: records[m["id"]][k] for k in ("text", "date", "segment", "area", "sentiment", "category")}}
                        for m in sub["members"]]})
    theme_list = []
    for theme in result["themes"]:
        subs = [s for s in sub_themes if s["theme_id"] == theme["id"]]
        theme_list.append({"id": theme["id"], "label": subs[0]["label"] if len(subs) == 1 else theme["label"],
                           "size": theme["size"], "sub_theme_ids": [s["id"] for s in subs],
                           "areas": dict(sum((Counter(s["areas"]) for s in subs), Counter()).most_common(3)),
                           "needs_triage": all(s["needs_triage"] for s in subs)})
    unclustered = [records[i] for i in result["unclustered_ids"]]
    output = {"method": method, "records": result["records"], "themes": theme_list, "sub_themes": sub_themes,
              "unclustered": [{k: r[k] for k in ("id", "text", "date", "segment", "area", "sentiment", "category")}
                              for r in sorted(unclustered, key=lambda r: r["id"])],
              "multi_issue_records": sum(len(v) > 1 for v in result["sub_memberships"].values()),
              "interpretation": result["interpretation"],
              "evaluation": ("Phase 3.2 test half (themes merged at 0.8): purity 0.91, issue recall 0.82, 7/7 look-alike "
                             "issues separated. Fewer, broader themes are less pure: the loose themes shown here scored "
                             "purity 0.73 on development. Synthetic data; re-evaluate before trusting on real feedback.")}
    _cache[key] = output
    return output
