"""Phase 5.2: portfolio docs stay true. Links resolve, and README results equal the versioned result files."""
import csv
import re
from pathlib import Path

import pytest

from app import observability

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_relative_links_and_images_resolve(doc):
    for match in LINK.finditer(doc.read_text()):
        target = (match.group(1) or match.group(2)).split("#")[0]
        if not target or re.match(r"^(https?:|mailto:)", target):
            continue
        assert (doc.parent / target).resolve().exists(), f"{doc.name}: broken link {target}"


def _value(run_id: str, key: str):
    run = next(r for r in observability.benchmarks()["runs"] if r["id"] == run_id)
    return next(m["value"] for m in run["metrics"] if m["key"] == key)


def _pct(v):
    return f"{v * 100:.1f}%"


def _answerable_good(path: str) -> int:
    rows = csv.DictReader((ROOT / path).open())
    return sum(1 for r in rows if r["category"] != "unanswerable" and r["overall (good/acceptable/poor)"] == "good")


def test_readme_results_match_result_files():
    readme = (ROOT / "README.md").read_text()
    expected = [
        _pct(_value("p2-v2-heldout-hybrid", "hit_at_5")),                                       # 38.9%
        f"{_pct(_value('p22-b4-final', 'hit_at_5'))} / {_pct(_value('p23-b5-final', 'hit_at_5'))}",
        f"{_answerable_good('evals/phase22/results/benchmark4-final-answer-review-completed.csv')} / "
        f"{_answerable_good('evals/phase23/results/benchmark5-final-answer-review-completed.csv')}",
        f"{_value('p32-clustering', 'purity'):.2f} / {_value('p32-clustering', 'issue_recall'):.2f} / "
        f"{_value('p32-clustering', 'hard_negatives')} of 7",
        f"{_value('p32-clustering', 'themes')} themes",
        f"{_value('p33-linking', 'ticket_precision'):.2f} / {_value('p33-linking', 'doc_top1'):.2f}",
        f"{_value('p34-robustness', 'overlap')} of 10",
        f"{_value('p35-experiment-review', 'useful')} / {_value('p35-experiment-review', 'sensible_metric')} / 0",
        f"{_value('p44-heldout', 'planted')} of {_value('p44-heldout', 'planted_total')}",
        f"{_value('p44-heldout', 'decoy_top')} of 4",
    ]
    for text in expected:
        assert text in readme, f"README should state {text!r} (from the result files)"
