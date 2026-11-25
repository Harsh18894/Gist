"""Import, validate, and freeze the Phase 2.1 human relevance review.

`check` reads the two completed review CSVs and reports blockers and warnings.
`freeze` writes a new immutable reviewed benchmark only when there are no blockers.
Human verdicts are authoritative; AI proposals are preserved separately and never
fill in a missing human decision. No retrieval or API call is made.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.dataset import fingerprint, source_dir, source_files  # noqa: E402

DRAFT = ROOT / "evals/phase21/benchmark-v2-draft.json"
DATA = source_dir("v2", ROOT)
OUT = ROOT / "evals/phase21/reviewed-v3"
BENCHMARK_VERSION = "gist-phase2.1-benchmark-3-reviewed"
# Benchmarks this importer can freeze: draft file, frozen output folder, reviewed version name.
TARGETS = {
    "v3": (DRAFT, OUT, BENCHMARK_VERSION),
    "v4": (ROOT / "evals/phase22/benchmark-v4-draft.json", ROOT / "evals/phase22/reviewed-v4",
           "gist-phase2.2-benchmark-4-reviewed"),
}

VERDICTS = {"supports", "partial", "unsupported", "unclear", "hard_negative"}
DECISIONS = {"approve", "revise", "unclear"}
COVERED = {"yes", "no", "unclear"}
COMPLETENESS = {"exhaustive", "reviewed_subset"}
FROZEN_QUESTION_FIELDS = ("split", "category", "question")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def corpus(data: Path = DATA) -> tuple[set[str], str]:
    """Return v2 source IDs and the same fingerprint the seeder records."""
    files = source_files(data)
    ids = {json.loads(line)["id"] for name in ("feedback.jsonl", "support-tickets.jsonl")
           for line in (data / name).read_text().splitlines() if line.strip()}
    ids |= {path.stem for path in files if path.suffix == ".md"}
    return ids, fingerprint(files)


def _base(header: str) -> str:
    # "your_source_verdict (supports/...)" -> "your_source_verdict"
    return header.split(" (", 1)[0].strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{_base(key): (value or "").strip() for key, value in row.items() if key is not None}
                for row in reader]


def split_ids(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;,]", value) if item.strip()]


def group_numbers(value: str) -> list[int] | None:
    items = split_ids(value)
    if not all(re.fullmatch(r"\d+", item) and int(item) > 0 for item in items):
        return None
    return sorted({int(item) for item in items})


def parse_group_text(value: str) -> list[list[str]]:
    """Parse 'Group 1: a, b | Group 2: c' from the AI proposal columns."""
    groups = []
    for part in value.split("|"):
        if ":" in part:
            groups.append(split_ids(part.split(":", 1)[1]))
    return [group for group in groups if group]


def _ai_role(row: dict[str, str]) -> str:
    if row.get("was_ai_reviewed_hard_negative") == "yes":
        return "hard_negative"
    if row.get("was_ai_reviewed_supporting_source") == "yes":
        return "supports"
    classification = row.get("ai_source_classification", "")
    if "partial" in classification:
        return "partial"
    if classification.startswith("not_individually_classified"):
        return "unclassified"  # The AI offered no verdict, so there is nothing to disagree with.
    if classification.startswith("ambiguous"):
        return "unclear"
    return "unsupported"


def _final_verdict(row: dict[str, str]) -> tuple[str | None, str | None]:
    """A second-reviewer resolution starting with a verdict overrides the first verdict."""
    resolution = row.get("second_reviewer_resolution", "")
    if resolution:
        word = re.split(r"[\s:;,.\-]+", resolution.lower(), maxsplit=1)[0]
        if word not in VERDICTS:
            return None, "second_reviewer_resolution must start with a verdict, e.g. 'supports: reason'"
        return word, None
    verdict = row.get("your_source_verdict", "").lower()
    return (verdict or None), None


@dataclass
class Review:
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disagreements: list[dict] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)

    def report(self) -> dict:
        return {"status": "READY_TO_FREEZE" if not self.blockers else "BLOCKED",
                "blocker_count": len(self.blockers), "warning_count": len(self.warnings),
                "blockers": self.blockers, "warnings": self.warnings,
                "human_ai_disagreements": self.disagreements}


def validate(question_rows: list[dict[str, str]], source_rows: list[dict[str, str]], *,
             draft: dict, corpus_ids: set[str], corpus_sha: str) -> Review:
    review = Review()
    block = review.blockers.append
    if draft.get("source_sha256") != corpus_sha:
        block("The v2 source corpus no longer matches the draft benchmark's source_sha256.")
    by_id = {question["id"]: question for question in draft["questions"]}
    seen: set[str] = set()
    for row in question_rows:
        qid = row.get("question_id", "")
        if qid in seen:
            block(f"{qid}: duplicate question row.")
        seen.add(qid)
        if qid not in by_id:
            block(f"{qid or '<blank>'}: question ID is not in the draft benchmark.")
            continue
        for name in FROZEN_QUESTION_FIELDS:
            if row.get(name, "") != by_id[qid][name]:
                block(f"{qid}: '{name}' was edited. Frozen question fields must stay unchanged; "
                      "put corrections in your_corrected_answer or comments.")
    for qid in sorted(set(by_id) - seen):
        block(f"{qid}: question row is missing from the questions CSV.")

    sources_by_question: dict[str, list[dict[str, str]]] = {}
    pairs: set[tuple[str, str]] = set()
    for row in source_rows:
        qid, sid = row.get("question_id", ""), row.get("source_id", "")
        if qid not in by_id:
            block(f"Source row {sid or '<blank>'}: question ID {qid or '<blank>'} is not in the draft.")
            continue
        if sid not in corpus_ids:
            block(f"{qid}/{sid or '<blank>'}: source ID does not exist in the Pulse v2 corpus.")
            continue
        if (qid, sid) in pairs:
            block(f"{qid}/{sid}: duplicate source row.")
            continue
        pairs.add((qid, sid))
        sources_by_question.setdefault(qid, []).append(row)

    for row in question_rows:
        qid = row.get("question_id", "")
        if qid not in by_id or qid in {q["id"] for q in review.questions}:
            continue
        review.questions.append(_question(row, by_id[qid], sources_by_question.get(qid, []),
                                          corpus_ids, review))
    return review


def _question(row: dict[str, str], draft_question: dict, sources: list[dict[str, str]],
              corpus_ids: set[str], review: Review) -> dict:
    qid = row["question_id"]
    block, warn = review.blockers.append, review.warnings.append
    unanswerable = draft_question["category"] == "unanswerable"
    listed = split_ids(row.get("all_source_ids_in_source_review_csv", ""))
    present = {source["source_id"] for source in sources}
    for sid in listed:
        if sid not in present:
            block(f"{qid}/{sid}: an original review row was deleted; keep every supplied row.")

    decision = row.get("question_reviewer_decision", "").lower()
    if decision not in DECISIONS:
        block(f"{qid}: question_reviewer_decision must be approve, revise, or unclear.")
    elif decision == "unclear":
        block(f"{qid}: question marked unclear; resolve it or record a second-reviewer decision.")
    corrected = row.get("your_corrected_answer", "")
    if decision == "revise" and not (corrected or row.get("your_question_comments")):
        block(f"{qid}: 'revise' needs a corrected answer or a comment explaining the revision.")
    if row.get("human_sign_off", "").lower() != "yes":
        block(f"{qid}: human_sign_off is not 'yes'.")
    completeness = row.get("judgments_are", "").lower()
    if completeness not in COMPLETENESS:
        block(f"{qid}: judgments_are must be exhaustive or reviewed_subset.")
    covered = row.get("all_evidence_groups_covered", "").lower()
    if not unanswerable and covered not in COVERED:
        block(f"{qid}: all_evidence_groups_covered must be yes, no, or unclear.")
    elif not unanswerable and covered != "yes":
        block(f"{qid}: reviewer says evidence groups are not all covered ({covered}).")
    reviewer = row.get("reviewer_name", "")
    if not reviewer:
        block(f"{qid}: reviewer_name is blank.")
    review_date = row.get("review_date", "")
    try:
        date.fromisoformat(review_date)
    except ValueError:
        block(f"{qid}: review_date '{review_date}' must be YYYY-MM-DD.")

    missing = split_ids(row.get("your_missing_source_ids", ""))
    for sid in missing:
        if sid not in corpus_ids:
            block(f"{qid}/{sid}: reported missing source does not exist in the Pulse v2 corpus.")
        elif sid not in present:
            block(f"{qid}/{sid}: reported missing source needs its own row in the sources CSV "
                  "with a verdict and evidence group.")

    groups: dict[int, list[str]] = {}
    buckets: dict[str, list[str]] = {verdict: [] for verdict in VERDICTS}
    judgments = []
    for source in sources:
        sid = source["source_id"]
        verdict, problem = _final_verdict(source)
        if problem:
            block(f"{qid}/{sid}: {problem}.")
            continue
        if verdict is None:
            block(f"{qid}/{sid}: source verdict is blank.")
            continue
        if verdict not in VERDICTS:
            block(f"{qid}/{sid}: unknown verdict '{verdict}'.")
            continue
        if verdict == "unclear":
            block(f"{qid}/{sid}: verdict is unclear and has no second-reviewer resolution.")
        numbers: list[int] = []
        if verdict == "supports":
            raw_group = source.get("your_corrected_evidence_group") or source.get("ai_reviewed_evidence_group_numbers", "")
            parsed = group_numbers(raw_group)
            if parsed is None:
                block(f"{qid}/{sid}: evidence group '{raw_group}' must be numbers like '1' or '1; 2'.")
            elif not parsed and not unanswerable:
                block(f"{qid}/{sid}: supporting source has no evidence group; fill your_corrected_evidence_group.")
            else:
                numbers = parsed
            for number in numbers:
                groups.setdefault(number, []).append(sid)
        buckets[verdict].append(sid)
        ai_role = _ai_role(source) if source.get("was_ai_reviewed_supporting_source") else None
        if ai_role and ai_role != "unclassified" and ai_role != verdict:
            review.disagreements.append({"question_id": qid, "split": draft_question["split"],
                                         "source_id": sid, "ai_proposal": ai_role, "human_final": verdict})
        if ai_role == "hard_negative" and verdict != "hard_negative":
            warn(f"{qid}/{sid}: human removed an AI-proposed hard negative ({verdict}).")
        if ai_role and ai_role != "hard_negative" and verdict == "hard_negative":
            warn(f"{qid}/{sid}: human added a hard negative.")
        if source.get("second_reviewer_resolution"):
            warn(f"{qid}/{sid}: final verdict comes from the second reviewer.")
        judgments.append({"source_id": sid, "human_verdict": source.get("your_source_verdict", "").lower() or None,
                          "final_verdict": verdict, "evidence_groups": numbers,
                          "comments": source.get("your_source_comments", ""),
                          "reviewer": source.get("human_reviewer") or reviewer,
                          "review_date": source.get("review_date") or review_date,
                          "second_reviewer_resolution": source.get("second_reviewer_resolution", ""),
                          "ai_proposal": ai_role})

    if unanswerable and buckets["supports"]:
        block(f"{qid}: unanswerable question has supporting sources {buckets['supports']}; "
              "the requested fact may exist. Recategorize in a new benchmark version.")
    if not unanswerable and not groups:
        block(f"{qid}: no human-supported evidence group.")
    proposed_groups = parse_group_text(row.get("ai_reviewed_evidence_groups", ""))
    if not unanswerable:
        for number in range(1, len(proposed_groups) + 1):
            if number not in groups:
                message = f"{qid}: proposed evidence group {number} has no human-supported source."
                # A deliberate 'revise' may drop a proposed group; anything else must cover it.
                (warn if decision == "revise" else block)(message)
    answer = corrected or row.get("proposed_answer_ai_reviewed", "")
    if not answer:
        block(f"{qid}: no expected answer or abstention.")
    return {"id": qid, "split": draft_question["split"], "category": draft_question["category"],
            "question": draft_question["question"],
            "expected_answer_or_abstention": answer,
            "answer_provenance": "human_corrected" if corrected else "ai_proposal_approved_by_human",
            "evidence_groups": [groups[number] for number in sorted(groups)],
            "relevant_source_ids": sorted(set(buckets["supports"])),
            "partial_source_ids": sorted(buckets["partial"]),
            "unsupported_source_ids": sorted(buckets["unsupported"]),
            "hard_negative_source_ids": sorted(buckets["hard_negative"]),
            "judgment_completeness": completeness,
            "review": {"decision": decision, "reviewer": reviewer, "review_date": review_date,
                       "sign_off": row.get("human_sign_off", "").lower(),
                       "all_evidence_groups_covered": covered or None,
                       "comments": row.get("your_question_comments", ""),
                       "missing_source_ids": missing,
                       "second_reviewer_comments": row.get("second_reviewer_comments", "")},
            "source_judgments": judgments,
            "ai_proposal": {"answer": row.get("proposed_answer_ai_reviewed", ""),
                            "evidence_groups": proposed_groups,
                            "supporting_source_ids": split_ids(row.get("ai_reviewed_supporting_source_ids", "")),
                            "hard_negative_source_ids": split_ids(row.get("ai_reviewed_hard_negative_source_ids", "")),
                            "findings": row.get("ai_review_findings", "")},
            "draft_labels": {"evidence_groups": draft_question["evidence_groups"],
                             "hard_negative_source_ids": draft_question["hard_negative_source_ids"]}}


def apply_corrections(questions_csv: Path, sources_csv: Path, corrections_path: Path,
                      out_dir: Path) -> tuple[Path, Path]:
    """Write corrected CSV copies; originals are never modified.

    Each correction names one cell and its expected current value, so a correction
    can never silently overwrite a value the reviewer changed afterwards.
    """
    corrections = json.loads(corrections_path.read_text())
    if not corrections.get("approved_by") or not corrections.get("approved_on"):
        raise ValueError("Corrections need approved_by and approved_on.")
    outputs = []
    for kind, path in (("questions", questions_csv), ("sources", sources_csv)):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or [])
            rows = list(reader)
        by_base = {_base(header): header for header in headers}
        for entry in (item for item in corrections["changes"] if item["file"] == kind):
            header = by_base.get(entry["field"])
            if header is None:
                raise ValueError(f"Unknown {kind} column '{entry['field']}'.")
            matches = [row for row in rows if row["question_id"] == entry["question_id"] and
                       (kind == "questions" or row["source_id"] == entry["source_id"])]
            if len(matches) != 1:
                raise ValueError(f"Correction target not unique: {entry}")
            if (matches[0][header] or "").strip() != entry["old"]:
                raise ValueError(f"Current value differs from expected 'old' value: {entry}")
            matches[0][header] = entry["new"]
        target = out_dir / f"{kind}-review.csv"
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        outputs.append(target)
    return outputs[0], outputs[1]


def load(questions_csv: Path, sources_csv: Path, *, draft_path: Path = DRAFT,
         data: Path = DATA) -> tuple[Review, dict]:
    draft = json.loads(draft_path.read_text())
    ids, sha = corpus(data)
    return validate(read_csv(questions_csv), read_csv(sources_csv), draft=draft,
                    corpus_ids=ids, corpus_sha=sha), draft


def freeze(questions_csv: Path, sources_csv: Path, *, out: Path = OUT,
           draft_path: Path = DRAFT, data: Path = DATA, corrections: Path | None = None,
           version: str = BENCHMARK_VERSION) -> dict:
    if out.exists():
        raise FileExistsError(f"{out} already exists. Reviewed benchmarks are immutable; create a new version.")
    staging = out.with_name(out.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        originals = questions_csv, sources_csv
        if corrections:
            questions_csv, sources_csv = apply_corrections(questions_csv, sources_csv, corrections, staging)
        review, draft = load(questions_csv, sources_csv, draft_path=draft_path, data=data)
        if review.blockers:
            raise ValueError(f"Review has {len(review.blockers)} blockers; run 'check' and resolve them first.")
        return _write_frozen(review, draft, questions_csv, sources_csv, out=out, draft_path=draft_path, version=version,
                             originals=originals if corrections else None, corrections=corrections)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _write_frozen(review: Review, draft: dict, questions_csv: Path, sources_csv: Path, *, out: Path, version: str,
                  draft_path: Path, originals: tuple[Path, Path] | None, corrections: Path | None) -> dict:
    questions = sorted(review.questions, key=lambda question: question["id"])
    heldout = [question for question in questions if question["split"] == "heldout"]
    reviewers = sorted({question["review"]["reviewer"] for question in questions})
    second = any(question["review"]["second_reviewer_comments"] or any(
        judgment["second_reviewer_resolution"] for judgment in question["source_judgments"])
        for question in questions)
    benchmark = {
        "benchmark_version": version, "dataset_version": "v2", "synthetic": True,
        "derived_from": {"benchmark_version": draft["benchmark_version"],
                         "file_sha256": sha256_bytes(draft_path.read_bytes())},
        "source_sha256": draft["source_sha256"],
        "questions_sha256": sha256_bytes(_canonical(questions)),
        "heldout_sha256": sha256_bytes(_canonical(heldout)),
        "split_counts": {"development": len(questions) - len(heldout), "heldout": len(heldout)},
        "human_review": {"reviewers": reviewers,
                         "review_dates": sorted({question["review"]["review_date"] for question in questions}),
                         "second_reviewer_involved": second,
                         "independence": ("Owner review of agent-proposed labels; not independent adjudication "
                                          "unless a second reviewer resolved disputes."),
                         "human_ai_disagreements": len(review.disagreements)},
        "label_policy": ("Human final verdicts are authoritative. evidence_groups are distinct evidence needs; "
                         "members are alternative human-supported sources. Partial, unsupported and hard-negative "
                         "sources are not relevant. Labels are a reviewed subset unless marked exhaustive."),
        "heldout_policy": "Do not tune on held-out questions. Run them once, after the retrieval lock.",
        "caveats": review.warnings,
        "questions": questions}
    files = ["benchmark.json", "review-report.json", "questions-review.csv", "sources-review.csv"]
    if corrections:
        record = json.loads(corrections.read_text())
        benchmark["owner_approved_corrections"] = {
            "approved_by": record["approved_by"], "approved_on": record["approved_on"],
            "summary": record.get("summary", []), "changed_cells": len(record["changes"]),
            "files": ["questions-review-original.csv", "sources-review-original.csv", "corrections.json"]}
        files += benchmark["owner_approved_corrections"]["files"]
    out.mkdir(parents=True)
    shutil.copyfile(questions_csv, out / "questions-review.csv")
    shutil.copyfile(sources_csv, out / "sources-review.csv")
    if corrections and originals:
        shutil.copyfile(originals[0], out / "questions-review-original.csv")
        shutil.copyfile(originals[1], out / "sources-review-original.csv")
        shutil.copyfile(corrections, out / "corrections.json")
    (out / "benchmark.json").write_text(json.dumps(benchmark, indent=2, ensure_ascii=False) + "\n")
    (out / "review-report.json").write_text(json.dumps(review.report(), indent=2, ensure_ascii=False) + "\n")
    manifest = {"benchmark_version": version, "frozen": True,
                "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_sha256": draft["source_sha256"],
                "questions_sha256": benchmark["questions_sha256"], "heldout_sha256": benchmark["heldout_sha256"],
                "development_ids": [q["id"] for q in questions if q["split"] == "development"],
                "heldout_ids": [q["id"] for q in heldout],
                "files_sha256": {name: sha256_bytes((out / name).read_bytes()) for name in files},
                "policy": benchmark["heldout_policy"]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify(out: Path = OUT) -> dict:
    """Recheck a frozen reviewed benchmark's file and content hashes."""
    manifest = json.loads((out / "manifest.json").read_text())
    for name, expected in manifest["files_sha256"].items():
        if sha256_bytes((out / name).read_bytes()) != expected:
            raise ValueError(f"{name} changed after freezing.")
    benchmark = json.loads((out / "benchmark.json").read_text())
    heldout = [q for q in benchmark["questions"] if q["split"] == "heldout"]
    if (sha256_bytes(_canonical(benchmark["questions"])) != manifest["questions_sha256"] or
            sha256_bytes(_canonical(heldout)) != manifest["heldout_sha256"]):
        raise ValueError("Benchmark question content does not match the manifest.")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "freeze"):
        command = commands.add_parser(name)
        command.add_argument("--questions", type=Path, required=True)
        command.add_argument("--sources", type=Path, required=True)
        command.add_argument("--corrections", type=Path, help="Owner-approved cell corrections (JSON)")
    commands.add_parser("verify")
    for command in commands.choices.values():
        command.add_argument("--benchmark", choices=sorted(TARGETS), default="v3")
    commands.choices["check"].add_argument("--report", type=Path, help="Optional JSON report path outside evals/")
    args = parser.parse_args()
    draft_path, out, version = TARGETS[args.benchmark]
    if args.command == "verify":
        print(json.dumps(verify(out), indent=2))
        return 0
    if args.command == "freeze":
        print(json.dumps(freeze(args.questions, args.sources, corrections=args.corrections, out=out,
                                draft_path=draft_path, version=version), indent=2))
        return 0
    if args.corrections:
        with tempfile.TemporaryDirectory() as scratch:
            corrected = apply_corrections(args.questions, args.sources, args.corrections, Path(scratch))
            review, _draft = load(*corrected, draft_path=draft_path)
    else:
        review, _draft = load(args.questions, args.sources, draft_path=draft_path)
    report = review.report()
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"Status: {report['status']} — {report['blocker_count']} blockers, "
          f"{report['warning_count']} warnings, {len(review.disagreements)} human/AI disagreements.")
    for line in review.blockers[:40]:
        print(f"  BLOCKER {line}")
    if len(review.blockers) > 40:
        print(f"  ... {len(review.blockers) - 40} more blockers (use --report for the full list)")
    for line in review.warnings:
        print(f"  WARNING {line}")
    return 0 if not review.blockers else 2


if __name__ == "__main__":
    sys.exit(main())
