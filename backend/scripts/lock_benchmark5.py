"""Create or verify the Phase 2.3 lock for the one-time benchmark-5 final exam.

The lock fingerprints every file that can change the final-exam retrieval or answers,
the answer settings (including the paid context retriever), and the frozen benchmark
manifest. `create` never replaces a lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/scripts"))

from app.rag import provider, service  # noqa: E402
import import_phase21_review as review  # noqa: E402

LOCK = ROOT / "evals/phase23/answer-lock-benchmark5.json"
LOCKED_FILES = (
    "backend/app/rag/service.py", "backend/app/rag/provider.py", "backend/app/rag/evidence.py",
    "backend/app/rag/retrieval.py", "backend/app/rag/ingest.py", "backend/app/rag/budget.py",
    "backend/app/rag/candidate_v3.py", "backend/app/schemas.py", "backend/app/database.py",
    "backend/scripts/run_benchmark5_final.py", "backend/scripts/run_benchmark3_answers.py",
    "backend/scripts/evaluate_benchmark3_dev.py",
)
LOCKED_RETRIEVER = "hybrid"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state() -> dict:
    _draft, benchmark_dir, version = review.TARGETS["v5"]
    manifest = review.verify(benchmark_dir)
    return {"benchmark_version": version, "benchmark_manifest_sha256": _sha(benchmark_dir / "manifest.json"),
            "source_sha256": manifest["source_sha256"], "questions_sha256": manifest["questions_sha256"],
            "answer_config": {"paid_retriever": LOCKED_RETRIEVER, "embedding_model": provider.EMBED_MODEL,
                              "llm_model": provider.DEFAULT_LLM_MODEL, "context_sources": service.PAID_CONTEXT_SOURCES,
                              "snippet_chars": provider.SNIPPET_CHARS, "generation_byte_limit": provider.GENERATION_BYTE_LIMIT,
                              "max_output_tokens": provider.MAX_OUTPUT_TOKENS,
                              "source_metadata_sent": ["kind", "date", "segment", "product_area"],
                              "evidence_gate": "fact rules only in paid mode; explicit-cause rule",
                              "number_check": "trailing punctuation stripped; source dates count as evidence",
                              "statuses": ["answered", "partial", "insufficient_evidence"]},
            "files_sha256": {name: _sha(ROOT / name) for name in LOCKED_FILES}}


def create(lock: Path = LOCK) -> dict:
    if lock.exists():
        raise FileExistsError(f"{lock} exists; a lock is never replaced.")
    record = {**_state(), "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "selection": ("Phase 2.3 answer path developed on benchmark-3 development and consumed v4. The hybrid "
                            "retriever was kept because MMR gave no context gain and cited fewer evidence groups."),
              "policy": "Run the 24 v5 questions once. Do not tune or rerun against them."}
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps(record, indent=2) + "\n")
    return record


def verify_lock(lock: Path = LOCK) -> dict:
    if not lock.exists():
        raise FileNotFoundError("No benchmark-5 answer lock exists.")
    record = json.loads(lock.read_text())
    for key, value in _state().items():
        if record.get(key) != value:
            raise ValueError(f"Locked answer state changed: {key}.")
    return {**record, "lock_sha256": _sha(lock)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["create", "verify"])
    result = create() if parser.parse_args().command == "create" else verify_lock()
    print(json.dumps({k: v for k, v in result.items() if k != "files_sha256"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
