"""Create or verify the Phase 2.2 lock for the one-time benchmark-4 final exam.

The lock fingerprints every file that can change the final-exam retrieval or answers,
the answer settings, and the frozen benchmark manifest. `create` never replaces a lock.
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

LOCK = ROOT / "evals/phase22/answer-lock-benchmark4.json"
LOCKED_FILES = (
    "backend/app/rag/service.py", "backend/app/rag/provider.py", "backend/app/rag/evidence.py",
    "backend/app/rag/retrieval.py", "backend/app/rag/ingest.py", "backend/app/rag/budget.py",
    "backend/app/schemas.py", "backend/app/database.py",
    "backend/scripts/run_benchmark4_final.py", "backend/scripts/run_benchmark3_answers.py",
    "backend/scripts/evaluate_benchmark3_dev.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state() -> dict:
    _draft, benchmark_dir, version = review.TARGETS["v4"]
    manifest = review.verify(benchmark_dir)
    return {"benchmark_version": version, "benchmark_manifest_sha256": _sha(benchmark_dir / "manifest.json"),
            "source_sha256": manifest["source_sha256"], "questions_sha256": manifest["questions_sha256"],
            "answer_config": {"retriever": "locked v2 hybrid_search (retrieval.py)", "embedding_model": provider.EMBED_MODEL,
                              "llm_model": provider.DEFAULT_LLM_MODEL, "context_sources": service.PAID_CONTEXT_SOURCES,
                              "snippet_chars": provider.SNIPPET_CHARS, "generation_byte_limit": provider.GENERATION_BYTE_LIMIT,
                              "max_output_tokens": provider.MAX_OUTPUT_TOKENS,
                              "evidence_gate": "fact rules only in paid mode", "statuses": ["answered", "partial", "insufficient_evidence"]},
            "files_sha256": {name: _sha(ROOT / name) for name in LOCKED_FILES}}


def create(lock: Path = LOCK) -> dict:
    if lock.exists():
        raise FileExistsError(f"{lock} exists; a lock is never replaced.")
    record = {**_state(), "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "selection": ("Phase 2.2 answer path as developed on benchmark-3 development questions. Task 5 (MMR for "
                            "answers) was skipped by owner decision; the locked v2 hybrid remains the retriever."),
              "policy": "Run the 24 v4 questions once. Do not tune or rerun against them."}
    lock.write_text(json.dumps(record, indent=2) + "\n")
    return record


def verify_lock(lock: Path = LOCK) -> dict:
    if not lock.exists():
        raise FileNotFoundError("No benchmark-4 answer lock exists.")
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
