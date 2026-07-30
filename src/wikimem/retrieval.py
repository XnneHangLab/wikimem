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
from datetime import date as _date
from datetime import timedelta, tzinfo
from pathlib import Path

from .models import DiaryItem, RecallItem
from .store import MemoryStore
from .timeparse import TimeRange, parse_time_range
from .tokenize import est_tokens, tokenize

_K1 = 1.5
_B = 0.75

#: Category shown for diary entries that surface through retrieval. Diary files
#: live in ``diary/``, not ``wiki/``, so this never collides with a real
#: wiki RecallFile — it is a display/dedup key, not a place on disk.
DIARY_FILE = "diary"


def _entry_as_item(entry: DiaryItem) -> RecallItem:
    """View a diary entry as an item, so one pipeline ranks both layers.

    Both primitives are the same ``##``-block shape (ADR-0001) — an event's
    "name" is simply its time. Adapting here is what lets ADR-0002's promise be
    literal: BM25, min-max fusion, the budget cut, and explain all keep working
    untouched, and a ``[[work:current-job]]`` written inside a diary entry still
    expands to the wiki item it points at.

    (The rendered name contains ``:``, so a diary entry cannot itself be a
    wiki-link *target* — pointing at diary entries was left open in ADR-0001.)
    """
    return RecallItem(
        file=DIARY_FILE,
        name=f"{entry.date} {entry.time}",
        content=entry.content,
        owner=entry.owner,
        source_conv=entry.source_conv,
        ts=entry.ts,
    )


@dataclass
class RetrievedItem:
    """One entry in an injection sequence."""

    item: RecallItem
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
    # Time gate (ADR-0002): which diary window was applied, and where it came from.
    time_range: TimeRange | None = None
    time_range_source: str | None = None  # "explicit" (caller) | "parsed" (regex fast path)
    time_range_widened: bool = False  # window held nothing, so it was relaxed by a day


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
        self._docs: list[tuple[RecallItem, Counter[str], int]] = []
        self._df: Counter[str] = Counter()
        self._avg_len = 0.0
        self._by_key: dict[tuple[str, str], RecallItem] = {}
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
            self._by_key[(item.file, item.name)] = item
            total_len += len(tokens)
        self._avg_len = (total_len / len(self._docs)) if self._docs else 0.0
        self._built_revision = self.store.revision
        self._vec_index = None
        if self._embedder is not None and self._docs:
            from .vectors import MemmapVectorIndex, VectorCache  # Lazy-import: [embed] extra

            cache = VectorCache(self._vectors_dir)
            entries = [
                ((item.file, item.name), f"{item.name}\n{item.content}")
                for item, _, _ in self._docs
            ]
            _, matrix = cache.sync(entries, self._embedder)
            if matrix is not None:
                self._vec_index = MemmapVectorIndex(matrix, binary_threshold=self._binary_threshold)

    def _ensure_fresh(self) -> None:
        if self._built_revision != self.store.revision:
            self.rebuild()

    # ---------------------------------------------------------------- search

    def _bm25(
        self,
        query_terms: list[str],
        counts: Counter[str],
        doc_len: int,
        *,
        n: int | None = None,
        df: Counter[str] | None = None,
        avg_len: float | None = None,
    ) -> float:
        """BM25 for one document. Corpus stats default to the cached wiki index.

        They are overridable because a time-gated query scores wiki items and
        windowed diary entries **in the same pass**: BM25 is corpus-relative, so
        both must see the same ``n`` / ``df`` / ``avg_len`` or their scores are
        not comparable and merging them would be meaningless.
        """
        n = len(self._docs) if n is None else n
        df = self._df if df is None else df
        avg_len = self._avg_len if avg_len is None else avg_len
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
            norm = tf * (_K1 + 1) / (tf + _K1 * (1 - _B + _B * doc_len / (avg_len or 1.0)))
            score += idf * norm
        return score

    def _diary_docs(self, window: TimeRange) -> list[tuple[RecallItem, Counter[str], int]]:
        """Windowed diary entries, tokenized like wiki docs.

        Built per query rather than cached: the candidate set depends on the
        window, and a window is only a handful of day files (the filename *is*
        the time index), so there is nothing worth persisting.
        """
        docs: list[tuple[RecallItem, Counter[str], int]] = []
        for entry in self.store.diary.window(*window):
            item = _entry_as_item(entry)
            tokens = tokenize(f"{item.name}\n{item.content}", use_jieba=self._use_jieba)
            docs.append((item, Counter(tokens), len(tokens)))
        return docs

    def _resolve_window(
        self, query: str, time_range: TimeRange | None, tz: tzinfo | None
    ) -> tuple[TimeRange | None, str | None]:
        """The window to gate on, and where it came from.

        Two ways in (ADR-0002 §1): the caller passes one — the exit of a host's
        intent recognition or tool call — or the regex fast path finds one in the
        query. Nothing else: regex is the floor, the host's LLM is the ceiling.

        A reversed pair is normalized here, once, so everything downstream can
        assume ``start <= end``. :meth:`Diary.window` tolerates a reversed pair
        on its own, but leaving one in place would report the window backwards
        in ``explain`` and — worse — make :meth:`_widen` shrink it rather than
        widen it, silently disabling the empty-window fallback.
        """
        if time_range is not None:
            start, end = time_range
            return (end, start) if start > end else (start, end), "explicit"
        parsed = parse_time_range(query, tz=tz)
        return (parsed, "parsed") if parsed is not None else (None, None)

    @staticmethod
    def _widen(window: TimeRange, days: int = 1) -> TimeRange:
        """Relax a window by a day on each side (ADR-0002 §4).

        An empty window usually means the boundary was slightly off — a late
        night filed under the next day, a fuzzy "上周中午". Better to look a day
        wider than to answer "I don't remember" because of one parse.
        """
        start = _date.fromisoformat(window[0]) - timedelta(days=days)
        end = _date.fromisoformat(window[1]) + timedelta(days=days)
        return start.isoformat(), end.isoformat()

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
        time_range: TimeRange | None = None,
        tz: tzinfo | None = None,
    ) -> RetrievalResult:
        """Rank items, expand each hit's wiki-links one hop, trim to budget.

        Ranking: BM25 alone by default; with an embedder, BM25 and cosine are
        each min-max normalized over the candidate union and fused by
        ``fusion_weight``. Injection order: each hit is followed by its
        resolved link targets (deduplicated globally). Budget trimming is a
        prefix cut — the first entry is always kept.

        **Time gate** (ADR-0002): ``time_range`` is an inclusive
        ``("YYYY-MM-DD", "YYYY-MM-DD")`` pair; when omitted, the regex fast path
        looks for one in ``query`` (``tz`` picks the calendar it resolves
        against). A window brings the diary entries of those days into the same
        ranking as the wiki — time **filters candidates**, it never votes on
        them, so the fusion formula is untouched. Wiki items keep competing
        unfiltered (§7: the timeline belongs to the diary). With no window,
        behaviour is exactly as before.
        """
        self._ensure_fresh()
        query_terms = tokenize(query, use_jieba=self._use_jieba)
        result = RetrievalResult(items=[], budget_tokens=budget_tokens, budget_used=0)

        window, source = self._resolve_window(query, time_range, tz)
        diary_docs: list[tuple[RecallItem, Counter[str], int]] = []
        if window is not None:
            result.time_range, result.time_range_source = window, source
            diary_docs = self._diary_docs(window)
            if not diary_docs:  # nothing in the window — relax rather than come back empty
                widened = self._widen(window)
                diary_docs = self._diary_docs(widened)
                if diary_docs:
                    result.time_range, result.time_range_widened = widened, True

        if not self._docs and not diary_docs:
            return result
        if not query_terms:
            # Degenerate case (§3): no usable query, but a window — answer with
            # the window itself, most recent first. This is "recall the diary"
            # working on its own, without time ever becoming a scoring path.
            if diary_docs:
                return self._finish(
                    [
                        RetrievedItem(
                            item=item,
                            source="hit",
                            tokens_est=est_tokens(f"{item.name}\n{item.content}"),
                        )
                        for item, _, _ in sorted(diary_docs, key=lambda d: d[0].name, reverse=True)
                    ][:limit],
                    result,
                    budget_tokens,
                )
            if self._vec_index is None:
                return result

        # Wiki rows keep index 0..len(self._docs)-1 so they stay aligned with the
        # vector index; diary rows are appended after them.
        docs = self._docs + diary_docs
        n, df, avg_len = len(self._docs), self._df, self._avg_len
        if diary_docs:
            df = self._df.copy()
            total_len = self._avg_len * len(self._docs)
            for _, counts, doc_len in diary_docs:
                df.update(counts.keys())
                total_len += doc_len
            n = len(docs)
            avg_len = total_len / n if n else 0.0

        bm25_raw: dict[int, float] = {}
        for row, (_, counts, doc_len) in enumerate(docs):
            score = self._bm25(query_terms, counts, doc_len, n=n, df=df, avg_len=avg_len)
            if score > 0.0:
                bm25_raw[row] = score

        cos_raw = self._cosine_scores(query, top_k=max(limit * 4, limit))
        if cos_raw is not None:
            result.embedding_used = True
            bm25_norm = _minmax(bm25_raw)
            cos_norm = _minmax(cos_raw)
            candidates = set(bm25_raw) | set(cos_raw)
            # Diary rows sit outside the vector cache, so they have no cosine
            # signal to fuse — they rank on normalized BM25, exactly as every
            # row does when no embedder is configured. Folding in a zero cosine
            # instead would scale them down by (1 - fusion_weight) and bury the
            # diary whenever embedding is on.
            embedded = len(self._docs)
            fused = {
                row: (
                    self._fusion_weight * bm25_norm.get(row, 0.0)
                    + (1 - self._fusion_weight) * cos_norm.get(row, 0.0)
                    if row < embedded
                    else bm25_norm.get(row, 0.0)
                )
                for row in candidates
            }
            ranking = [(row, fused[row]) for row in candidates if fused[row] > 0.0]
        else:
            ranking = list(bm25_raw.items())
        ranking.sort(key=lambda pair: pair[1], reverse=True)
        ranking = ranking[:limit]

        scored: list[RetrievedItem] = []
        for row, rank_score in ranking:
            item, counts, _ = docs[row]
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
        return self._finish(
            scored, result, budget_tokens, expand_links=expand_links, explain=explain
        )

    def _finish(
        self,
        scored: list[RetrievedItem],
        result: RetrievalResult,
        budget_tokens: int | None,
        *,
        expand_links: bool = False,
        explain: bool = False,
    ) -> RetrievalResult:
        """Expand links one hop, then trim to budget — shared by every path."""
        sequence: list[RetrievedItem] = []
        seen: set[tuple[str, str]] = set()
        for hit in scored:
            key = (hit.item.file, hit.item.name)
            if key in seen:
                continue
            seen.add(key)
            sequence.append(hit)
            if not expand_links:
                continue
            for link in hit.item.links:
                target_key = (link.file, link.name)
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
