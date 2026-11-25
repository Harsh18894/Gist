# Gist

**Turn customer feedback into product decisions.** Gist is a local Product Intelligence Copilot prototype for Product Managers. It explores fictional Pulse customer feedback, calculates SQLite summaries, and retrieves source evidence in Ask Gist. The entire dataset is synthetic. The default retrieval demo requires no API key and makes no paid calls.

## Stack and structure

- `frontend/` — Next.js App Router, TypeScript, Tailwind CSS UI.
- `backend/app/` — FastAPI routes, Pydantic contracts, SQLite services, and RAG modules.
- `backend/scripts/` — deterministic generator, seeder, importer, guarded embedding command, and evaluation.
- `backend/tests/` — data, API, filter, and metric tests.
- `data/` — unchanged Pulse v1 sources; `data/v2/` — versioned synthetic Pulse v2 sources.
- `evals/` — v1 benchmark; `evals/v2/` — 50 questions and private source annotations.
- `docs/` — architecture and learning notes.

## Local setup

Requires Python 3.11+ and Node.js 20+. Verified during development with Python 3.14.7 and Node.js 25.2.1. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
python3 backend/scripts/generate_data.py
.venv/bin/python backend/scripts/seed.py --dataset v1
(cd frontend && npm install)
```

The v1 generator uses a fixed seed. It creates exactly 400 feedback records, 120 support tickets, six PRDs, eight release notes, and 20 benchmark questions. The v1 seeder builds 534 searchable sources and 534 chunks with local demo vectors. **Seeding refuses to overwrite an existing database.** If you intentionally rebuild a database after source changes, pass `--replace`; this clears imported sources and stored embeddings. The local database is ignored by Git.

## Pulse Dataset v2

Pulse v2 is a more varied, still entirely fictional feedback fixture. It has 400 feedback entries, 120 support conversations, 14 product documents, private multi-label source annotations, and 50 benchmark questions. It includes ambiguous reports, hard negatives, mixed reactions, and release-aware timelines. See [dataset quality review](docs/dataset-v2-quality.md). The original v1 files remain unchanged.

From the repository root, generate and seed v2 without API calls:

```sh
.venv/bin/python backend/scripts/generate_v2.py --replace
.venv/bin/python backend/scripts/audit_v2.py --json evals/v2/quality-audit.json
.venv/bin/python backend/scripts/seed.py --dataset v2
GIST_DATASET_VERSION=v2 npm run dev
```

The committed v2 source files are already generated. If `backend/gist-v2.sqlite3` already exists, the seed command stops; use `--replace` only when you intend to rebuild that v2 database. To switch back, run `npm run dev` with `GIST_DATASET_VERSION` unset (v1 default). If you set `GIST_DB_PATH`, point it at the matching version's database. `/api/rag/status` reports the active version and source fingerprint. The API rejects a version mismatch or source files changed after indexing. Never index `evals/v2/`; it contains hidden answers. Neither version automatically generates OpenAI embeddings.

## Run Gist

From the repository root (`gist %`), one command starts both servers:

```sh
npm run dev
```

You can also use two terminals. Start the API from the repository root:

```sh
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --reload --port 8000
```

Start the frontend from the repository root in the second terminal:

```sh
cd frontend
npm run dev
```

If that terminal is already in `frontend/`, run only `npm run dev`. Python virtual environment activation does not change directories; npm looks for `package.json` in the current directory.

Visit `http://localhost:3000`. API docs are at `http://localhost:8000/docs`. The frontend defaults to `http://localhost:8000`; set `NEXT_PUBLIC_GIST_API_URL` if needed. Optional configuration is documented in `.env.example`. Never put secrets in a `NEXT_PUBLIC_` variable.

## Ask Gist and ingestion

Ask Gist defaults to **local retrieval only**. It combines SQLite FTS5 keyword ranking and cosine similarity over deterministic token-hash vectors, then shows clickable retrieved sources. It does not synthesize an answer or call those sources generated citations. The local vectors are lexical stand-ins, not OpenAI embeddings. Questions asking for facts absent from the sources return an insufficient-evidence state, even if topically related records were retrieved.

To import **synthetic** CSV, TXT, or Markdown sources from a local file:

```sh
.venv/bin/python backend/scripts/rag.py import data/examples/example.csv
.venv/bin/python backend/scripts/rag.py import data/examples/example.txt --segment SMB --product-area Billing --source-date 2025-09-01
.venv/bin/python backend/scripts/rag.py import data/examples/example.md
```

These example files are included in `data/examples/`. CSV requires a `text`, `content`, `feedback_text`, or `description` column. Optional columns include `title`, `segment`/`customer_segment`, `product_area`, and `source_date`/`date`/`timestamp`. Text and Markdown accept the metadata flags shown above; Markdown also reads `Published:` and `Product area:` lines. Reimporting unchanged content preserves cached embeddings; changed content invalidates its vectors. Files are limited to 5 MB. Keep all imports synthetic.

The OpenAI path is implemented but **disabled by default**. It requires explicit user approval, a server-side key, both `GIST_ENABLE_PAID_API=true` and `GIST_PAID_EVAL_APPROVED=true`, and a positive cap. The project-wide ledger atomically reserves at least $0.05 per request and enforces a maximum **$0.50** validation allocation across embeddings and generation. Reported tokens reconcile successful reservations; uncertain requests retain theirs and are not retried automatically. The ledger is an estimate; compare it with provider billing. Never put the key in a `NEXT_PUBLIC_` variable. The app does not automatically load `.env.example` or `backend/.env`.

## Verify

```sh
PYTHONPATH=backend .venv/bin/pytest backend/tests -q
(cd frontend && npm run build)
.venv/bin/python backend/scripts/evaluate_retrieval.py
```

The legacy evaluator defaults to the original v1 benchmark. Pulse v2 uses a frozen 30-question development and 20-question held-out split. Run `.venv/bin/python backend/scripts/freeze_v2_split.py` to verify its hashes. The old `--dataset v2` evaluator is disabled because it would expose the held-out set. The learned-vector development comparison and the **one-time** frozen held-out evaluation are complete; see [Phase 2 validation](docs/phase2-validation.md). Do not rerun or tune against the held-out set in this benchmark version. Do not interpret demo hash-vector scores as learned semantic retrieval quality.

For a reproducible read-only v2 preflight, run:

```sh
.venv/bin/python backend/scripts/freeze_v2_split.py
.venv/bin/python backend/scripts/preflight_v2.py
.venv/bin/python backend/scripts/run_v2_retrieval.py --split development
.venv/bin/python backend/scripts/check_v2_demo_answers.py
```

The development and held-out results are in `evals/v2/results/`. `evals/v2/development-judgments.json` contains additional source-reviewed, **non-exhaustive** development labels and evidence groups. The original benchmark and held-out split remain hash-frozen. For the read-only retrieval lock, index inventory, and shared cost ledger:

```sh
PYTHONPATH=backend .venv/bin/python backend/scripts/lock_v2_retrieval.py
PYTHONPATH=backend .venv/bin/python backend/scripts/rag.py index-preflight
PYTHONPATH=backend .venv/bin/python backend/scripts/rag.py spend-report
```

The authorized validation indexed **536/536** learned v2 vectors. The retrieval configuration is locked in `evals/v2/retrieval-lock.json`; the final held-out set has already been run once. Saved development and final results are reviewable without further API calls. Any future paid run requires new explicit approval. Review generated claims and citations with [the answer rubric](evals/v2/answer-review-rubric.md). An interrupted embedding batch with uncertain billing stops and requires manual reconciliation; it is never automatically rebilled.

Phase 2.1 has an **experimental offline retriever** with bounded local subqueries and a separate [retrieval improvement report](docs/phase2-retrieval-improvements.md). It is not the Ask Gist default. Its draft 24-question benchmark under `evals/phase21/` needs independent human relevance review; do not run its held-out questions for tuning. After the owner completes the review CSVs, `backend/scripts/import_phase21_review.py check` validates them and `freeze` writes an immutable reviewed benchmark; see [the review guide](evals/phase21/human-review.md). Exact paid-mode query embeddings are now cached by model and dataset fingerprint, while source embeddings and the frozen v2 baseline remain intact.

Phase 2.1 final validation is complete: see [the report](docs/phase21-final-validation.md). Held-out retrieval Hit@5 was 0.80 on five questions, but only 5 of 20 answerable answers were rated good in the owner's claim review. Proposed release readiness: **FAIL**.

## API

Phase 1: `GET /api/health`, `GET /api/stats`, `GET /api/records`, and `GET /api/records/{id}`. Phase 2: `GET /api/search` (`keyword`, `semantic`, or `hybrid`), `POST /api/ask`, `GET /api/sources/{id}`, `GET /api/rag/status`, and `GET /api/usage`. Search and Ask support segment, product-area, and inclusive date filters. Ask defaults to `mode: "demo"`; `mode: "openai"` is guarded. Invalid input returns structured 422 errors. Retrieval-only results use `retrieved_sources`; generated answers use `citations`. The source endpoint returns the indexed original text for verification.

## Known limitations

The no-key demo uses token-hash vectors, so its cosine ranking is lexical and should not be described as learned semantic understanding. OpenAI embeddings and Responses answering were exercised in a bounded paid validation; the resulting Phase 2 release readiness is **FAIL** because held-out retrieval is weak and one answerable multi-source development case abstained. Judgments are non-exhaustive, so the reported scores are conditional. A valid citation ID does not prove a qualitative claim is supported; independent human claim-level review remains required. Opportunity ranking, authentication, and deployment remain future work. SQLite is local single-user storage. The shared ledger records **$0.00141804 estimated external API cost** from 137 completed requests, with zero uncertain requests, against the $0.50 local allocation. Provider billing was not independently verified.
