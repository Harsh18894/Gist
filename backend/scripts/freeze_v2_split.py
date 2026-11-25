"""Create or verify the immutable-by-hash Pulse v2 benchmark split."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.dataset import fingerprint, require_complete, source_dir, source_files  # noqa: E402
from app.errors import SourceFilesMissing  # noqa: E402

BENCHMARK = ROOT / "evals/v2/questions.json"
MANIFEST = ROOT / "evals/v2/split-manifest.json"
SEED = 271027
TEST_COUNTS = {"direct": 6, "semantic": 6, "multi_source": 4,
               "contradiction_ambiguity": 2, "unanswerable": 2}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_hash() -> str:
    try:
        files = require_complete(source_files(source_dir("v2", ROOT)), "v2")
    except SourceFilesMissing as exc:
        raise ValueError("Pulse v2 source set is incomplete.") from exc  # unchanged error for callers
    return fingerprint(files)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", value.lower())


def cross_split_similarity(questions: list[dict], dev: set[str], test: set[str]) -> dict:
    by_id = {item["id"]: item for item in questions}
    maximum = ("", "", 0.0)
    for left in sorted(dev):
        for right in sorted(test):
            ratio = SequenceMatcher(None, _normalize(by_id[left]["question"]),
                                    _normalize(by_id[right]["question"])).ratio()
            if ratio > maximum[2]:
                maximum = (left, right, ratio)
    return {"pair": [maximum[0], maximum[1]], "normalized_sequence_similarity": round(maximum[2], 3)}


def make_manifest() -> dict:
    raw = BENCHMARK.read_bytes()
    benchmark = json.loads(raw)
    if benchmark.get("dataset_version") != "v2" or len(benchmark["questions"]) < 50:
        raise ValueError("Expected the versioned v2 benchmark with at least 50 questions.")
    groups: dict[str, list[str]] = defaultdict(list)
    for item in benchmark["questions"]:
        groups[item["evaluation_category"]].append(item["id"])
    if set(groups) != set(TEST_COUNTS):
        raise ValueError("Benchmark categories changed; review the split manually.")
    rng = random.Random(SEED)
    test: set[str] = set()
    for category, count in TEST_COUNTS.items():
        ids = sorted(groups[category])
        test.update(rng.sample(ids, count))
    dev = {item["id"] for item in benchmark["questions"]} - test
    similarity = cross_split_similarity(benchmark["questions"], dev, test)
    if similarity["normalized_sequence_similarity"] >= .72:
        raise ValueError(f"Potential near-duplicate questions cross the split: {similarity}")
    question_hashes = {item["id"]: _sha(json.dumps(item, sort_keys=True, ensure_ascii=False,
                                                   separators=(",", ":")).encode())
                       for item in benchmark["questions"]}
    heldout_payload = json.dumps([item for item in benchmark["questions"] if item["id"] in test],
                                 sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {"dataset_version": "v2", "split_version": "v2-baseline-1", "frozen": True,
            "selection_seed": SEED, "source_sha256": source_hash(), "benchmark_sha256": _sha(raw),
            "heldout_content_sha256": _sha(heldout_payload), "question_sha256": question_hashes,
            "development_ids": sorted(dev), "heldout_test_ids": sorted(test),
            "category_test_counts": TEST_COUNTS, "maximum_cross_split_similarity": similarity,
            "policy": "Use development only for tuning; run held-out once for the final locked comparison."}


def verify() -> dict:
    saved = json.loads(MANIFEST.read_text())
    current = make_manifest()
    if saved != current:
        raise ValueError("Frozen split or source/benchmark hashes changed. Do not evaluate until reviewed.")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--create", action="store_true", help="Create the split once; refuses an existing manifest")
    args = parser.parse_args()
    if args.create:
        if MANIFEST.exists():
            raise FileExistsError("The v2 split is already frozen; refusing to overwrite it.")
        MANIFEST.write_text(json.dumps(make_manifest(), indent=2) + "\n")
    result = verify()
    print(json.dumps({key: result[key] for key in ("split_version", "source_sha256", "benchmark_sha256",
                                                   "heldout_content_sha256", "maximum_cross_split_similarity")}, indent=2))
