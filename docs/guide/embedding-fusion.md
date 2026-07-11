# Embedding Fusion

BM25 matches wording. Sometimes you want meaning: "海滨度假" should recall an
item that says "喜欢海边" even with zero shared characters. That is what the
optional `[embed]` extra adds — and **only** that:

```bash
pip install "wikimem[embed]"   # adds httpx + numpy
```

```python
from wikimem import MemoryIndex, MemoryStore
from wikimem.vectors import HttpEmbedder

store = MemoryStore("memory/")
embedder = HttpEmbedder("https://api.example.com/v1", "bge-m3", api_key="sk-…")

index = MemoryIndex(store, embedder=embedder)
result = index.retrieve("海滨度假")   # finds 喜欢海边 with zero shared words
print(result.embedding_used)          # False = endpoint was down, BM25 carried on
```

No `embedder` argument → the entire module is never even imported. The
zero-dependency core stays intact.

## BM25 is never disabled

With an embedder configured, **every query runs both signals**:

1. BM25 scores all items (as always).
2. The query is embedded and cosine-scored against the vector index.
3. Both score sets are **min-max normalized** over the candidate union, then
   fused: `score = w · bm25 + (1 − w) · cos`, with `w = fusion_weight`
   (default `0.5` — the same hybrid formula memU's ADR-0007 converged on).

BM25 catches the wording, cosine catches the meaning, and neither can silently
vanish: an item found by only one signal still enters the candidate set. Tune
`fusion_weight` toward `1.0` for keyword-heavy workloads, toward `0.0` for
paraphrase-heavy ones.

## Fail-open, always

An embedding endpoint is a network dependency, and wikimem refuses to let it
become a point of failure:

- Endpoint down, timeout, bad credentials, malformed response — the cosine
  path returns nothing, retrieval **silently degrades to BM25-only**, and
  `result.embedding_used` is `False`. `retrieve` never raises for a down
  endpoint.
- This is a per-query decision. When the endpoint recovers, fusion resumes on
  the next query — no circuit breaker to reset.

Watch `embedding_used` in your host's logs if you want visibility into how
often the fusion path actually ran.

## The vector cache

Unlike the BM25 index (rebuilt free at startup), vectors cost embedding-API
money to recompute. So they live in a **persistent, incrementally-updated
cache** next to your markdown — with the same "derived state" guarantees as
everything else:

```
memory/
├── preferences.md
├── daily_life.md
├── journal.jsonl
├── vectors-000003.npy     ← float32 matrix, one row per item
└── vectors.keys.jsonl     ← plain text: which row is which item, content-hashed
```

- **Keyed by content hash.** On each index rebuild, only new or changed items
  are embedded (batched 64 per request); unchanged rows are reused without an
  API call. Renaming an item re-embeds just that item.
- **Readable where it matters.** `vectors.keys.jsonl` is plain JSONL — a
  header naming the current `.npy`, then one `{category, name, hash}` line per
  row. The matrix itself is opaque numbers, but *what maps to what* is text.
- **Deletable, always.** Remove both files and the cache rebuilds on the next
  sync. It is never the source of truth.
- **Versioned `.npy` files** (`vectors-000001.npy`, `-000002.npy`, …): Windows
  forbids replacing a file that a live index still memory-maps, so each sync
  writes a new version and sweeps old ones best-effort. Leftover versions are
  cleaned up by later syncs; a torn cache (keys/matrix mismatch) is treated as
  absent and rebuilt, never trusted.

Put the cache elsewhere (out of a synced folder, say) with
`MemoryIndex(store, embedder=..., vectors_dir="…")`.

## RAM story: memmap tiers

Full-precision vectors are never all RAM-resident:

- **Tier 0 — up to `binary_threshold` items (default 10 000):** brute-force
  cosine over a float32 **memmap**. The OS page cache decides what stays hot;
  at personal-memory scale this is microseconds.
- **Tier 1 — above the threshold:** compact 1-bit signatures (96 bytes per
  item at 768 dims) live in RAM for a Hamming-distance coarse ranking; only
  the top `k × 4` candidates are read back from the memmap for exact cosine
  rerank.

The switch is automatic and per-build; `binary_threshold` is a `MemoryIndex`
constructor knob if your accuracy/RAM trade-off differs.

## Bring your own embedder — or index

Two small protocols keep the whole layer pluggable
([reference](/reference/vectors)):

- **`Embedder`** — anything with `embed(texts: list[str]) -> list[list[float]]`.
  `HttpEmbedder` covers any OpenAI-compatible `/embeddings` endpoint (OpenAI,
  SiliconFlow, Ollama, vLLM, …); a local sentence-transformers wrapper is a
  five-line class.
- **`VectorIndex`** — the search port: `search(query, top_k) -> [(row, score)]`.
  The built-in `MemmapVectorIndex` is the default backend; heavier ones
  (sqlite-vec, Qdrant local, …) adapt behind the same surface without touching
  retrieval code. (Interface borrowed from mem0's VectorStore abstraction —
  the port, not the backend.)
