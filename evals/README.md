# Evaluation

Everything in this folder is used to measure Gist. It is **never indexed** for search, because it contains expected answers and hidden labels. The in-app **Evaluation** page reads these result files directly through `evals/registry.json`, and shows each file's SHA-256 hash.

## How results were judged

| Judged by | Used for | How |
|---|---|---|
| **Automatic** | Clustering, ticket and document linking, prioritization robustness, investigations | Code scores each run against a fixed key: hidden source annotations (`v2/source_annotations.jsonl`), an owner-reviewed document key (`phase33/document-issue-key.json`), or the product-events answer key of planted causes and decoys (`phase4/events-answer-key.json`). |
| **Owner** | Retrieval relevance labels, answer quality, experiment usefulness | The project owner labelled sources and rated each generated answer with a written rubric ([`v2/answer-review-rubric.md`](v2/answer-review-rubric.md)): claims supported (all, some or none), correct abstention, and overall (good, acceptable or poor). Experiment cards were rated useful, needs work or wrong. Only the counts are published, in the `*-review-summary.json` files. |
| **AI judge** | Calibration only | An AI claim-support judge ([`phase21/answer-judge-prompt.md`](phase21/answer-judge-prompt.md)) was compared with the owner's labels and **not adopted**; human review remains the measure. |

## Rules that make the numbers trustworthy

- **Targets were written before each run** and never loosened afterwards. Results below target are shown as accepted limitations.
- **Held-out sets were frozen** (a hash split, a SHA-256 manifest and a lock covering the evaluated code) and **run exactly once**. Results are written with exclusive create, so a run can't be silently repeated.
- **Development and held-out data are kept apart.** Prompts and settings were only iterated on development sets.
- **Every paid run had a cost estimate and a hard stop**, and was recorded in a spend ledger.

## Layout

| Folder | Contents |
|---|---|
| `v1/`, `questions.json` | The original 20-question fixture (release dates and PRD facts). |
| `v2/` | The Pulse v2 benchmark: 50 questions, hash split, retrieval lock, hidden source annotations. |
| `phase21/`, `phase22/`, `phase23/` | Benchmarks 3–5: frozen question sets, locks and held-out results for retrieval and answers. |
| `phase32/`–`phase35/` | Product intelligence: clustering, linking, prioritization robustness, experiment review. |
| `phase4/`, `phase43/`, `phase44/` | The investigation answer key, the development runs, and the one-time held-out run. |
| `registry.json` | Which result files and metrics the Evaluation page shows, with each run's status against its targets. |
| `regressions.json` | Past failures and the tests that guard against them. |

The original v1 retrieval check (`backend/scripts/evaluate_retrieval.py`) measures recall@1, recall@5 and MRR@5 on the 20-question fixture with no API calls.
