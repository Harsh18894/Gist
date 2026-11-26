"""Evaluate Phase 3.4 prioritization robustness on Pulse v2. $0, read-only, no API calls.

There is no ground truth for priority, so this checks the criteria set in PLAN.md before the run:
- robustness: each default weight changed by -50% / +50% (10 variants); top-10 overlap with the
  default ranking must have mean >= 7/10 and minimum >= 5/10;
- not just volume: Spearman correlation between the evidence score and reach must be < 0.9.
PM estimates are not used (the pure scorer is called with no inputs).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import issues  # noqa: E402
from app.opportunities import build  # noqa: E402
from app.priorities import DEFAULT_WEIGHTS, raw_parts, score  # noqa: E402

DB = ROOT / "backend/gist-v2.sqlite3"
RESULTS = ROOT / "evals/phase34/results"
TARGETS = {"mean_top10_overlap": 7, "min_top10_overlap": 5, "max_spearman_with_reach": 0.9}


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return cov / ((sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5)


def run() -> dict:
    issues._cache.clear()
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        cards = build(db)["opportunities"]
    base = score(cards, DEFAULT_WEIGHTS)
    top = [r["opportunity_id"] for r in base[:10]]
    variants = []
    for part in DEFAULT_WEIGHTS:
        for factor in (0.5, 1.5):
            weights = {**DEFAULT_WEIGHTS, part: round(DEFAULT_WEIGHTS[part] * factor)}
            rows = score(cards, weights)
            by_id = {r["opportunity_id"]: r["evidence_score"] for r in rows}
            variants.append({"changed": part, "factor": factor, "weights": weights,
                             "top10_overlap": len(set(top) & {r["opportunity_id"] for r in rows[:10]}),
                             "spearman_with_default": round(spearman([r["evidence_score"] for r in base],
                                                                     [by_id[r["opportunity_id"]] for r in base]), 4)})
    overlaps = [v["top10_overlap"] for v in variants]
    reach = {c["id"]: raw_parts(c)["reach"] for c in cards}
    rho_reach = spearman([r["evidence_score"] for r in base], [reach[r["opportunity_id"]] for r in base])
    summary = {"mean_top10_overlap": round(sum(overlaps) / len(overlaps), 2), "min_top10_overlap": min(overlaps),
               "spearman_with_reach": round(rho_reach, 4)}
    met = {"mean_top10_overlap": summary["mean_top10_overlap"] >= TARGETS["mean_top10_overlap"],
           "min_top10_overlap": summary["min_top10_overlap"] >= TARGETS["min_top10_overlap"],
           "not_just_volume": summary["spearman_with_reach"] < TARGETS["max_spearman_with_reach"]}
    return {"data": "Pulse v2 (synthetic); no PM estimates applied", "opportunities": len(cards), "targets": TARGETS,
            "summary": summary, "targets_met": met, "default_top10": top, "variants": variants}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    target = RESULTS / f"robustness-{parser.parse_args().label}.json"
    if target.exists():
        raise FileExistsError(f"{target} exists; results are immutable per label.")
    result = run()
    RESULTS.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"]), result["targets_met"])
    for v in result["variants"]:
        print(f"  {v['changed']:>9} x{v['factor']}: top-10 overlap {v['top10_overlap']}/10, spearman {v['spearman_with_default']}")
    print(f"Saved {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
