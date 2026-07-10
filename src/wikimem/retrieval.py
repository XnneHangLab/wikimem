"""In-memory BM25 retrieval with one-hop wiki-link expansion.

Hard constraints from the design (lab ADR-0001):

- retrieve makes **zero LLM calls** and is synchronous; hosts wrap it
  fail-open on their side.
- The index is **derived state**: built in memory from the store, never
  persisted. Store mutations bump a revision counter and the index rebuilds
  lazily. Out-of-band file edits are picked up by calling :meth:`rebuild`.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from .models import MemoryItem
from .store import MemoryStore
from .tokenize import est_tokens, tokenize

_K1 = 1.5
_B = 0.75


@dataclass
class RetrievedItem:
    """One entry in an injection sequence."""

    item: MemoryItem
    source: str  # "hit" (BM25 match) or "link" (one-hop wiki-link expansion)
    score: float | None = None  # BM25 score; None for link expansions
    via: str | None = None  # parent item name, for source == "link"
    matched_terms: list[str] = field(default_factory=list)
    tokens_est: int = 0


@dataclass
class RetrievalResult:
    items: list[RetrievedItem]  # survived the budget, in injection order
    budget_tokens: int | None
    budget_used: int
    dropped: list[RetrievedItem] = field(default_factory=list)  # populated when explain=True
    unresolved_links: list[str] = field(default_factory=list)  # links whose target is missing


class MemoryIndex:
    """BM25 index over a :class:`MemoryStore`, rebuilt lazily on store writes."""

    def __init__(self, store: MemoryStore, *, use_jieba: bool | None = None) -> None:
        self.store = store
        self._use_jieba = use_jieba
        self._built_revision: int | None = None
        self._docs: list[tuple[MemoryItem, Counter[str], int]] = []
        self._df: Counter[str] = Counter()
        self._avg_len = 0.0
        self._by_key: dict[tuple[str, str], MemoryItem] = {}

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

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 10,
        budget_tokens: int | None = None,
        expand_links: bool = True,
        explain: bool = False,
    ) -> RetrievalResult:
        """Rank items by BM25, expand each hit's wiki-links one hop, trim to budget.

        Injection order: each hit is followed by its resolved link targets
        (deduplicated globally). Budget trimming is a prefix cut — the first
        entry is always kept, even if it alone exceeds the budget.
        """
        self._ensure_fresh()
        query_terms = tokenize(query, use_jieba=self._use_jieba)
        result = RetrievalResult(items=[], budget_tokens=budget_tokens, budget_used=0)
        if not query_terms or not self._docs:
            return result

        scored: list[RetrievedItem] = []
        for item, counts, doc_len in self._docs:
            score = self._bm25(query_terms, counts, doc_len)
            if score <= 0.0:
                continue
            scored.append(
                RetrievedItem(
                    item=item,
                    source="hit",
                    score=score,
                    matched_terms=sorted({t for t in query_terms if counts.get(t)}),
                    tokens_est=est_tokens(f"{item.name}\n{item.content}"),
                )
            )
        scored.sort(key=lambda r: r.score or 0.0, reverse=True)
        scored = scored[:limit]

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
