"""In-memory BM25 retrieval with one-hop wiki-link expansion.

Hard constraints from the design (lab ADR-0001):

- retrieve makes **zero LLM calls** and is synchronous; hosts wrap it
  fail-open on their side.
- The BM25 index is **derived state**: built in memory from the store, never
  persisted. Store mutations bump a revision counter and the index rebuilds
  lazily. Out-of-band file edits are picked up by calling :meth:`rebuild`.

Optional embedding fusion (M3, the ``[embed]`` extra): pass an ``embedder``
and BM25 scores are min-max fused with cosine scores from a persistent
vector cache (see :mod:`wikimem.vectors`). The embedding path degrades
silently to BM25-only when the embedder fails — retrieval never raises for
a down endpoint (``RetrievalResult.embedding_used`` tells you which path ran).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .models import MemoryItem
from .store import MemoryStore
from .tokenize import est_tokens, tokenize

_K1 = 1.5
_B = 0.75


@dataclass
class RetrievedItem:
    """One entry in an injection sequence."""

    item: MemoryItem
    source: str  # "hit" (search match) or "link" (one-hop wiki-link expansion)
    score: float | None = None  # ranking score: fused when embedding ran, else BM25
    bm25_score: float | None = None
    cos_score: float | None = None
    via: str | None = None  # parent item name, for source == "link"
    matched_terms: list[str] = field(default_factory=list)
    tokens_est: int = 0


@dataclass
class RetrievalResult:
    items: list[RetrievedItem]  # survived the budget, in injection order
    budget_tokens: int | None
    budget_used: int
    embedding_used: bool = False
    dropped: list[RetrievedItem] = field(default_factory=list)  # populated when explain=True
    unresolved_links: list[str] = field(default_factory=list)  # links whose target is missing


def _minmax(raw: dict[int, float]) -> dict[int, float]:
    if not raw:
        return {}
    lo, hi = min(raw.values()), max(raw.values())
    if hi <= lo:
        return {k: (1.0 if v > 0 else 0.0) for k, v in raw.items()}
    return {k: (v - lo) / (hi - lo) for k, v in raw.items()}


class MemoryIndex:
    """BM25 (+ optional embedding fusion) over a :class:`MemoryStore`.

    ``embedder`` activates the ``[embed]`` extra path: vectors live in a
    persistent content-hash cache under ``vectors_dir`` (default: the store
    root) and search runs through :class:`wikimem.vectors.MemmapVectorIndex`
    — see that module for the RAM/tier story. ``fusion_weight`` is the BM25
    share of the fused score (cosine gets ``1 - fusion_weight``).
    """

    def __init__(
        self,
        store: MemoryStore,
        *,
        use_jieba: bool | None = None,
        embedder=None,
        vectors_dir: Path | str | None = None,
        fusion_weight: float = 0.5,
        binary_threshold: int = 10_000,
    ) -> None:
        self.store = store
        self._use_jieba = use_jieba
        self._embedder = embedder
        self._vectors_dir = Path(vectors_dir) if vectors_dir is not None else store.root
        self._fusion_weight = fusion_weight
        self._binary_threshold = binary_threshold
        self._built_revision: int | None = None
        self._docs: list[tuple[MemoryItem, Counter[str], int]] = []
        self._df: Counter[str] = Counter()
        self._avg_len = 0.0
        self._by_key: dict[tuple[str, str], MemoryItem] = {}
        self._vec_index = None  # wikimem.vectors.MemmapVectorIndex, rows == doc order

    # ----------------------------------------------------------------- build

    def rebuild(self) -> None:
        """Rescan the store. Cheap at personal-memory scale (a few MB of text)."""
        self._docs = []
        self._df = Counter()
        self._by_key = {}
        total_len = 0
        for item in self.store.items():
            tokens = tokenize(f"{item.name}\n{item.content}", use_jieba=self._use_jieba)
            counts = Counter(tokens)
            self._docs.append((item, counts, len(tokens)))
            self._df.update(counts.keys())
            self._by_key[(item.category, item.name)] = item
            total_len += len(tokens)
        self._avg_len = (total_len / len(self._docs)) if self._docs else 0.0
        self._built_revision = self.store.revision
        self._vec_index = None
        if self._embedder is not None and self._docs:
            from .vectors import MemmapVectorIndex, VectorCache  # Lazy-import: [embed] extra

            cache = VectorCache(self._vectors_dir)
            entries = [
                ((item.category, item.name), f"{item.name}\n{item.content}")
                for item, _, _ in self._docs
            ]
            _, matrix = cache.sync(entries, self._embedder)
            if matrix is not None:
                self._vec_index = MemmapVectorIndex(matrix, binary_threshold=self._binary_threshold)

    def _ensure_fresh(self) -> None:
        if self._built_revision != self.store.revision:
            self.rebuild()

    # ---------------------------------------------------------------- search

    def _bm25(self, query_terms: list[str], counts: Counter[str], doc_len: int) -> float:
        n = len(self._docs)
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            df = self._df[term]
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            norm = tf * (_K1 + 1) / (tf + _K1 * (1 - _B + _B * doc_len / (self._avg_len or 1.0)))
            score += idf * norm
        return score

    def _cosine_scores(self, query: str, top_k: int) -> dict[int, float] | None:
        """Row -> cosine score via the vector index; None when the path is off/degraded."""
        if self._vec_index is None or self._embedder is None:
            return None
        try:
            query_vec = self._embedder.embed([query])[0]
            return {
                row: score for row, score in self._vec_index.search(query_vec, top_k) if score > 0.0
            }
        except Exception:  # noqa: BLE001 - fail-open: embedding endpoint down != retrieval down
            return None

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 10,
        budget_tokens: int | None = None,
        expand_links: bool = True,
        explain: bool = False,
    ) -> RetrievalResult:
        """Rank items, expand each hit's wiki-links one hop, trim to budget.

        Ranking: BM25 alone by default; with an embedder, BM25 and cosine are
        each min-max normalized over the candidate union and fused by
        ``fusion_weight``. Injection order: each hit is followed by its
        resolved link targets (deduplicated globally). Budget trimming is a
        prefix cut — the first entry is always kept.
        """
        self._ensure_fresh()
        query_terms = tokenize(query, use_jieba=self._use_jieba)
        result = RetrievalResult(items=[], budget_tokens=budget_tokens, budget_used=0)
        if not self._docs or (not query_terms and self._vec_index is None):
            return result

        bm25_raw: dict[int, float] = {}
        for row, (_, counts, doc_len) in enumerate(self._docs):
            score = self._bm25(query_terms, counts, doc_len)
            if score > 0.0:
                bm25_raw[row] = score

        cos_raw = self._cosine_scores(query, top_k=max(limit * 4, limit))
        if cos_raw is not None:
            result.embedding_used = True
            bm25_norm = _minmax(bm25_raw)
            cos_norm = _minmax(cos_raw)
            candidates = set(bm25_raw) | set(cos_raw)
            fused = {
                row: self._fusion_weight * bm25_norm.get(row, 0.0)
                + (1 - self._fusion_weight) * cos_norm.get(row, 0.0)
                for row in candidates
            }
            ranking = [(row, fused[row]) for row in candidates if fused[row] > 0.0]
        else:
            ranking = list(bm25_raw.items())
        ranking.sort(key=lambda pair: pair[1], reverse=True)
        ranking = ranking[:limit]

        scored: list[RetrievedItem] = []
        for row, rank_score in ranking:
            item, counts, _ = self._docs[row]
            scored.append(
                RetrievedItem(
                    item=item,
                    source="hit",
                    score=rank_score,
                    bm25_score=bm25_raw.get(row),
                    cos_score=cos_raw.get(row) if cos_raw is not None else None,
                    matched_terms=sorted({t for t in query_terms if counts.get(t)}),
                    tokens_est=est_tokens(f"{item.name}\n{item.content}"),
                )
            )

        # One-hop link expansion, dedup across the whole sequence.
        sequence: list[RetrievedItem] = []
        seen: set[tuple[str, str]] = set()
        for hit in scored:
            key = (hit.item.category, hit.item.name)
            if key in seen:
                continue
            seen.add(key)
            sequence.append(hit)
            if not expand_links:
                continue
            for link in hit.item.links:
                target_key = (link.category, link.name)
                if target_key in seen:
                    continue
                target = self._by_key.get(target_key)
                if target is None:
                    result.unresolved_links.append(link.render())
                    continue
                seen.add(target_key)
                sequence.append(
                    RetrievedItem(
                        item=target,
                        source="link",
                        via=hit.item.name,
                        tokens_est=est_tokens(f"{target.name}\n{target.content}"),
                    )
                )

        # Prefix budget cut.
        used = 0
        for pos, entry in enumerate(sequence):
            over = budget_tokens is not None and used + entry.tokens_est > budget_tokens
            if over and pos > 0:
                if explain:
                    result.dropped = sequence[pos:]
                break
            result.items.append(entry)
            used += entry.tokens_est
        result.budget_used = used
        return result
