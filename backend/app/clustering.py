"""Phase 3.2 issue discovery: deterministic clustering of feedback, with explanations.

Methods:
- ``category``: the existing ``issue_category`` label (baseline; "Unclear"/"Multiple issues" stay unclustered).
- ``tfidf``: word (unigram + bigram) TF-IDF vectors, cosine, average-linkage clustering.
- ``embedding``: the stored ``text-embedding-3-small`` chunk vectors (already paid for), same clustering.

Multi-issue records: each record's sentences are also compared with every cluster's word
centroid; a strong sentence match attaches the record to that cluster too. Labels and
explanations always come from TF-IDF terms, so they are readable and deterministic.
No model calls are made. Ground-truth annotations are never used here.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .rag.ingest import STOPWORDS

EMBED_MODEL = "text-embedding-3-small"
EXTRA_STOPWORDS = {"the", "this", "that", "our", "we", "they", "but", "just", "now", "can", "not", "isn", "don", "doesn",
                   "was", "has", "have", "had", "been", "still", "into", "out", "one", "also", "there", "then", "than",
                   "you", "your", "its", "it's", "are", "for", "with", "from", "when", "what", "why", "which", "who",
                   "about", "after", "before", "again", "only", "some", "any", "all", "each", "every", "same", "very"}
STOP = set(STOPWORDS) | EXTRA_STOPWORDS
UNCLUSTERED_CATEGORIES = {"Unclear", "Multiple issues"}


@dataclass(frozen=True)
class ClusterConfig:
    method: str = "tfidf"
    threshold: float = 0.3            # stop merging when average-linkage similarity falls below this
    min_size: int = 3                 # smaller groups are reported as unclustered
    secondary_threshold: float = 0.45  # sentence-to-centroid similarity that adds a second membership
    remove_boilerplate: bool = False  # drop sentences repeated across several product areas
    area_weight: float = 0.0          # weight of product-area metadata in the similarity
    embedding_share: float = 0.5      # hybrid only: share of similarity from learned vectors

    def __post_init__(self) -> None:
        if self.method not in {"category", "tfidf", "embedding", "hybrid"}:
            raise ValueError("method must be category, tfidf, embedding or hybrid")
        if not 0 < self.threshold < 1 or not 0 < self.secondary_threshold <= 1 or not 2 <= self.min_size <= 50:
            raise ValueError("threshold and secondary_threshold must be in (0, 1]; min_size 2–50")
        if not 0 <= self.area_weight <= 1 or not 0 <= self.embedding_share <= 1:
            raise ValueError("area_weight and embedding_share must be between 0 and 1")


def terms(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP and not w.isdigit()]
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?:])\s+|\s*Also:\s*", text)
    return [p.strip() for p in parts if len(terms(p)) >= 2]


def _norm_sentence(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def boilerplate(records: list[dict], min_records: int = 3, min_areas: int = 3) -> set[str]:
    """Sentences repeated verbatim in many records across several product areas (filler, sign-offs).

    Uses only text and product-area metadata, never issue labels.
    """
    areas: dict[str, set[str]] = {}
    counts: Counter = Counter()
    for record in records:
        for sentence in {_norm_sentence(s) for s in sentences(record["text"])}:
            counts[sentence] += 1
            areas.setdefault(sentence, set()).add(record["area"])
    return {s for s, n in counts.items() if n >= min_records and len(areas[s]) >= min_areas}


def clean(text: str, filler: set[str]) -> str:
    kept = [s for s in sentences(text) if _norm_sentence(s) not in filler]
    return " ".join(kept) if kept else text


@dataclass
class Vectorizer:
    vocab: dict[str, int] = field(default_factory=dict)
    idf: np.ndarray | None = None

    def fit(self, docs: list[str]) -> "Vectorizer":
        counts = Counter(term for doc in docs for term in set(terms(doc)))
        kept = sorted(term for term, n in counts.items() if n >= 2)  # ignore one-off terms
        self.vocab = {term: i for i, term in enumerate(kept)}
        n = len(docs)
        self.idf = np.array([math.log((1 + n) / (1 + counts[t])) + 1 for t in kept], dtype=np.float32)
        return self

    def transform(self, docs: list[str]) -> np.ndarray:
        matrix = np.zeros((len(docs), len(self.vocab)), dtype=np.float32)
        for row, doc in enumerate(docs):
            for term, count in Counter(terms(doc)).items():
                column = self.vocab.get(term)
                if column is not None:
                    matrix[row, column] = (1 + math.log(count)) * self.idf[column]
        return _normalize(matrix)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)


def average_linkage(vectors: np.ndarray, threshold: float) -> np.ndarray:
    """Agglomerative clustering with average linkage on cosine similarity; returns a label per row."""
    n = len(vectors)
    sim = vectors @ vectors.T
    np.fill_diagonal(sim, -np.inf)
    sizes = np.ones(n)
    active = np.ones(n, dtype=bool)
    labels = np.arange(n)
    while True:
        masked = np.where(active[:, None] & active[None, :], sim, -np.inf)
        flat = int(np.argmax(masked))
        a, b = divmod(flat, n)
        if masked[a, b] < threshold:
            break
        merged = (sim[a] * sizes[a] + sim[b] * sizes[b]) / (sizes[a] + sizes[b])
        sim[a, :] = merged
        sim[:, a] = merged
        sim[a, a] = -np.inf
        sizes[a] += sizes[b]
        active[b] = False
        sim[b, :] = -np.inf
        sim[:, b] = -np.inf
        labels[labels == b] = a
    return labels


def _records(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute("""SELECT id, feedback_text, substr(timestamp,1,10) AS day, customer_segment, product_area,
        sentiment, issue_category, related_feature FROM feedback ORDER BY id""").fetchall()
    return [dict(zip(("id", "text", "date", "segment", "area", "sentiment", "category", "feature"), row)) for row in rows]


def _embeddings(db: sqlite3.Connection, ids: list[str]) -> np.ndarray:
    vectors = {}
    for source_id, blob in db.execute("""SELECT c.source_id, e.vector FROM embeddings e JOIN chunks c ON c.id = e.chunk_id
            WHERE e.model = ?""", (EMBED_MODEL,)):
        vectors.setdefault(source_id, []).append(np.frombuffer(blob, dtype=np.float32))
    missing = [i for i in ids if i not in vectors]
    if missing:
        raise RuntimeError(f"{len(missing)} feedback records have no stored {EMBED_MODEL} vector; use method tfidf.")
    return _normalize(np.vstack([np.mean(vectors[i], axis=0) for i in ids]).astype(np.float32))


def cluster(db: sqlite3.Connection, config: ClusterConfig) -> dict:
    records = _records(db)
    filler = boilerplate(records) if config.remove_boilerplate else set()
    texts = [clean(r["text"], filler) for r in records]
    vectorizer = Vectorizer().fit(texts)
    words = vectorizer.transform(texts)
    if config.method == "category":
        names = sorted({r["category"] for r in records if r["category"] not in UNCLUSTERED_CATEGORIES})
        labels = np.array([names.index(r["category"]) if r["category"] in names else -1 for r in records])
    else:
        if config.method == "tfidf":
            vectors = words
        elif config.method == "embedding":
            vectors = _embeddings(db, [r["id"] for r in records])
        else:  # hybrid: cosine of the concatenation = share * learned + (1 - share) * words
            learned = _embeddings(db, [r["id"] for r in records])
            vectors = np.hstack([np.sqrt(config.embedding_share) * learned, np.sqrt(1 - config.embedding_share) * words])
        if config.area_weight:
            names = sorted({r["area"] for r in records})
            onehot = np.array([[float(r["area"] == a) for a in names] for r in records], dtype=np.float32)
            vectors = _normalize(np.hstack([np.sqrt(1 - config.area_weight) * _normalize(vectors),
                                            np.sqrt(config.area_weight) * onehot]))
        labels = average_linkage(vectors, config.threshold)
    groups: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        if label >= 0:
            groups.setdefault(int(label), []).append(index)
    kept = [members for members in groups.values() if len(members) >= config.min_size]
    kept.sort(key=lambda members: (-len(members), records[members[0]]["id"]))
    primary = {index: cid for cid, members in enumerate(kept) for index in members}
    centroids = _normalize(np.vstack([words[m].mean(axis=0) for m in kept])) if kept else np.zeros((0, words.shape[1]))
    vocabulary = sorted(vectorizer.vocab, key=vectorizer.vocab.get)

    # Second memberships from sentence-level matches (multi-issue records, or records left unclustered).
    secondary: dict[int, dict[int, float]] = {}
    if len(kept):
        for index, record in enumerate(records):
            parts = [s for s in sentences(record["text"]) if _norm_sentence(s) not in filler]
            if len(parts) < 2 and index in primary:
                continue
            sims = vectorizer.transform(parts) @ centroids.T if parts else np.zeros((0, len(kept)))
            for cid in range(len(kept)):
                best = float(sims[:, cid].max()) if len(parts) else 0.0
                if cid != primary.get(index) and best >= config.secondary_threshold:
                    secondary.setdefault(index, {})[cid] = round(best, 4)

    latest = max(date.fromisoformat(r["date"]) for r in records)
    recent_start, prior_start = latest - timedelta(days=89), latest - timedelta(days=179)
    clusters = []
    for cid, members in enumerate(kept):
        centroid = centroids[cid]
        top = [vocabulary[i] for i in np.argsort(-centroid)[:8] if centroid[i] > 0]
        unigrams = [t for t in top if " " not in t]
        phrase = [t for t in top if " " in t][:1]
        # Skip single words already inside the leading two-word phrase ("stable week / stable").
        label = " / ".join((phrase + [u for u in unigrams if not phrase or u not in phrase[0].split()])[:3])
        member_sims = words[members] @ centroid
        all_members = members + [i for i, extra in secondary.items() if cid in extra]
        days = sorted(records[i]["date"] for i in all_members)
        recent = sum(recent_start.isoformat() <= d for d in days)
        prior = sum(prior_start.isoformat() <= d < recent_start.isoformat() for d in days)
        explained = []
        for i in all_members:
            record_terms = set(terms(records[i]["text"]))
            is_primary = i in members
            explained.append({"id": records[i]["id"], "membership": "primary" if is_primary else "secondary",
                              "similarity": round(float(words[i] @ centroid if is_primary else secondary[i][cid]), 4),
                              "shared_terms": [t for t in top if t in record_terms][:4]})
        explained.sort(key=lambda m: (m["membership"] != "primary", -m["similarity"], m["id"]))
        clusters.append({
            "id": f"C{cid + 1:02d}", "label": label, "top_terms": top,
            "size": len(members), "secondary_members": len(all_members) - len(members),
            "distinct_texts": len({re.sub(r'[^a-z0-9]+', ' ', records[i]['text'].lower()).strip() for i in members}),
            "representative_ids": [records[members[j]]["id"] for j in np.argsort(-member_sims)[:3]],
            "categories": dict(Counter(records[i]["category"] for i in members).most_common()),
            "segments": dict(Counter(records[i]["segment"] for i in all_members).most_common()),
            "areas": dict(Counter(records[i]["area"] for i in all_members).most_common()),
            "sentiment": dict(Counter(records[i]["sentiment"] for i in all_members).most_common()),
            "first_date": days[0], "last_date": days[-1],
            "recent_90_days": recent, "prior_90_days": prior,
            "trend": "new" if prior == 0 and recent > 0 and days[0] >= prior_start.isoformat()
                     else "rising" if recent >= max(3, 1.5 * prior) else "falling" if prior >= max(3, 1.5 * recent) else "steady",
            "members": explained})
    unclustered = [records[i]["id"] for i in range(len(records)) if i not in primary and i not in secondary]
    return {"config": config.__dict__, "records": len(records), "boilerplate_sentences": sorted(filler),
            "clusters": clusters, "unclustered_ids": unclustered,
            "memberships": {records[i]["id"]: ([primary[i]] if i in primary else []) + sorted(secondary.get(i, {}))
                            for i in range(len(records))},
            "interpretation": ("Clusters are word- or vector-similarity groups, not confirmed root causes. Labels are the "
                               "group's most distinctive terms; check representative records before acting.")}


def themes(db: sqlite3.Connection, sub_config: ClusterConfig, theme_threshold: float,
           theme_signal: str = "embedding") -> dict:
    """Two-level hierarchy: clean sub-themes from `cluster`, merged into broader themes.

    Theme similarity compares sub-theme centroids. Averaging a sub-theme's member vectors
    cancels much of the per-record filler, so centroids carry the shared complaint.
    `theme_signal` is "embedding" (stored learned vectors), "words" (TF-IDF) or "both".
    """
    if theme_signal not in {"embedding", "words", "both"}:
        raise ValueError("theme_signal must be embedding, words or both")
    if not 0 < theme_threshold < 1:
        raise ValueError("theme_threshold must be in (0, 1)")
    sub = cluster(db, sub_config)
    records = _records(db)
    index = {r["id"]: i for i, r in enumerate(records)}
    filler = set(sub["boilerplate_sentences"])
    vectorizer = Vectorizer().fit([clean(r["text"], filler) for r in records])
    words = vectorizer.transform([clean(r["text"], filler) for r in records])
    primary = [[index[m["id"]] for m in c["members"] if m["membership"] == "primary"] for c in sub["clusters"]]
    parts = []
    if theme_signal in {"embedding", "both"}:
        learned = _embeddings(db, [r["id"] for r in records])
        parts.append(_normalize(np.vstack([learned[m].mean(axis=0) for m in primary])) if primary else np.zeros((0, 1)))
    if theme_signal in {"words", "both"}:
        parts.append(_normalize(np.vstack([words[m].mean(axis=0) for m in primary])) if primary else np.zeros((0, 1)))
    centroids = _normalize(np.hstack(parts)) if primary else np.zeros((0, 1))
    labels = average_linkage(centroids, theme_threshold) if len(primary) > 1 else np.zeros(len(primary), dtype=int)
    order = sorted(set(int(x) for x in labels), key=lambda t: (-sum(sub["clusters"][i]["size"] for i in range(len(primary)) if labels[i] == t), t))
    theme_of_sub = {i: order.index(int(labels[i])) for i in range(len(primary))}
    vocabulary = sorted(vectorizer.vocab, key=vectorizer.vocab.get)
    out = []
    for tid in range(len(order)):
        subs = [i for i in range(len(primary)) if theme_of_sub[i] == tid]
        member_idx = sorted({j for i in subs for j in primary[i]})
        centroid = _normalize(words[member_idx].mean(axis=0, keepdims=True))[0]
        top = [vocabulary[i] for i in np.argsort(-centroid)[:6] if centroid[i] > 0]
        out.append({"id": f"T{tid + 1:02d}", "label": " / ".join([t for t in top if " " not in t][:3]), "top_terms": top,
                    "size": len(member_idx), "sub_themes": [sub["clusters"][i]["id"] for i in subs]})
    memberships = {rid: sorted({theme_of_sub[c] for c in cids}) for rid, cids in sub["memberships"].items()}
    return {"config": {"sub": sub_config.__dict__, "theme_threshold": theme_threshold, "theme_signal": theme_signal},
            "records": sub["records"], "themes": out, "sub_themes": sub["clusters"],
            "theme_of_sub_theme": {sub["clusters"][i]["id"]: out[theme_of_sub[i]]["id"] for i in range(len(primary))},
            "memberships": memberships, "sub_memberships": sub["memberships"], "unclustered_ids": sub["unclustered_ids"],
            "boilerplate_sentences": sub["boilerplate_sentences"], "interpretation": sub["interpretation"]}
