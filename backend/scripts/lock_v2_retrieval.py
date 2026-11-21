"""Freeze the exact retrieval implementation before the one-time held-out run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.freeze_v2_split import ROOT, verify

LOCK = ROOT / "evals/v2/retrieval-lock.json"
FILES = [ROOT / "backend/app/rag/retrieval.py", ROOT / "backend/scripts/run_v2_retrieval.py"]


def current() -> dict:
    manifest = verify()
    return {"dataset_version": "v2", "split_version": manifest["split_version"],
            "source_sha256": manifest["source_sha256"],
            "benchmark_sha256": manifest["benchmark_sha256"],
            "embedding_model": "text-embedding-3-small",
            "files_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in FILES},
            "decision": "Original chunk-level reciprocal rank fusion retained after source-level trial showed no development metric gain."}


def verify_lock() -> dict:
    saved = json.loads(LOCK.read_text())
    if saved != current():
        raise ValueError("Retrieval implementation or frozen benchmark changed after lock.")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    if args.create:
        if LOCK.exists():
            raise FileExistsError("Retrieval lock already exists; refusing to overwrite.")
        LOCK.write_text(json.dumps(current(), indent=2) + "\n")
    print(json.dumps(verify_lock(), indent=2))
