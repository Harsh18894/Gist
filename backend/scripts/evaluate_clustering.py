"""Evaluate Phase 3.2 clustering against the private v2 issue annotations.

Annotations are used only to score clusters. Records are split by a fixed hash of
their ID: configurations are chosen on the development half only, and each method's
chosen configuration is then scored once on the test half. Clustering itself runs
on all records and never sees the annotations. $0: no API calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from itertools import product
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.clustering import ClusterConfig, cluster, themes  # noqa: E402

DB = ROOT / "backend/gist-v2.sqlite3"
ANNOTATIONS = ROOT / "evals/v2/source_annotations.jsonl"
RESULTS = ROOT / "evals/phase32/results"
HARD_NEGATIVES = [("INVITE_LOOP", "RESET_LOGIN"), ("INVITE_LOOP", "SSO_SETUP"), ("RESET_LOGIN", "SSO_SETUP"),
                  ("CRM_SYNC", "CSV_MAPPING"), ("DASH_SLOW", "DASH_FILTER"), ("TEMPLATE_FIND", "TEMPLATE_ACCESS"),
                  ("DIGEST_NOISE", "ALERT_DELAY")]
GRID = {"tfidf": [round(0.05 * i, 2) for i in range(1, 9)], "embedding": [round(0.05 * i, 2) for i in range(7, 16)],
        "hybrid": [round(0.05 * i, 2) for i in range(4, 13)]}
SECONDARY = [0.45, 0.55]
VARIANTS = [{"remove_boilerplate": b, "area_weight": w} for b in (False, True) for w in (0.0, 0.3)]
TARGETS = {"purity": 0.85, "issue_recall": 0.75, "hard_negatives_separated": 6, "ambiguous_unclustered": 0.5,
           "multi_issue_both": 0.5}


def split_of(source_id: str) -> str:
    return "development" if int(hashlib.sha256(source_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


def load_truth() -> dict[str, list[str]]:
    rows = [json.loads(line) for line in ANNOTATIONS.read_text().splitlines() if line.strip()]
    return {r["source_id"]: r["issue_ids"] for r in rows if r["source_id"].startswith("V2-FB-")}


def adjusted_rand(a: list, b: list) -> float:
    table = Counter(zip(a, b))
    comb = lambda n: n * (n - 1) / 2
    index = sum(comb(n) for n in table.values())
    rows = sum(comb(n) for n in Counter(a).values())
    cols = sum(comb(n) for n in Counter(b).values())
    expected = rows * cols / comb(len(a)) if len(a) > 1 else 0
    maximum = (rows + cols) / 2
    return round((index - expected) / (maximum - expected), 4) if maximum != expected else 1.0


def score(result: dict, truth: dict[str, list[str]], split: str) -> dict:
    ids = [i for i in truth if split_of(i) == split]
    member = {i: result["memberships"][i] for i in ids}
    # Majority issue per cluster, from this split's records only.
    votes: dict[int, Counter] = {}
    for i in ids:
        for cid in member[i]:
            votes.setdefault(cid, Counter()).update(truth[i] or ["(ambiguous)"])
    majority = {cid: c.most_common(1)[0][0] for cid, c in votes.items()}
    single = [i for i in ids if len(truth[i]) == 1]
    clustered_single = [i for i in single if member[i]]
    purity = np.mean([truth[i][0] == majority[member[i][0]] for i in clustered_single]) if clustered_single else 0.0
    issues = sorted({x for i in ids for x in truth[i]})
    recall_by_issue = {}
    for issue in issues:
        having = [i for i in ids if issue in truth[i]]
        recall_by_issue[issue] = round(float(np.mean([any(majority.get(c) == issue for c in member[i]) for i in having])), 4)
    labels_true = [truth[i][0] for i in single]
    labels_pred = [member[i][0] if member[i] else f"noise-{i}" for i in single]
    home = {issue: Counter(member[i][0] for i in single if truth[i][0] == issue and member[i]).most_common(1) for issue in issues}
    home = {issue: (h[0][0] if h else None) for issue, h in home.items()}
    separated = [f"{a}/{b}" for a, b in HARD_NEGATIVES if home.get(a) is not None and home.get(a) != home.get(b)]
    fragmented = [issue for issue in issues if sum(1 for n in Counter(member[i][0] for i in single if truth[i][0] == issue and member[i]).values() if n >= 3) >= 2]
    mixed = [cid for cid, c in votes.items() if sum(c.values()) >= 3 and c.most_common(1)[0][1] / sum(c.values()) < 0.7]
    ambiguous = [i for i in ids if not truth[i]]
    multi = [i for i in ids if len(truth[i]) >= 2]
    return {"split": split, "records": len(ids), "clusters_used": len(votes),
            "purity": round(float(purity), 4), "issue_recall": round(float(np.mean(list(recall_by_issue.values()))), 4),
            "recall_by_issue": recall_by_issue, "adjusted_rand_index": adjusted_rand(labels_true, labels_pred),
            "single_issue_unclustered": round(1 - len(clustered_single) / len(single), 4),
            "hard_negatives_separated": len(separated), "hard_negative_pairs_separated": separated,
            "fragmented_issues": fragmented, "mixed_clusters": len(mixed),
            "ambiguous_unclustered": round(float(np.mean([not member[i] for i in ambiguous])), 4) if ambiguous else None,
            "multi_issue_both": round(float(np.mean([all(any(majority.get(c) == x for c in member[i]) for x in truth[i]) for i in multi])), 4) if multi else None}


def meets(metrics: dict) -> dict:
    return {k: (metrics[k] is not None and metrics[k] >= v) for k, v in TARGETS.items()}


def run() -> dict:
    truth = load_truth()
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        sweep = []
        configs = [ClusterConfig("category")] + [ClusterConfig(m, t, 3, s, **v) for m in ("tfidf", "embedding", "hybrid")
                                                 for t, s, v in product(GRID[m], SECONDARY, VARIANTS)]
        results = {}
        for config in configs:
            result = cluster(db, config)
            results[json.dumps(config.__dict__, sort_keys=True)] = result
            dev = score(result, truth, "development")
            sweep.append({"config": config.__dict__, "clusters": len(result["clusters"]), "development": dev})
    chosen = {}
    for method in ("category", "tfidf", "embedding", "hybrid"):
        candidates = [row for row in sweep if row["config"]["method"] == method]
        # Selection on development only: adjusted Rand index, then purity, then fewer unclustered single-issue records.
        best = max(candidates, key=lambda r: (r["development"]["adjusted_rand_index"], r["development"]["purity"],
                                              -r["development"]["single_issue_unclustered"]))
        test = score(results[json.dumps(best["config"], sort_keys=True)], truth, "test")
        chosen[method] = {"config": best["config"], "clusters": best["clusters"], "development": best["development"],
                          "test": test, "test_targets_met": meets(test)}
    return {"data": "Pulse v2 feedback (400 records); annotations used for scoring only",
            "split": "sha256(source_id) parity: even = development, odd = test",
            "targets": TARGETS, "selection_rule": "max development ARI, then purity, then fewer unclustered",
            "chosen": chosen, "development_sweep": sweep,
            "note": "Test half was viewed once for the baseline label; later methods are still selected on development only."}


THEME_TARGETS = {**TARGETS, "themes_at_most": 24}
SUB_CONFIGS = ([ClusterConfig(m, thr, 3, 0.45, remove_boilerplate=b) for m, thrs in (("embedding", (0.6, 0.65, 0.7, 0.75)),
                                                                                    ("hybrid", (0.5, 0.55, 0.6)))
                for thr in thrs for b in (False, True)]
               + [ClusterConfig("tfidf", thr, 3, 0.45, remove_boilerplate=True) for thr in (0.2, 0.25, 0.3, 0.35)])
THEME_THRESHOLDS = [round(0.05 * i, 2) for i in range(6, 18)]
THEME_SIGNALS = ("embedding", "words", "both")


def theme_score(result: dict, truth: dict, split: str) -> dict:
    metrics = score(result, truth, split)
    metrics["themes"] = len(result["themes"])
    return metrics


def theme_meets(metrics: dict) -> dict:
    met = meets(metrics)
    met["themes_at_most"] = metrics["themes"] <= THEME_TARGETS["themes_at_most"]
    return met


def run_themes() -> dict:
    """Sweep the hierarchy on development; score the selected configuration once on test."""
    truth = load_truth()
    sweep, results = [], {}
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        for sub_config, threshold, signal in product(SUB_CONFIGS, THEME_THRESHOLDS, THEME_SIGNALS):
            result = themes(db, sub_config, threshold, signal)
            key = json.dumps(result["config"], sort_keys=True)
            results[key] = result
            dev = theme_score(result, truth, "development")
            sweep.append({"config": result["config"], "development": dev, "development_targets_met": sum(theme_meets(dev).values())})
    best = max(sweep, key=lambda r: (r["development_targets_met"], r["development"]["adjusted_rand_index"]))
    test = theme_score(results[json.dumps(best["config"], sort_keys=True)], truth, "test")
    return {"data": "Pulse v2 feedback (400 records); annotations used for scoring only",
            "split": "sha256(source_id) parity: even = development, odd = test", "targets": THEME_TARGETS,
            "selection_rule": "max development targets met (incl. themes <= 24), then development ARI; test scored once",
            "chosen": {"config": best["config"], "development": best["development"], "test": test,
                       "test_targets_met": theme_meets(test)},
            "development_sweep": sweep}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--themes", action="store_true", help="Evaluate the theme -> sub-theme hierarchy")
    args = parser.parse_args()
    target = RESULTS / f"clustering-{args.label}.json"
    if target.exists():
        raise FileExistsError(f"{target} exists; evaluation results are immutable per label.")
    if args.themes:
        result = run_themes()
        RESULTS.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2) + "\n")
        c = result["chosen"]
        for split in ("development", "test"):
            m = c[split]
            print(f"{split:11} themes={m['themes']} purity={m['purity']} recall={m['issue_recall']} ARI={m['adjusted_rand_index']} "
                  f"hardneg={m['hard_negatives_separated']}/7 ambig_uncl={m['ambiguous_unclustered']} multi_both={m['multi_issue_both']} "
                  f"single_uncl={m['single_issue_unclustered']} mixed={m['mixed_clusters']} frag={len(m['fragmented_issues'])}")
        print("config:", json.dumps(c["config"]))
        print("test targets met:", c["test_targets_met"])
        print(f"Saved {target.relative_to(ROOT)}")
        return 0
    result = run()
    RESULTS.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    for method, row in result["chosen"].items():
        t = row["test"]
        print(f"{method:9} cfg={ {k: row['config'][k] for k in ('threshold', 'secondary_threshold', 'remove_boilerplate', 'area_weight')} } clusters={row['clusters']:3} "
              f"| TEST purity={t['purity']} recall={t['issue_recall']} ARI={t['adjusted_rand_index']} hardneg={t['hard_negatives_separated']}/7 "
              f"ambig_uncl={t['ambiguous_unclustered']} multi_both={t['multi_issue_both']} single_uncl={t['single_issue_unclustered']} "
              f"mixed={t['mixed_clusters']} frag={len(t['fragmented_issues'])}")
    print(f"Saved {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
