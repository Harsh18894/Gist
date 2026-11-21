# Gist retrieval benchmark

`questions.json` contains 20 synthetic, source-linked questions: eight release-date questions and two questions for each of six PRDs. Expected answers are facts stated directly in the named Markdown files under `data/`. Questions are generated with the same deterministic script as the source corpus.

Run `.venv/bin/python backend/scripts/evaluate_retrieval.py` from the repository root. It measures source recall@1, recall@5, and MRR@5 for FTS5 alone and no-key hybrid retrieval. On the seeded Phase 2 corpus, keyword recall@1 was 0.65 and recall@5 was 1.00; local hybrid recall@1 and recall@5 were both 1.00. This small, term-overlapping fixture does not evaluate generated answers or real-world product insight quality. No LLM API calls are made by the evaluator.
