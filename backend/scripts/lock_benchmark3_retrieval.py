"""Create or verify the retrieval lock for the benchmark-3 final held-out run.

The lock hashes every file that can change held-out retrieval results, plus the
locked configuration and the frozen benchmark manifest. `create` refuses to
overwrite an existing lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/scripts"))

from app.rag.candidate_v3 import LOCKED_CONFIG  # noqa: E402
import import_phase21_review as review  # noqa: E402

LOCK = ROOT / "evals/phase21/retrieval-lock-benchmark3.json"
LOCKED_FILES = (
    "backend/app/rag/candidate_v3.py", "backend/app/rag/retrieval.py", "backend/app/rag/ingest.py",
    "backend/app/rag/evidence.py", "backend/app/rag/provider.py",
    "backend/scripts/evaluate_benchmark3_dev.py", "backend/scripts/evaluate_benchmark3_heldout.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state(root: Path = ROOT, benchmark_dir: Path = review.OUT) -> dict:
    manifest = review.verify(benchmark_dir)
    return {"benchmark_version": review.BENCHMARK_VERSION,
            "benchmark_manifest_sha256": _sha(benchmark_dir / "manifest.json"),
            "source_sha256": manifest["source_sha256"], "questions_sha256": manifest["questions_sha256"],
            "heldout_sha256": manifest["heldout_sha256"], "embedding_model": "text-embedding-3-small",
            "locked_config": asdict(LOCKED_CONFIG),
            "files_sha256": {name: _sha(root / name) for name in LOCKED_FILES}}


def create(lock: Path = LOCK) -> dict:
    if lock.exists():
        raise FileExistsError(f"{lock} exists; a lock is never replaced. Use a new benchmark version.")
    record = {**_state(), "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "selection": ("MMR lambda 0.7 chosen on 15 answerable development questions: best balance of Hit@5, "
                            "MRR@5 and evidence-group coverage, with neighbouring lambdas also above baseline."),
              "development_results": ["evals/phase21/results/benchmark3-development-baseline.json",
                                      "evals/phase21/results/benchmark3-development-trials-round1.json",
                                      "evals/phase21/results/benchmark3-development-trials-round2.json"],
              "policy": "Run the six held-out questions once. Do not tune or rerun against them."}
    lock.write_text(json.dumps(record, indent=2) + "\n")
    return record


def verify_lock(lock: Path = LOCK) -> dict:
    if not lock.exists():
        raise FileNotFoundError("No benchmark-3 retrieval lock exists.")
    record = json.loads(lock.read_text())
    current = _state()
    for key, value in current.items():
        if record.get(key) != value:
            raise ValueError(f"Locked retrieval state changed: {key}.")
    return {**record, "lock_sha256": _sha(lock)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["create", "verify"])
    args = parser.parse_args()
    result = create() if args.command == "create" else verify_lock()
    print(json.dumps({k: v for k, v in result.items() if k != "files_sha256"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
